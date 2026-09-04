from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

import pytest
import websockets


PACKAGE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "integrations/ros2/mimicrec_quest_bridge"
)
sys.path.insert(0, str(PACKAGE_ROOT))
from mimicrec_quest_bridge.transport import MimicRecWebSocketTransport  # noqa: E402


@pytest.mark.asyncio
async def test_transport_forwards_pose_offset_and_camera_jpeg():
    teleop_messages: list[dict] = []
    camera_frames: list[tuple[str, bytes]] = []
    teleop_states: list[bool] = []

    async def handler(connection):
        path = connection.request.path
        if path == "/ws/teleop":
            await connection.send(json.dumps({"type": "init", "input_mode": "ee_delta"}))
            async for raw_message in connection:
                teleop_messages.append(json.loads(raw_message))
        elif path == "/ws/cameras/front":
            await connection.send(b"\xff\xd8jpeg")
            await asyncio.sleep(2.0)
        else:
            await connection.close(code=1008, reason="unknown path")

    server = await websockets.serve(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    transport = MimicRecWebSocketTransport(
        base_url=f"ws://127.0.0.1:{port}",
        camera_names=["front"],
        on_camera=lambda name, data, _timestamp: camera_frames.append((name, data)),
        on_teleop_state=teleop_states.append,
    )
    transport.start()
    transport.send_pose_offset([0.1, 0, 0, 0, 0, 0.5], 0.2)
    stopped = False
    try:
        for _ in range(100):
            if (
                any(message.get("cmd") == "ee_pose_offset" for message in teleop_messages)
                and camera_frames
            ):
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("bridge did not forward teleop and camera data in time")

        pose_offset = next(
            message for message in teleop_messages if message.get("cmd") == "ee_pose_offset"
        )
        assert pose_offset["offset"] == [0.1, 0.0, 0.0, 0.0, 0.0, 0.5]
        assert pose_offset["gripper_fraction"] == pytest.approx(0.2)
        assert camera_frames == [("front", b"\xff\xd8jpeg")]

        assert transport.send_home() is True
        for _ in range(50):
            if any(message.get("cmd") == "home" for message in teleop_messages):
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("bridge did not forward the home event in time")
        assert sum(message.get("cmd") == "home" for message in teleop_messages) == 1

        await asyncio.to_thread(transport.stop)
        stopped = True
        assert teleop_messages[-1] == {"cmd": "stop"}
        assert teleop_states == [True, False]
    finally:
        if not stopped:
            await asyncio.to_thread(transport.stop)
        server.close()
        await server.wait_closed()


def test_home_event_is_rejected_while_disconnected():
    transport = MimicRecWebSocketTransport(
        base_url="ws://127.0.0.1:1",
        camera_names=[],
        on_camera=lambda *_args: None,
    )
    assert transport.send_home() is False


def test_transport_tags_motion_messages_with_channel():
    transport = MimicRecWebSocketTransport(
        base_url="ws://127.0.0.1:1",
        camera_names=[],
        on_camera=lambda *_args: None,
        motion_channel="left",
    )

    transport.send_pose_offset([0, 0, 0, 0, 0, 0], 0.5)
    _sequence, message = transport._snapshot_message()
    transport.send_stop()
    _stop_sequence, stop = transport._snapshot_message()

    assert message["channel"] == "left"
    assert stop == {"cmd": "stop", "channel": "left"}


def test_transport_sends_world_absolute_pose_for_lossless_control():
    transport = MimicRecWebSocketTransport(
        base_url="ws://127.0.0.1:1",
        camera_names=[],
        on_camera=lambda *_args: None,
        motion_channel="left",
    )

    transport.send_world_pose_offset(
        [0.1, 0, 0, 0, 0.2, 0], [0.0, 0.2, 0.0], 0.4
    )
    _sequence, message = transport._snapshot_message()

    assert message == {
        "cmd": "ee_world_pose_offset",
        "offset": [0.1, 0.0, 0.0, 0.0, 0.2, 0.0],
        "control_rotation": [0.0, 0.2, 0.0],
        "gripper_fraction": 0.4,
        "channel": "left",
    }
