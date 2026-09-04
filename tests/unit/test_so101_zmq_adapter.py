import numpy as np
import pytest

from mimicrec.adapters.robot import RobotMode
from mimicrec.adapters.so101_protocol import (
    CMD_READ_STATE,
    CMD_SEND_COMMAND,
    CMD_SEND_GRIPPER_COMMAND,
    CMD_SET_MODE,
    MODE_TORQUE_OFF,
    MODE_POSITION,
)
from mimicrec.adapters.so101_zmq import SO101ZmqAdapter
from mimicrec.motion.types import JointPositionCommand, ScalarPositionCommand


class _Adapter(SO101ZmqAdapter):
    def __init__(self):
        super().__init__()
        self.requests = []

    async def _request(self, message):
        self.requests.append(message)
        if message["cmd"] == CMD_READ_STATE:
            return {
                "ok": True,
                "joint_pos": [1, 2, 3, 4, 5],
                "joint_vel": [0, 0, 0, 0, 0],
                "joint_effort": [0, 0, 0, 0, 0],
                "target_joint_pos": [1.5, 2.5, 3.5, 4.5, 5.5],
                "gripper_pos": 25,
                "t_mono_ns": 123,
            }
        return {"ok": True}


@pytest.mark.asyncio
async def test_resource_adapter_sends_arm_and_gripper_atomically():
    adapter = _Adapter()

    states = await adapter.read_resources()
    await adapter.send_commands({
        "arm": JointPositionCommand(np.array([5, 4, 3, 2, 1])),
        "gripper": ScalarPositionCommand(75),
    })

    assert states["arm"].position == pytest.approx(np.deg2rad([1, 2, 3, 4, 5]))
    assert states["arm"].target_position == pytest.approx(
        np.deg2rad([1.5, 2.5, 3.5, 4.5, 5.5])
    )
    assert states["gripper"].position == pytest.approx(25)
    assert adapter.requests[-1] == {
        "cmd": CMD_SEND_COMMAND,
        "q": pytest.approx(np.rad2deg([5, 4, 3, 2, 1]).tolist()),
        "gripper": 75.0,
    }


@pytest.mark.asyncio
async def test_legacy_gripper_command_maps_normalized_value_to_raw_range():
    adapter = _Adapter()

    await adapter.send_gripper_command(0.4)

    assert adapter.requests[-1]["gripper"] == pytest.approx(40.0)


@pytest.mark.asyncio
async def test_safe_stop_requests_daemon_torque_off():
    adapter = _Adapter()

    await adapter.safe_stop()

    assert adapter.requests[-1] == {
        "cmd": CMD_SET_MODE,
        "mode": MODE_TORQUE_OFF,
    }
    assert adapter.supports_mode(RobotMode.GRAVITY_COMP) is False


@pytest.mark.asyncio
async def test_activate_enters_seeded_position_mode():
    adapter = _Adapter()

    await adapter.activate()

    assert adapter.requests[-1] == {
        "cmd": CMD_SET_MODE,
        "mode": MODE_POSITION,
    }


@pytest.mark.asyncio
async def test_clear_estop_reenters_seeded_position_mode():
    adapter = _Adapter()

    result = await adapter.clear_estop()

    assert result == {"ok": True, "mode": "position"}
    assert adapter.requests[-1] == {
        "cmd": CMD_SET_MODE,
        "mode": "position",
    }
