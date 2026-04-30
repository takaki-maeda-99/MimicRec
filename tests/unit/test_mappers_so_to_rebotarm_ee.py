"""Unit tests for SOToReBotArmEEMapper (delta mode).

The mapper accumulates SO-101 EE deltas onto a running reBotArm EE
target initialized from the live ``state.joint_pos`` on the first
tick. These tests verify that the delta semantics, scale, yaw drop,
discontinuity / workspace / joint-step guards, and the gripper map
all behave as documented.

Skips when placo is not installed.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mimicrec.types import RobotState, TeleopAction


pytest.importorskip("placo")

from mimicrec.mappers.so_to_rebotarm_ee import SOToReBotArmEEMapper  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[2]
SO101_URDF = str(REPO_ROOT / "configs/urdf/so101/so101.urdf")
REBOTARM_URDF = str(
    REPO_ROOT
    / "reBotArm_control_py/urdf/reBot-DevArm_fixend_description/urdf/reBot-DevArm_fixend.urdf"
)


def _state(q_rad: np.ndarray | None = None) -> RobotState:
    if q_rad is None:
        q_rad = np.zeros(6, dtype=np.float32)
    return RobotState(
        joint_pos=q_rad.astype(np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
    )


def _action(so101_deg: list[float]) -> TeleopAction:
    return TeleopAction(target_joint_pos=np.asarray(so101_deg, dtype=np.float32))


def _mk_mapper(**overrides) -> SOToReBotArmEEMapper:
    kwargs = dict(
        so101_urdf_path=SO101_URDF,
        rebotarm_urdf_path=REBOTARM_URDF,
        # Default to all guards disabled so most tests can exercise
        # raw mapper behavior. Individual guard tests re-enable the
        # guard they're verifying.
        max_ee_step_m=0.0,
        workspace_radius_m=0.0,
        workspace_z_min_m=-100.0,
        workspace_z_max_m=100.0,
        max_joint_step_deg=0.0,
    )
    kwargs.update(overrides)
    return SOToReBotArmEEMapper(**kwargs)


# --- Basic shape & init -------------------------------------------------


def test_first_tick_holds_at_state():
    """First tick must hold the arm at the current pose (anchor only,
    no motion). target_pos / prev SO101 are recorded."""
    m = _mk_mapper()
    seed = np.deg2rad([5.0, -10.0, 15.0, 0.0, 0.0, 0.0]).astype(np.float32)
    cmd = m.map(_action([0, 0, 0, 0, 0, 0]), _state(seed))
    assert cmd.q.shape == (6,)
    assert np.isfinite(cmd.q).all()
    assert np.allclose(cmd.q, seed, atol=1e-6), \
        "first tick should hold q at the live state"
    # Internal state primed for delta accumulation
    assert m._target_pos is not None and m._target_R is not None
    assert m._prev_so_pos is not None and m._prev_so_R is not None


def test_first_tick_runs_gripper_map():
    """Even on the held first tick, gripper should follow the leader."""
    m = _mk_mapper()
    cmd = m.map(_action([0, 0, 0, 0, 0, 50.0]), _state())
    assert cmd.gripper == pytest.approx(0.5, abs=1e-6)


# --- Delta accumulation -------------------------------------------------


def test_delta_accumulates_into_target_pos():
    """A second tick with a moved SO-101 must shift _target_pos by
    xyz_scale * Δp_so101."""
    m = _mk_mapper(xyz_scale=1.5)
    m.map(_action([0, 0, 0, 0, 0, 0]), _state())  # tick 1, anchor
    target_before = m._target_pos.copy()
    so_before = m._prev_so_pos.copy()

    # Perturb wrist_flex slightly to move the SO-101 EE pos.
    m.map(_action([0, 0, 0, 5.0, 0, 0]), _state())
    target_after = m._target_pos.copy()
    so_after = m._prev_so_pos.copy()

    expected_dp = 1.5 * (so_after - so_before)
    assert np.allclose(target_after - target_before, expected_dp, atol=1e-6), \
        "target_pos should shift by xyz_scale × SO101 Δp"


def test_position_scale_doubles_target_delta():
    """At 2× scale, _target_pos shifts twice as far per SO-101 motion."""
    so_a = [0, 0, 0, 0, 0, 0]
    so_b = [0, 0, 0, 5.0, 0, 0]

    m1 = _mk_mapper(xyz_scale=1.0)
    m1.map(_action(so_a), _state())
    base1 = m1._target_pos.copy()
    m1.map(_action(so_b), _state())
    delta1 = float(np.linalg.norm(m1._target_pos - base1))

    m2 = _mk_mapper(xyz_scale=2.0)
    m2.map(_action(so_a), _state())
    base2 = m2._target_pos.copy()
    m2.map(_action(so_b), _state())
    delta2 = float(np.linalg.norm(m2._target_pos - base2))

    assert delta2 == pytest.approx(2.0 * delta1, rel=1e-3), \
        f"scale=2 delta {delta2:.5f} should be 2× scale=1 delta {delta1:.5f}"


# --- Yaw drop ---------------------------------------------------------


def test_shoulder_pan_propagates_to_target_R():
    """SO-101 shoulder_pan is a pure world-Z rotation. The mapper
    forwards the full ΔR_world to ``target_R``, so a 30° shoulder_pan
    perturbation must rotate target_R by 30° about world Z (give or
    take the URDF axis sign — we only check magnitude)."""
    m = _mk_mapper()
    m.map(_action([0, -45, 30, 20, 0, 0]), _state())
    m.map(_action([0, -45, 30, 20, 0, 0]), _state())  # zero delta tick
    R_before = m._target_R.copy()

    m.map(_action([30, -45, 30, 20, 0, 0]), _state())
    R_after = m._target_R.copy()

    dR = R_after @ R_before.T
    # angular magnitude
    cos_theta = (np.trace(dR) - 1.0) * 0.5
    cos_theta = float(np.clip(cos_theta, -1.0, 1.0))
    angle = float(np.arccos(cos_theta))
    assert angle == pytest.approx(np.deg2rad(30.0), abs=np.deg2rad(1.0)), \
        f"target_R should rotate by ~30°; got {np.rad2deg(angle):.2f}°"


# --- Discontinuity filter ---------------------------------------------


def test_max_ee_step_skips_delta_on_leader_jump():
    """A SO-101 jump exceeding max_ee_step_m must NOT update
    target_pos, so the held command equals the previous one."""
    m = _mk_mapper(max_ee_step_m=0.01)  # 1cm threshold
    cmd1 = m.map(_action([0, 0, 0, 0, 0, 0]), _state())
    target_before = m._target_pos.copy()
    cmd2 = m.map(_action([60, -30, 30, 30, 0, 0]), _state())
    # Target unchanged, cmd holds at the prior arm pose
    assert np.allclose(m._target_pos, target_before, atol=1e-6)
    assert np.allclose(cmd2.q, cmd1.q, atol=1e-5)


# --- Workspace guards -------------------------------------------------


def test_workspace_radius_refuses_target_drift_outside():
    """Many ticks of consistent motion can drift the target outside
    the workspace radius. Once outside, deltas must be refused."""
    # Use enormous scale so a single SO-101 step pushes target out.
    m = _mk_mapper(
        xyz_scale=100.0,
        workspace_radius_m=0.5,
    )
    seed = np.zeros(6, dtype=np.float32)
    m.map(_action([0, 0, 0, 0, 0, 0]), _state(seed))  # anchor
    # Big SO-101 motion → big delta × big scale → way outside radius
    cmd = m.map(_action([0, -30, 30, 0, 0, 50.0]), _state(seed))
    # Held: q stays at the previously committed command
    assert np.allclose(cmd.q, seed, atol=1e-5)
    # Gripper still tracks
    assert cmd.gripper == pytest.approx(0.5, abs=1e-6)


def test_workspace_z_guard_refuses_below_floor():
    """Targets that would drop below workspace_z_min_m are refused."""
    m = _mk_mapper(
        xyz_scale=100.0,
        workspace_z_min_m=0.0,   # floor at z=0
        workspace_z_max_m=1.0,
    )
    seed = np.zeros(6, dtype=np.float32)
    m.map(_action([0, 0, 0, 0, 0, 0]), _state(seed))
    # SO-101 wrist tucks down → delta has -z component → big scale → below floor
    cmd = m.map(_action([0, -90, 90, 60, 0, 0]), _state(seed))
    assert np.allclose(cmd.q, seed, atol=1e-5)


# --- Joint-step clamp -------------------------------------------------


def test_joint_step_clamp_caps_per_tick_delta():
    """A SO-101 motion big enough to demand a large IK swing must
    have its per-joint command delta capped at max_joint_step_deg."""
    cap_deg = 5.0
    m = _mk_mapper(
        xyz_scale=2.0,
        max_joint_step_deg=cap_deg,
    )
    seed = np.zeros(6, dtype=np.float32)
    m.map(_action([0, 0, 0, 0, 0, 0]), _state(seed))  # anchor
    cmd = m.map(_action([60, -45, 60, 30, 0, 0]), _state(seed))
    # Each joint moves at most cap_deg from seed=0
    delta_deg = np.rad2deg(np.abs(cmd.q.astype(np.float64)))
    assert np.all(delta_deg <= cap_deg + 1e-3), \
        f"clamp violated: deltas {delta_deg} exceed cap {cap_deg}"


# --- Gripper map ------------------------------------------------------


def test_gripper_linear_map():
    m = _mk_mapper(
        gripper_in_min_deg=0.0,
        gripper_in_max_deg=100.0,
        gripper_out_min_rad=0.2,
        gripper_out_max_rad=1.2,
    )
    cmd_lo = m.map(_action([0, 0, 0, 0, 0, 0.0]), _state())
    cmd_hi = m.map(_action([0, 0, 0, 0, 0, 100.0]), _state())
    cmd_mid = m.map(_action([0, 0, 0, 0, 0, 50.0]), _state())

    assert cmd_lo.gripper == pytest.approx(0.2, abs=1e-6)
    assert cmd_hi.gripper == pytest.approx(1.2, abs=1e-6)
    assert cmd_mid.gripper == pytest.approx(0.7, abs=1e-6)


def test_gripper_invert_swaps_endpoints():
    m = _mk_mapper(gripper_invert=True)
    cmd_lo = m.map(_action([0, 0, 0, 0, 0, 0.0]), _state())
    cmd_hi = m.map(_action([0, 0, 0, 0, 0, 100.0]), _state())
    assert cmd_lo.gripper == pytest.approx(1.0, abs=1e-6)
    assert cmd_hi.gripper == pytest.approx(0.0, abs=1e-6)


def test_gripper_clamped_outside_input_range():
    m = _mk_mapper()
    cmd_below = m.map(_action([0, 0, 0, 0, 0, -50.0]), _state())
    cmd_above = m.map(_action([0, 0, 0, 0, 0, 200.0]), _state())
    assert cmd_below.gripper == pytest.approx(0.0, abs=1e-6)
    assert cmd_above.gripper == pytest.approx(1.0, abs=1e-6)


# --- Fallback ---------------------------------------------------------


def test_none_action_falls_back_safely():
    m = _mk_mapper()
    cmd = m.map(TeleopAction(target_joint_pos=None), _state())
    assert cmd.q.shape == (6,)
    assert np.isfinite(cmd.q).all()
