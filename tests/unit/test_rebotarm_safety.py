import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import numpy as np
import pytest
from rebotarm_daemon.config import SafetyLimits
from rebotarm_daemon.safety import SafetyManager


def _mgr(**overrides) -> SafetyManager:
    defaults = dict(
        joint_pos_min_rad=[-1.0] * 6,
        joint_pos_max_rad=[1.0] * 6,
        joint_vel_max_rad_s=1.0,
        joint_accel_max_rad_s2=10.0,
        torque_max_nm=[5.0] * 6,
        temperature_warn_c=60.0,
        temperature_fault_c=70.0,
        temperature_recover_c=50.0,
        heartbeat_timeout_ms=200,
    )
    defaults.update(overrides)
    return SafetyManager(SafetyLimits(**defaults), dof=6)


def test_clamp_joint_pos_to_bounds():
    m = _mgr()
    q = np.array([2.0, -2.0, 0.5, 0.5, 0.5, 0.5])
    out = m.clamp_joint_pos(q)
    assert out[0] == 1.0
    assert out[1] == -1.0
    assert out[2] == 0.5


def test_velocity_ramp_limits_step_size():
    m = _mgr()
    q_now = np.zeros(6)
    q_target = np.array([10.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    dt = 0.01
    out = m.ramp_velocity(q_now, q_target, dt)
    # max step = vel_max * dt = 1.0 * 0.01 = 0.01
    assert out[0] == pytest.approx(0.01, abs=1e-6)


def test_torque_clamp_per_joint():
    m = _mgr()
    tau = np.array([100, -100, 0, 0, 0, 0], dtype=float)
    out = m.clamp_torque(tau)
    assert out[0] == 5.0
    assert out[1] == -5.0


def test_thermal_warn_then_fault_then_recover():
    m = _mgr()
    assert m.evaluate_thermal(np.array([55] * 6)) == "ok"
    assert m.evaluate_thermal(np.array([65] * 6)) == "warn"
    fault = m.evaluate_thermal(np.array([72] * 6))
    assert fault == "thermal_fault"
    # state stays in fault even when temp drops to warn band
    assert m.evaluate_thermal(np.array([55] * 6)) == "thermal_fault"
    # cooling below recover threshold + clear request returns to ok
    m.evaluate_thermal(np.array([45] * 6))
    assert m.try_clear_estop(np.array([45] * 6)) is True
    assert m.evaluate_thermal(np.array([45] * 6)) == "ok"


def test_estop_then_clear():
    m = _mgr()
    m.trigger_estop()
    assert m.is_active_fault()
    assert m.try_clear_estop(np.array([20] * 6)) is True
    assert not m.is_active_fault()


def test_clear_estop_blocked_when_thermal_fault_active():
    m = _mgr()
    m.evaluate_thermal(np.array([72] * 6))  # enters thermal fault
    m.trigger_estop()
    # too hot to recover
    assert m.try_clear_estop(np.array([55] * 6)) is False


def test_heartbeat_timeout_after_silence():
    m = _mgr(heartbeat_timeout_ms=50)
    m.note_heartbeat()
    assert m.heartbeat_state(time.monotonic()) == "ok"
    later = time.monotonic() + 0.1
    assert m.heartbeat_state(later) == "heartbeat_timeout"
