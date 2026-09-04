"""WebSocket endpoint for browser-based teleop input.

Receives JSON messages from the frontend:
    {"joint": 0, "delta": 0.05}
    {"cmd": "reset"}
    {"cmd": "ee_axes", "axes": [..6..], "gripper": 0.0}
    {"cmd": "ee_velocity", "velocity": [..6..], "gripper_velocity": 0.0}
    {"cmd": "ee_pose_offset", "offset": [..6..], "gripper_fraction": 0.0}
    {"cmd": "ee_world_pose_offset", "offset": [..6..], "gripper_fraction": 0.0}
    {"cmd": "home"}
    {"cmd": "stop"}

Forwards them to the WebTeleoperator's input queue.
"""

from __future__ import annotations

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
        candidate = sm._teleop
        # MotionTeleopRouter intentionally exposes the same narrow queue /
        # control-mode surface as WebTeleoperator without pretending to be
        # one robot-specific input device.
        if hasattr(candidate, "input_queue") and hasattr(candidate, "control_mode"):
            teleop = candidate

    if teleop is None:
        await websocket.close(code=1008, reason="no web teleop active")
        return

    # Send initial state so frontend knows current joint positions
    state = sm._robot_state_slot.peek()
    if state is not None:
        # Initialize teleop target to current robot position
        await teleop.input_queue.put(
            {
                "cmd": "reset",
                "pos": state.value.joint_pos.tolist(),
            }
        )
    if state is not None or teleop.control_mode == "ee_delta":
        await websocket.send_json(
            {
                "type": "init",
                "input_mode": teleop.control_mode,
                "accepted_commands": (
                    ["ee_axes", "ee_velocity", "ee_pose_offset", "ee_world_delta", "ee_world_pose_offset", "home", "stop", "channel"]
                    if teleop.control_mode == "ee_delta"
                    else ["reset", "joint"]
                ),
                "dof": sm._robot.dof
                if teleop.control_mode == "ee_delta"
                else teleop._dof,
                "joint_names": sm._robot.joint_names,
                "joint_pos": state.value.joint_pos.tolist()
                if state is not None
                else [],
            }
        )

    connection_channels: set[str] = set()
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("channel") is not None:
                connection_channels.add(str(data["channel"]))
            await teleop.input_queue.put(data)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        # A dropped input socket must release any held Cartesian motion.
        if connection_channels:
            for channel in connection_channels:
                teleop.stop_motion(channel)
        else:
            teleop.stop_motion()
