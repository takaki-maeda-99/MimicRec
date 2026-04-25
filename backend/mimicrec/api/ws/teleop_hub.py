"""WebSocket endpoint for browser-based teleop input.

Receives JSON messages from the frontend:
    {"joint": 0, "delta": 0.05}
    {"cmd": "reset"}

Forwards them to the WebTeleoperator's input queue.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/teleop")
async def ws_teleop(websocket: WebSocket):
    await websocket.accept()
    app = websocket.app
    sm = getattr(app.state, "session_manager", None)

    # Find the WebTeleoperator if one is active
    teleop = None
    if sm and hasattr(sm, "_teleop") and sm._teleop is not None:
        from mimicrec.adapters.web_teleop import WebTeleoperator
        if isinstance(sm._teleop, WebTeleoperator):
            teleop = sm._teleop

    if teleop is None:
        await websocket.close(code=1008, reason="no web teleop active")
        return

    # Send initial state so frontend knows current joint positions
    state = sm._robot_state_slot.peek()
    if state is not None:
        # Initialize teleop target to current robot position
        await teleop.input_queue.put({
            "cmd": "reset",
            "pos": state.value.joint_pos.tolist(),
        })
        await websocket.send_json({
            "type": "init",
            "dof": teleop._dof,
            "joint_names": sm._robot.joint_names,
            "joint_pos": state.value.joint_pos.tolist(),
        })

    try:
        while True:
            data = await websocket.receive_json()
            await teleop.input_queue.put(data)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
