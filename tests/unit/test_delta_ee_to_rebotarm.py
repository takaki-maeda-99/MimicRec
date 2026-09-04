"""Tests for the reusable Cartesian reBotArm mapper."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mimicrec.types import RobotCommand, RobotState, TeleopAction

pytest.importorskip("placo")

from mimicrec.mappers.delta_ee_to_rebotarm import DeltaEEToReBotArmMapper  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
URDF = str(
    REPO_ROOT
    / "third_party/reBotArm_control_py/urdf/reBot-DevArm_fixend_description/urdf/reBot-DevArm_fixend.urdf"
)


def _state(
    gripper: float | None = -3.0,
    joint_pos: np.ndarray | None = None,
) -> RobotState:
    q = np.zeros(6, dtype=np.float32) if joint_pos is None else joint_pos
    return RobotState(
        joint_pos=np.asarray(q, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
        gripper_pos=gripper,
    )


def _mapper(**overrides) -> DeltaEEToReBotArmMapper:
    kwargs = dict(
        rebotarm_urdf_path=URDF,
        rebotarm_package_dirs=[
            str(REPO_ROOT / "third_party/reBotArm_control_py/urdf")
        ],
        workspace_radius_m=0.0,
        workspace_z_min_m=-10.0,
        workspace_z_max_m=10.0,
        max_joint_step_deg=0.0,
        max_ik_position_error_m=0.0,
        max_ik_orientation_error_rad=0.0,
    )
    kwargs.update(overrides)
    return DeltaEEToReBotArmMapper(**kwargs)


def test_first_tick_anchors_without_motion():
    mapper = _mapper()
    command = mapper.map(TeleopAction(ee_delta=np.ones(6, dtype=np.float32)), _state())
    assert np.allclose(command.q, 0.0)
    assert mapper._target_pos is not None


def test_translation_delta_updates_target_and_returns_finite_joint_command():
    mapper = _mapper()
    state = _state()
    mapper.map(TeleopAction(ee_delta=np.zeros(6, dtype=np.float32)), state)
    before = mapper._target_pos.copy()
    command = mapper.map(
        TeleopAction(ee_delta=np.array([0.001, 0, 0, 0, 0, 0], dtype=np.float32)),
        state,
    )
    assert mapper._target_pos[0] == pytest.approx(before[0] + 0.001, abs=1e-6)
    assert command.q.shape == (6,)
    assert np.isfinite(command.q).all()


def test_workspace_rejection_does_not_commit_unreachable_target():
    mapper = _mapper(workspace_radius_m=0.01)
    state = _state()
    first = mapper.map(TeleopAction(ee_delta=np.zeros(6, dtype=np.float32)), state)
    before = mapper._target_pos.copy()
    held = mapper.map(
        TeleopAction(ee_delta=np.array([0.01, 0, 0, 0, 0, 0], dtype=np.float32)),
        state,
    )
    assert np.allclose(mapper._target_pos, before)
    assert np.allclose(held.q, first.q)


def test_joint_step_limit_is_relative_to_last_sent_command():
    mapper = _mapper(max_joint_step_deg=0.5)
    state = _state()
    mapper.map(TeleopAction(ee_delta=np.zeros(6, dtype=np.float32)), state)
    previous = np.zeros(6)
    for _ in range(3):
        command = mapper.map(
            TeleopAction(ee_delta=np.array([0.003, 0, 0, 0, 0, 0], dtype=np.float32)),
            state,
        )
        current = np.rad2deg(command.q.astype(np.float64))
        assert np.max(np.abs(current - previous)) <= 0.5 + 1e-4
        previous = current


def test_gripper_delta_integrates_and_clamps():
    mapper = _mapper(gripper_min_rad=-5.5, gripper_max_rad=-0.5)
    state = _state(gripper=-1.0)
    command = mapper.map(
        TeleopAction(ee_delta=np.zeros(6, dtype=np.float32), gripper_delta=1.0),
        state,
    )
    assert command.gripper == pytest.approx(-0.5)


def test_trigger_fraction_maps_open_to_closed_with_smoothing():
    mapper = _mapper(
        gripper_min_rad=-5.5,
        gripper_max_rad=-0.5,
        gripper_open_rad=-5.5,
        gripper_closed_rad=-0.5,
        gripper_smoothing_time_constant_sec=0.05,
    )
    now = 10.0
    mapper._monotonic = lambda: now
    state = _state(gripper=-5.5)
    mapper.map(
        TeleopAction(
            ee_pose_offset=np.zeros(6),
            ee_pose_active=True,
            gripper_fraction=1.0,
        ),
        state,
    )

    now += 1.0 / 60.0
    first = mapper.map(
        TeleopAction(
            ee_pose_offset=np.zeros(6),
            ee_pose_active=True,
            gripper_fraction=1.0,
        ),
        state,
    )
    assert -5.5 < first.gripper < -0.5

    for _ in range(60):
        now += 1.0 / 60.0
        final = mapper.map(
            TeleopAction(
                ee_pose_offset=np.zeros(6),
                ee_pose_active=True,
                gripper_fraction=1.0,
            ),
            state,
        )
    assert final.gripper == pytest.approx(-0.5, abs=1e-6)


def test_bad_delta_holds_instead_of_emitting_bad_command():
    mapper = _mapper()
    command = mapper.map(TeleopAction(ee_delta=np.array([np.nan] * 6)), _state())
    assert command.q.shape == (6,)
    assert np.isfinite(command.q).all()


def test_absolute_pose_offset_preserves_rotation_amount():
    mapper = _mapper()
    state = _state()
    mapper.map(
        TeleopAction(ee_pose_offset=np.zeros(6), ee_pose_active=True), state
    )
    anchor_R = mapper._pose_anchor_R.copy()

    controller_angle = 0.4
    mapper.map(
        TeleopAction(
            ee_pose_offset=np.array([0, 0, 0, 0, 0, controller_angle]),
            ee_pose_active=True,
        ),
        state,
    )

    relative = mapper._target_R @ anchor_R.T
    angle = np.arccos(np.clip((np.trace(relative) - 1.0) * 0.5, -1.0, 1.0))
    assert angle == pytest.approx(controller_angle, abs=1e-8)


def test_pose_release_clears_anchor_for_next_clutch():
    mapper = _mapper()
    state = _state()
    mapper.map(
        TeleopAction(ee_pose_offset=np.zeros(6), ee_pose_active=True), state
    )
    assert mapper._pose_anchor_pos is not None

    mapper.map(TeleopAction(ee_pose_active=False), state)

    assert mapper._pose_anchor_pos is None
    assert mapper._pose_anchor_R is None
    assert mapper._target_pos is None


def test_pose_smoothing_advances_between_bursty_absolute_updates():
    mapper = _mapper(pose_smoothing_time_constant_sec=0.04)
    now = 10.0
    mapper._monotonic = lambda: now
    state = _state()
    mapper.map(
        TeleopAction(ee_pose_offset=np.zeros(6), ee_pose_active=True), state
    )
    anchor_R = mapper._pose_anchor_R.copy()
    target = TeleopAction(
        ee_pose_offset=np.array([0.06, 0, 0, 0, 0, 0.6]),
        ee_pose_active=True,
    )

    now += 1.0 / 60.0
    mapper.map(target, state)
    first_translation = mapper._target_pos[0] - mapper._pose_anchor_pos[0]
    first_relative = mapper._target_R @ anchor_R.T
    first_angle = np.arccos(
        np.clip((np.trace(first_relative) - 1.0) * 0.5, -1.0, 1.0)
    )

    assert 0.0 < first_translation < 0.06
    assert 0.0 < first_angle < 0.6

    # No new source pose is needed: the held absolute target is resampled by
    # the 60 Hz control loop, so both components converge without stair-steps.
    for _ in range(30):
        now += 1.0 / 60.0
        mapper.map(target, state)

    final_translation = mapper._target_pos[0] - mapper._pose_anchor_pos[0]
    final_relative = mapper._target_R @ anchor_R.T
    final_angle = np.arccos(
        np.clip((np.trace(final_relative) - 1.0) * 0.5, -1.0, 1.0)
    )
    assert final_translation == pytest.approx(0.06, abs=1e-6)
    assert final_angle == pytest.approx(0.6, abs=1e-5)


def test_pose_release_discards_smoothing_tail():
    mapper = _mapper(pose_smoothing_time_constant_sec=0.04)
    now = 10.0
    mapper._monotonic = lambda: now
    state = _state()
    mapper.map(
        TeleopAction(ee_pose_offset=np.zeros(6), ee_pose_active=True), state
    )
    now += 1.0 / 60.0
    mapper.map(
        TeleopAction(
            ee_pose_offset=np.array([0.1, 0, 0, 0, 0, 0]),
            ee_pose_active=True,
        ),
        state,
    )

    mapper.map(TeleopAction(ee_pose_active=False), state)

    assert mapper._filtered_pose_translation is None
    assert mapper._filtered_pose_R is None
    assert mapper._pose_filter_last_at is None


def test_eef_local_pose_offset_uses_anchor_axes_as_one_rigid_transform():
    mapper = _mapper(delta_frame="ee_local")
    state = _state()
    mapper.map(
        TeleopAction(ee_pose_offset=np.zeros(6), ee_pose_active=True), state
    )
    anchor_pos = mapper._pose_anchor_pos.copy()
    anchor_R = mapper._pose_anchor_R.copy()
    local_translation = np.array([0.01, -0.02, 0.005])

    mapper.map(
        TeleopAction(
            ee_pose_offset=np.concatenate(
                [local_translation, np.array([0.0, 0.0, 0.2])]
            ),
            ee_pose_active=True,
        ),
        state,
    )

    assert mapper._target_pos == pytest.approx(
        anchor_pos + anchor_R @ local_translation
    )
    relative_local = anchor_R.T @ mapper._target_R
    angle = np.arccos(
        np.clip((np.trace(relative_local) - 1.0) * 0.5, -1.0, 1.0)
    )
    assert angle == pytest.approx(0.2, abs=1e-8)


def test_absolute_pose_target_is_split_into_bounded_se3_steps():
    mapper = _mapper(
        delta_frame="ee_local",
        max_pose_linear_step_m=0.005,
        max_pose_angular_step_rad=0.05,
    )
    state = _state()
    mapper.map(
        TeleopAction(ee_pose_offset=np.zeros(6), ee_pose_active=True), state
    )
    anchor_pos = mapper._pose_anchor_pos.copy()
    anchor_R = mapper._pose_anchor_R.copy()
    action = TeleopAction(
        ee_pose_offset=np.array([0.02, 0.0, 0.0, 0.0, 0.0, 0.2]),
        ee_pose_active=True,
    )

    for tick in range(1, 5):
        mapper.map(action, state)
        assert np.linalg.norm(mapper._target_pos - anchor_pos) == pytest.approx(
            tick * 0.005, abs=1e-7
        )
        relative = mapper._target_R @ anchor_R.T
        angle = np.arccos(
            np.clip((np.trace(relative) - 1.0) * 0.5, -1.0, 1.0)
        )
        assert angle == pytest.approx(tick * 0.05, abs=1e-7)

    assert mapper._target_pos == pytest.approx(mapper._desired_pose_pos)
    assert mapper._target_R == pytest.approx(mapper._desired_pose_R)


def test_ik_seed_prefers_last_command_over_unsent_raw_solution():
    mapper = _mapper(seed_from_last_command=True, seed_from_last_ik=True)
    mapper._last_command = RobotCommand(q=np.deg2rad(np.full(6, 2.0)))
    mapper._last_ik_output_deg = np.full(6, 90.0)

    seed = mapper._seed_from_state(_state())

    assert seed == pytest.approx(np.full(6, 2.0))


def test_pose_slew_does_not_run_ahead_of_joint_limited_command():
    mapper = _mapper(
        delta_frame="ee_local",
        max_pose_linear_step_m=0.005,
        max_pose_angular_step_rad=0.05,
        max_joint_step_deg=0.1,
        seed_from_last_command=True,
        seed_from_last_ik=False,
    )
    state = _state()
    mapper.map(
        TeleopAction(ee_pose_offset=np.zeros(6), ee_pose_active=True), state
    )
    action = TeleopAction(
        ee_pose_offset=np.array([0.05, 0.0, 0.0, 0.0, 0.0, 0.5]),
        ee_pose_active=True,
    )
    first_command = mapper.map(action, state)
    sent_pose = mapper._rebotarm_ik.forward_kinematics(
        np.rad2deg(first_command.q.astype(np.float64))
    )

    mapper.map(action, state)

    assert np.linalg.norm(mapper._target_pos - sent_pose[:3, 3]) <= 0.005 + 1e-9
    rotation_step = mapper._target_R @ sent_pose[:3, :3].T
    angle = np.arccos(
        np.clip((np.trace(rotation_step) - 1.0) * 0.5, -1.0, 1.0)
    )
    assert angle <= 0.05 + 1e-9


def test_cartesian_backtracking_sends_complete_ik_solution_without_joint_clip():
    mapper = _mapper(
        max_joint_step_deg=0.1,
        max_ik_backtracking_steps=8,
        seed_from_last_command=True,
        seed_from_last_ik=False,
    )
    state = _state()
    first = mapper.map(TeleopAction(ee_delta=np.zeros(6)), state)
    command = mapper.map(
        TeleopAction(ee_delta=np.array([0.01, 0.0, 0.0, 0.0, 0.0, 0.0])),
        state,
    )

    step_deg = np.rad2deg(command.q.astype(np.float64) - first.q.astype(np.float64))
    assert np.max(np.abs(step_deg)) <= 0.1 + 1e-5
    # The command is the accepted IK configuration itself. It is never an
    # independently clipped mixture of the seed and a distant IK solution.
    assert np.rad2deg(command.q.astype(np.float64)) == pytest.approx(
        mapper._last_ik_output_deg, abs=1e-5
    )
    assert mapper._ik_backtrack_count > 0


def test_posture_regularization_and_velocity_constraints_are_enabled():
    mapper = _mapper(
        ik_posture_weight=0.02,
        ik_velocity_limit_deg_s=90.0,
        ik_control_rate_hz=60.0,
        ik_hard_position_constraint=True,
    )

    assert mapper._ik_posture_task is not None
    assert mapper._rebotarm_ik.solver.dt == pytest.approx(1.0 / 60.0)
    assert mapper._ik_hard_position_constraint is True


def test_hard_position_constraint_keeps_rotation_pivot_fixed():
    mapper = _mapper(
        delta_frame="ee_local",
        max_pose_linear_step_m=0.006,
        max_pose_angular_step_rad=0.04,
        max_joint_step_deg=2.0,
        max_ik_backtracking_steps=6,
        ik_posture_weight=0.02,
        ik_velocity_limit_deg_s=90.0,
        ik_control_rate_hz=60.0,
        ik_hard_position_constraint=True,
        max_ik_position_error_m=0.001,
        max_ik_orientation_error_rad=0.08,
        seed_from_last_command=True,
        seed_from_last_ik=False,
    )
    idle_q = np.array(
        [-0.028801, -0.028801, -0.018883, -0.110056, -0.235943, 0.008202],
        dtype=np.float32,
    )
    state = _state(joint_pos=idle_q)
    command = mapper.map(
        TeleopAction(ee_pose_offset=np.zeros(6), ee_pose_active=True), state
    )
    anchor = mapper._rebotarm_ik.forward_kinematics(
        np.rad2deg(command.q.astype(np.float64))
    )[:3, 3].copy()
    action = TeleopAction(
        ee_pose_offset=np.array([0.0, 0.0, 0.0, 0.0, 0.8, 0.0]),
        ee_pose_active=True,
    )
    maximum_position_drift = 0.0

    for _ in range(40):
        command = mapper.map(action, state)
        achieved = mapper._rebotarm_ik.forward_kinematics(
            np.rad2deg(command.q.astype(np.float64))
        )
        maximum_position_drift = max(
            maximum_position_drift,
            float(np.linalg.norm(achieved[:3, 3] - anchor)),
        )

    assert maximum_position_drift < 0.0002


def test_floor_mesh_guard_rejects_entire_predicted_joint_path():
    mapper = _mapper(
        max_ik_backtracking_steps=2,
        floor_plane_normal=[0.0, 0.0, 1.0],
        floor_plane_offset_m=0.5,
        floor_clearance_m=0.01,
        floor_collision_frames=["link2"],
        floor_path_samples=3,
    )
    state = _state()
    first = mapper.map(TeleopAction(ee_delta=np.zeros(6)), state)
    target_before = mapper._target_pos.copy()

    held = mapper.map(
        TeleopAction(ee_delta=np.array([0.001, 0.0, 0.0, 0.0, 0.0, 0.0])),
        state,
    )

    assert held.q == pytest.approx(first.q)
    assert mapper._target_pos == pytest.approx(target_before)
    assert "floor clearance" in mapper._last_rejection_reason
    assert mapper._floor_clearance_last_m < mapper._floor_clearance


def test_mapper_rejects_solution_outside_asymmetric_physical_limits(monkeypatch):
    mapper = _mapper(
        joint_pos_min_deg=[-160.428, -179.909, -179.909, -107.143, -89.954, -179.909],
        joint_pos_max_deg=[160.428, 0.0, 0.0, 89.954, 89.954, 179.909],
    )
    state = _state()
    mapper.map(TeleopAction(ee_delta=np.zeros(6)), state)
    monkeypatch.setattr(
        mapper._rebotarm_ik,
        "inverse_kinematics",
        lambda *_args, **_kwargs: np.array([0.0, 1.0, 0.0, 0.0, 0.0, 0.0]),
    )

    held = mapper.map(
        TeleopAction(ee_delta=np.array([0.001, 0.0, 0.0, 0.0, 0.0, 0.0])),
        state,
    )

    assert held.q == pytest.approx(np.zeros(6))
    assert mapper._last_rejection_reason == "IK output above joint limits"


def test_cartesian_telemetry_reports_command_and_measured_errors():
    mapper = _mapper(delta_frame="ee_local", max_joint_step_deg=0.1)
    state = _state()
    mapper.map(
        TeleopAction(ee_pose_offset=np.zeros(6), ee_pose_active=True), state
    )
    command = mapper.map(
        TeleopAction(
            ee_pose_offset=np.array([0.02, 0, 0, 0, 0, 0.2]),
            ee_pose_active=True,
        ),
        state,
    )
    state.daemon_target_joint_pos = command.q + np.deg2rad(
        np.full(6, 0.02, dtype=np.float32)
    )

    telemetry = mapper.telemetry(state, command)

    assert telemetry["teleop_measured_position_error_m"] >= 0.0
    assert telemetry["teleop_measured_orientation_error_rad"] >= 0.0
    assert telemetry["teleop_command_position_error_m"] >= 0.0
    assert telemetry["teleop_command_orientation_error_rad"] >= 0.0
    assert telemetry["teleop_joint_step_limited"] in {0.0, 1.0}
    assert telemetry["teleop_desired_position_gap_m"] >= 0.0
    assert telemetry["teleop_desired_orientation_gap_rad"] >= 0.0
    assert telemetry["teleop_pose_slew_active"] in {0.0, 1.0}
    assert telemetry["teleop_joint_1_daemon_ramp_error_deg"] == pytest.approx(
        -0.02, abs=1e-5
    )
    assert "teleop_joint_1_motor_tracking_error_deg" in telemetry
