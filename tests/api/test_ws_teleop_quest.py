from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
from httpx import AsyncClient
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

from mimicrec.adapters.web_teleop import QuestRosTeleoperator
from mimicrec.api.app import create_app
from mimicrec.util.latest_value import LatestValue


async def test_quest_pose_websocket_reaches_teleoperator_and_disconnect_stops():
    app = create_app()
    teleop = QuestRosTeleoperator(control_rate_hz=50)
    robot = SimpleNamespace(dof=6, joint_names=[f"j{index}" for index in range(6)])
    app.state.session_manager = SimpleNamespace(
        _teleop=teleop,
        _robot=robot,
        _robot_state_slot=LatestValue(),
    )

    async with ASGIWebSocketTransport(app=app) as transport:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with aconnect_ws("/ws/teleop", client) as websocket:
                init = await websocket.receive_json()
                assert init["input_mode"] == "ee_delta"
                assert "ee_pose_offset" in init["accepted_commands"]
                assert "ee_world_delta" in init["accepted_commands"]
                assert "ee_world_pose_offset" in init["accepted_commands"]
                await websocket.send_json(
                    {
                        "cmd": "ee_pose_offset",
                        "offset": [0.1, 0, 0, 0, 0, 0.5],
                        "gripper_fraction": 0.7,
                    }
                )
                await asyncio.sleep(0)
                action = await teleop.read_action()
                assert np.allclose(action.ee_pose_offset, [0.1, 0, 0, 0, 0, 0.5])
                assert action.ee_pose_active is True
                assert action.gripper_fraction == 0.7

    action = await teleop.read_action()
    assert np.allclose(action.ee_delta, 0.0)
    assert action.ee_pose_active is False
    assert action.gripper_delta == 0.0
