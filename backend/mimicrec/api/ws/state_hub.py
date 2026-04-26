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
                    payload: dict = {
                        "joint_pos": s.value.joint_pos.tolist(),
                        "joint_vel": s.value.joint_vel.tolist(),
                        "joint_effort": s.value.joint_effort.tolist(),
                        "t_mono_ns": s.t_mono_ns,
                    }
                    # Prefer EE already on RobotState (daemon-supplied);
                    # else fall back to local FK if configured.
                    if s.value.ee_pos is not None:
                        payload["ee_pos"] = s.value.ee_pos.tolist()
                        payload["ee_rotvec"] = (
                            s.value.ee_rotvec.tolist()
                            if s.value.ee_rotvec is not None
                            else None
                        )
                        if s.value.gripper_pos is not None:
                            payload["gripper_pos"] = float(s.value.gripper_pos)
                    else:
                        fk = getattr(sm, "_fk", None)
                        if fk is not None:
                            try:
                                n = fk.n_kin_joints
                                ee_pos, ee_rotvec = fk.pose(s.value.joint_pos[:n])
                                payload["ee_pos"] = ee_pos.tolist()
                                payload["ee_rotvec"] = ee_rotvec.tolist()
                                if s.value.joint_pos.shape[0] > n:
                                    payload["gripper_pos"] = float(s.value.joint_pos[n])
                            except Exception:
                                # FK errors here shouldn't kill the state stream
                                pass
                    await websocket.send_json(payload)
            # Use receive with timeout for clean disconnect handling
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=1 / 15)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
