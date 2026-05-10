"""GravityCompController velocity-taper behavior.

Without the taper the Coulomb friction comp ``friction_tau * sign(qdot)``
keeps pushing in the motion direction at any |qdot|, so a residual coast
settles at the runaway terminal velocity ``friction_tau / kd``. With the
taper, the comp scales by ``max(0, 1 - |qdot| / v_taper)`` so it fades
to zero before damping has to fight a constant push. v_taper=0 disables
the taper on a joint and reproduces the legacy constant-comp behavior.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pytest


# The controller imports from reBotArm_control_py at module load time;
# stub the dynamics module so the test runs without the (large) C++/URDF
# dependency. Gravity is forced to zero so the assertions can isolate the
# friction term.
_dyn_stub = types.ModuleType("reBotArm_control_py.dynamics")
_dyn_stub.compute_generalized_gravity = lambda q: np.zeros(len(q))
_dyn_stub.load_dynamics_model = lambda: None
sys.modules.setdefault("reBotArm_control_py", types.ModuleType("reBotArm_control_py"))
sys.modules["reBotArm_control_py.dynamics"] = _dyn_stub

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from rebotarm_daemon.config import GravityCompParams  # noqa: E402
from rebotarm_daemon.controllers import GravityCompController  # noqa: E402


class _FakeArm:
    """Minimal stand-in for the reBotArm interface used by the controller."""

    def __init__(self, q: np.ndarray, qdot: np.ndarray):
        self._q = np.asarray(q, dtype=float)
        self._qdot = np.asarray(qdot, dtype=float)
        self.last_tau: np.ndarray | None = None

    def get_positions(self) -> np.ndarray:
        return self._q.copy()

    def get_velocities(self) -> np.ndarray:
        return self._qdot.copy()

    def mit(self, *, pos, vel, kp, kd, tau, request_feedback) -> None:
        self.last_tau = np.asarray(tau, dtype=float).copy()


def _step_with(qdot: np.ndarray, params: GravityCompParams) -> np.ndarray:
    n = len(qdot)
    arm = _FakeArm(q=np.zeros(n), qdot=qdot)
    ctrl = GravityCompController(params, num_joints=n)
    ctrl.step(arm)
    assert arm.last_tau is not None
    return arm.last_tau


def test_taper_zero_keeps_full_friction_comp():
    """v_taper=0 disables the taper — comp stays at friction_tau regardless of speed."""
    params = GravityCompParams(
        kp=[0.0],
        kd=[0.4],
        friction_tau_nm=[0.9],
        vel_deadband_rad_s=[0.02],
        friction_vel_taper_rad_s=[0.0],
    )
    tau_low = _step_with(np.array([0.05]), params)
    tau_high = _step_with(np.array([2.0]), params)
    assert tau_low[0] == pytest.approx(0.9)
    assert tau_high[0] == pytest.approx(0.9)


def test_taper_full_at_low_speed():
    """At |qdot| just past the deadband, the taper coefficient is ~1."""
    params = GravityCompParams(
        kp=[0.0],
        kd=[0.4],
        friction_tau_nm=[0.9],
        vel_deadband_rad_s=[0.02],
        friction_vel_taper_rad_s=[1.5],
    )
    tau = _step_with(np.array([0.05]), params)
    # 0.9 * (1 - 0.05/1.5) = 0.9 * 0.9667 ≈ 0.870
    assert tau[0] == pytest.approx(0.9 * (1.0 - 0.05 / 1.5), rel=1e-6)


def test_taper_zero_at_v_taper():
    """At |qdot| == v_taper the comp drops to zero exactly."""
    params = GravityCompParams(
        kp=[0.0],
        kd=[0.4],
        friction_tau_nm=[0.9],
        vel_deadband_rad_s=[0.02],
        friction_vel_taper_rad_s=[1.5],
    )
    tau = _step_with(np.array([1.5]), params)
    assert tau[0] == pytest.approx(0.0)


def test_taper_clipped_to_zero_above_v_taper():
    """Above v_taper the comp must not go negative — clipped to 0."""
    params = GravityCompParams(
        kp=[0.0],
        kd=[0.4],
        friction_tau_nm=[0.9],
        vel_deadband_rad_s=[0.02],
        friction_vel_taper_rad_s=[1.5],
    )
    tau = _step_with(np.array([3.0]), params)
    assert tau[0] == pytest.approx(0.0)


def test_taper_respects_deadband_and_sign():
    """Inside the deadband sign() is zero so the comp is suppressed even if taper>0."""
    params = GravityCompParams(
        kp=[0.0],
        kd=[0.4],
        friction_tau_nm=[0.9],
        vel_deadband_rad_s=[0.1],
        friction_vel_taper_rad_s=[1.5],
    )
    tau_inside = _step_with(np.array([0.05]), params)  # below deadband
    tau_negative = _step_with(np.array([-0.5]), params)  # above deadband, negative dir
    assert tau_inside[0] == pytest.approx(0.0)
    # 0.9 * (-1) * (1 - 0.5/1.5) = -0.9 * 0.6667 = -0.6
    assert tau_negative[0] == pytest.approx(-0.9 * (1.0 - 0.5 / 1.5), rel=1e-6)


def test_taper_per_joint_independent():
    """Per-joint v_taper: a 0 entry must keep that joint at full comp while
    its neighbor tapers normally."""
    params = GravityCompParams(
        kp=[0.0, 0.0],
        kd=[0.4, 0.4],
        friction_tau_nm=[0.9, 0.9],
        vel_deadband_rad_s=[0.02, 0.02],
        friction_vel_taper_rad_s=[0.0, 1.5],  # joint 0 disabled, joint 1 tapered
    )
    tau = _step_with(np.array([1.0, 1.0]), params)
    assert tau[0] == pytest.approx(0.9)  # untapered
    assert tau[1] == pytest.approx(0.9 * (1.0 - 1.0 / 1.5), rel=1e-6)
