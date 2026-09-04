import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from so101_daemon.config import (  # noqa: E402
    ARM_JOINT_NAMES,
    SO101DaemonConfig,
    SO101Limits,
    load_daemon_config,
)
from so101_daemon.core import (  # noqa: E402
    CMD_CONNECT,
    CMD_DISCONNECT,
    CMD_HEARTBEAT,
    CMD_SEND_COMMAND,
    CMD_SEND_GRIPPER_COMMAND,
    CMD_SET_MODE,
    MODE_POSITION,
    MODE_TORQUE_OFF,
    SO101DaemonCore,
)


class _Clock:
    def __init__(self):
        self.now = 10.0

    def __call__(self):
        return self.now


class _Hardware:
    def __init__(self):
        self.positions = {
            "shoulder_pan": 1.0,
            "shoulder_lift": 2.0,
            "elbow_flex": 3.0,
            "wrist_flex": 4.0,
            "wrist_roll": 5.0,
            "gripper": 6.0,
        }
        self.sent = []
        self.torque_enabled = False
        self.disable_count = 0

    def read(self):
        return {f"{key}.pos": value for key, value in self.positions.items()}

    def send(self, values):
        self.sent.append(dict(values))

    def hold_current_and_enable_torque(self):
        self.torque_enabled = True
        return self.read()

    def disable_torque(self):
        self.torque_enabled = False
        self.disable_count += 1


def _core():
    clock = _Clock()
    hardware = _Hardware()
    config = SO101DaemonConfig(
        heartbeat_timeout_ms=500,
        limits=SO101Limits(max_joint_step_deg=2.0),
    )
    core = SO101DaemonCore(config, hardware, monotonic=clock)
    core._update_state_locked(hardware.read())
    return core, hardware, clock


def test_daemon_config_supports_named_arm_pid_overrides(tmp_path):
    path = tmp_path / "so101.yaml"
    path.write_text(
        "arm_p_coefficient: 96\n"
        "arm_p_coefficients:\n"
        "  shoulder_pan: 32\n"
        "  shoulder_lift: 120\n"
        "  elbow_flex: 96\n"
        "  wrist_flex: 120\n"
        "  wrist_roll: 32\n"
        "arm_i_coefficient: 0\n"
        "gripper_p_coefficient: 32\n"
        "gripper_i_coefficient: 0\n"
        "gripper_d_coefficient: 24\n"
        "arm_acceleration: 50\n"
        "arm_goal_velocity: 20\n"
    )

    config = load_daemon_config(path)

    assert config.arm_p_coefficient == 96
    assert config.arm_acceleration == 50
    assert config.arm_goal_velocity == 20
    assert config.arm_p_coefficients == {
        "shoulder_pan": 32,
        "shoulder_lift": 120,
        "elbow_flex": 96,
        "wrist_flex": 120,
        "wrist_roll": 32,
    }
    assert config.arm_i_coefficient == 0
    assert config.gripper_p_coefficient == 32
    assert config.gripper_i_coefficient == 0
    assert config.gripper_d_coefficient == 24


def test_repository_config_names_every_arm_p_gain_explicitly():
    config_path = Path(__file__).resolve().parents[2] / "configs" / "so101_daemon.yaml"

    config = load_daemon_config(config_path)

    assert set(config.arm_p_coefficients) == set(ARM_JOINT_NAMES)


def test_daemon_config_rejects_unknown_pid_joint():
    with pytest.raises(ValueError, match="unknown arm_p_coefficients"):
        SO101DaemonConfig(arm_p_coefficients={"not_a_joint": 120})

    with pytest.raises(ValueError, match="arm_acceleration"):
        SO101DaemonConfig(arm_acceleration=0)

    with pytest.raises(ValueError, match="arm_goal_velocity"):
        SO101DaemonConfig(arm_goal_velocity=4096)


def test_position_mode_requires_client_lease_and_seeds_current_hold():
    core, hardware, _ = _core()

    denied = core.handle({"cmd": CMD_SET_MODE, "mode": MODE_POSITION})
    connected = core.handle({"cmd": CMD_CONNECT})
    enabled = core.handle({"cmd": CMD_SET_MODE, "mode": MODE_POSITION})

    assert denied["ok"] is False
    assert connected["resources"] == ["arm", "gripper"]
    assert enabled == {"ok": True, "mode": MODE_POSITION}
    assert hardware.torque_enabled


def test_status_reports_cached_bus_voltage():
    core, hardware, _ = _core()
    observation = hardware.read()
    observation["_voltage_raw"] = {
        "shoulder_pan": 49,
        "gripper": 48,
    }
    core._update_state_locked(observation)

    status = core.handle({"cmd": "get_status"})

    assert status["voltage_raw"] == {
        "shoulder_pan": 49,
        "gripper": 48,
    }


def test_arm_command_clamps_joint_limits_and_per_command_step():
    core, hardware, _ = _core()
    core.handle({"cmd": CMD_CONNECT})
    core.handle({"cmd": CMD_SET_MODE, "mode": MODE_POSITION})

    reply = core.handle({"cmd": CMD_SEND_COMMAND, "q": [100, -100, 100, -100, 100]})

    assert reply["ok"] is True
    assert reply["applied_q"] == pytest.approx([3, 0, 5, 2, 7])
    assert hardware.sent[-1]["shoulder_pan"] == pytest.approx(3)
    assert core._state_reply_locked()["target_joint_pos"] == pytest.approx(
        [3, 0, 5, 2, 7]
    )


def test_arm_and_gripper_are_applied_in_one_hardware_write():
    core, hardware, _ = _core()
    core.handle({"cmd": CMD_CONNECT})
    core.handle({"cmd": CMD_SET_MODE, "mode": MODE_POSITION})

    reply = core.handle({
        "cmd": CMD_SEND_COMMAND,
        "q": [1, 2, 3, 4, 5],
        "gripper": 75,
    })

    assert reply["ok"] is True
    assert reply["applied_gripper"] == pytest.approx(75)
    assert hardware.sent[-1] == {
        "shoulder_pan": pytest.approx(1),
        "shoulder_lift": pytest.approx(2),
        "elbow_flex": pytest.approx(3),
        "wrist_flex": pytest.approx(4),
        "wrist_roll": pytest.approx(5),
        "gripper": pytest.approx(75),
    }


def test_gripper_is_clamped_to_configured_safe_range():
    core, hardware, _ = _core()
    core.handle({"cmd": CMD_CONNECT})
    core.handle({"cmd": CMD_SET_MODE, "mode": MODE_POSITION})

    reply = core.handle({"cmd": CMD_SEND_GRIPPER_COMMAND, "gripper": 900})

    assert reply == {"ok": True, "applied_gripper": 100.0}
    assert hardware.sent[-1] == {"gripper": 100.0}


def test_expired_heartbeat_fails_closed_and_does_not_auto_resume():
    core, hardware, clock = _core()
    core.handle({"cmd": CMD_CONNECT})
    core.handle({"cmd": CMD_SET_MODE, "mode": MODE_POSITION})
    clock.now += 0.6

    rejected = core.handle({"cmd": CMD_SEND_COMMAND, "q": [1, 2, 3, 4, 5]})

    assert rejected["ok"] is False
    assert hardware.torque_enabled is False
    assert core.handle({"cmd": CMD_HEARTBEAT})["ok"] is True
    assert core.handle({"cmd": CMD_SEND_COMMAND, "q": [1, 2, 3, 4, 5]})["ok"] is False
    assert core.handle({"cmd": CMD_SET_MODE, "mode": MODE_POSITION})["ok"] is True


def test_disconnect_always_disables_torque():
    core, hardware, _ = _core()
    core.handle({"cmd": CMD_CONNECT})
    core.handle({"cmd": CMD_SET_MODE, "mode": MODE_POSITION})

    reply = core.handle({"cmd": CMD_DISCONNECT})

    assert reply == {"ok": True, "mode": MODE_TORQUE_OFF}
    assert hardware.torque_enabled is False
