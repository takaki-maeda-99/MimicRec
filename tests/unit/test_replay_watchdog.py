import pytest
import numpy as np

from mimicrec.errors import ReplaySafetyError
from mimicrec.session.replay_safety import ReplaySafetyConfig, ReplayWatchdog


def _cfg(**overrides) -> ReplaySafetyConfig:
    base = ReplaySafetyConfig(
        ramp_duration_sec=2.0,
        max_joint_velocity=1.0,
        max_joint_acceleration=5.0,
        max_joint_position_jump=0.3,
        command_timeout_sec=0.2,
        watchdog_hz=20,
        dof=2,
        dt_sec=1 / 30,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_position_jump_trips():
    wd = ReplayWatchdog(_cfg(max_joint_position_jump=0.05))
    target = np.array([0.5, 0.0], dtype=np.float32)
    measured = np.array([0.0, 0.0], dtype=np.float32)
    with pytest.raises(ReplaySafetyError) as e:
        wd.check(target=target, prev_target=None, prev_prev_target=None, measured=measured)
    assert "joint_position_jump" in str(e.value)


def test_velocity_trips():
    wd = ReplayWatchdog(_cfg(max_joint_velocity=0.1, dt_sec=1 / 30))
    prev = np.array([0.0, 0.0], dtype=np.float32)
    target = np.array([0.1, 0.0], dtype=np.float32)
    measured = np.array([0.05, 0.0], dtype=np.float32)
    with pytest.raises(ReplaySafetyError) as e:
        wd.check(target=target, prev_target=prev, prev_prev_target=None, measured=measured)
    assert "joint_velocity" in str(e.value)


def test_acceleration_trips():
    wd = ReplayWatchdog(_cfg(max_joint_acceleration=1.0, max_joint_velocity=1000.0, max_joint_position_jump=10.0, dt_sec=1 / 30))
    prev_prev = np.array([0.0, 0.0], dtype=np.float32)
    prev = np.array([0.01, 0.0], dtype=np.float32)
    target = np.array([1.0, 0.0], dtype=np.float32)
    measured = np.array([0.01, 0.0], dtype=np.float32)
    with pytest.raises(ReplaySafetyError) as e:
        wd.check(target=target, prev_target=prev, prev_prev_target=prev_prev, measured=measured)
    assert "joint_acceleration" in str(e.value)


def test_command_timeout_trips():
    wd = ReplayWatchdog(_cfg(command_timeout_sec=0.05))
    wd.note_command_sent(t_mono_ns=1_000_000_000)
    with pytest.raises(ReplaySafetyError) as e:
        wd.assert_fresh(now_t_mono_ns=1_000_000_000 + 200_000_000)
    assert "command_timeout" in str(e.value)


def test_within_all_limits_does_not_trip():
    wd = ReplayWatchdog(_cfg())
    target = np.array([0.1, 0.1], dtype=np.float32)
    measured = np.array([0.1, 0.1], dtype=np.float32)
    wd.check(target=target, prev_target=target, prev_prev_target=target, measured=measured)
