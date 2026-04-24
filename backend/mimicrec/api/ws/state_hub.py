from __future__ import annotations
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from mimicrec.api.deps import get_session_manager_or_none

router = APIRouter()


@router.websocket("/ws/state")
async def ws_state(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            sm = get_session_manager_or_none(websocket.app)
            if sm:
                s = sm._robot_state_slot.peek()
                if s is not None:
                    await websocket.send_json({
                        "joint_pos": s.value.joint_pos.tolist(),
                        "joint_vel": s.value.joint_vel.tolist(),
                        "joint_effort": s.value.joint_effort.tolist(),
                        "t_mono_ns": s.t_mono_ns,
                    })
            # Use receive with timeout for clean disconnect handling
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=1 / 15)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
