import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from mimicrec.mappers.se3_delta_to_so101 import SE3DeltaToSO101Mapper
from mimicrec.motion.se3 import SE3Delta, SE3Frame
from mimicrec.motion.types import JointResourceState, MotionStep


class _Kinematics:
    def __init__(self, fail=False):
        self.fail = fail

    def forward(self, q):
        if self.fail:
            raise RuntimeError("singular")
        transform = np.eye(4)
        transform[0, 3] = q[0] / 100.0
        transform[1, 3] = q[1] / 100.0
        transform[2, 3] = q[2] / 100.0
        return transform



class _FiveDofKinematics(_Kinematics):
    """Three translational plus two rotational differential DoFs."""

    def forward(self, q):
        transform = super().forward(q)
        transform[:3, :3] = Rotation.from_rotvec(
            np.deg2rad([q[3], q[4], 0.0])
        ).as_matrix()
        # Keep the EEF away from the world origin. A faulty left-multiplied
        # WORLD rotation would turn this into translation.
        transform[0, 3] += 0.4
        return transform


class _WeakRotationKinematics(_Kinematics):
    """Second nullspace direction is numerical noise, not a usable axis."""

    def forward(self, q):
        transform = super().forward(q)
        transform[:3, :3] = Rotation.from_rotvec(
            np.deg2rad([q[3], 0.001 * q[4], 0.0])
        ).as_matrix()
        return transform


class _MisalignedRotationKinematics(_Kinematics):
    def forward(self, q):
        transform = super().forward(q)
        transform[:3, :3] = Rotation.from_rotvec(
            np.deg2rad([q[3], q[4], q[4]])
        ).as_matrix()
        return transform


class _LimitRedundantPositionKinematics(_Kinematics):
    def forward(self, q):
        transform = np.eye(4)
        transform[0, 3] = q[0] / 100.0
        transform[1, 3] = q[4] / 100.0
        transform[2, 3] = (q[1] + q[2] - q[3]) / 100.0
        return transform


class _WristRedundantPositionKinematics(_Kinematics):
    def forward(self, q):
        transform = np.eye(4)
        transform[0, 3] = (q[0] + q[4]) / 100.0
        transform[1, 3] = q[1] / 100.0
        transform[2, 3] = q[2] / 100.0
        return transform


class _QuadraticPositionKinematics(_Kinematics):
    """Expose a nonlinear FK acceptance boundary between 1/2 and 1."""

    def forward(self, q):
        transform = np.eye(4)
        transform[0, 3] = q[0] / 1000.0 + q[0] ** 2 / 10000.0
        return transform


def _state(q=None):
    values_deg = np.zeros(5) if q is None else np.asarray(q, dtype=float)
    values = np.deg2rad(values_deg)
    return JointResourceState(
        position=values,
        velocity=np.zeros(5),
        effort=np.zeros(5),
        joint_names=(
            "shoulder_pan",
            "shoulder_lift",
            "elbow_flex",
            "wrist_flex",
            "wrist_roll",
        ),
    )


def _mapper(**overrides):
    kwargs = {
        "urdf_path": "unused.urdf",
        "kinematics": _Kinematics(),
        "max_joint_step_deg": 6.0,
        "max_orientation_error_rad": 3.2,
    }
    kwargs.update(overrides)
    return SE3DeltaToSO101Mapper(**kwargs)


def test_maps_local_se3_increment_to_five_joint_command():
    mapper = _mapper()

    commands = mapper.map(
        MotionStep(SE3Delta(np.array([0.02, 0.01, 0, 0, 0, 0]))),
        {"left_robot.arm": _state()},
    )

    assert commands["left_robot.arm"].position == pytest.approx(
        np.deg2rad([2, 1, 0, 0, 0]), abs=1e-6
    )


def test_joint_step_is_limited_without_creating_a_global_pose_target():
    mapper = _mapper(max_joint_step_deg=3.0)

    first = mapper.map(
        MotionStep(SE3Delta(np.array([0.10, 0, 0, 0, 0, 0]))),
        {"left_robot.arm": _state()},
    )

    assert first["left_robot.arm"].position[0] == pytest.approx(
        np.deg2rad(3.0), abs=2e-5
    )
    assert mapper._last_command_deg[0] == pytest.approx(3.0, abs=0.001)


def test_trigger_fraction_maps_to_raw_so101_gripper_range():
    mapper = _mapper()

    open_commands = mapper.map(
        MotionStep(SE3Delta.identity(), auxiliary={"gripper": 0.0}),
        {"left_robot.arm": _state()},
    )
    closed_commands = mapper.map(
        MotionStep(SE3Delta.identity(), auxiliary={"gripper": 1.0}),
        {"left_robot.arm": _state()},
    )

    assert open_commands["left_robot.gripper"].position == pytest.approx(100)
    assert closed_commands["left_robot.gripper"].position == pytest.approx(0)


def test_failed_ik_holds_command_and_reports_projection_rejection():
    mapper = _mapper(kinematics=_Kinematics(fail=True))

    commands = mapper.map(
        MotionStep(SE3Delta(np.array([0.02, 0, 0, 0, 0, 0]))),
        {"left_robot.arm": _state([1, 2, 3, 4, 5])},
    )

    assert commands["left_robot.arm"].position == pytest.approx(
        np.deg2rad([1, 2, 3, 4, 5])
    )
    assert mapper.telemetry()["ik_rejected"] == 1.0
    assert mapper.telemetry()["ik_projection_scale"] == 0.0


def test_unreachable_rotation_is_dropped_without_translation_or_joint_motion():
    mapper = _mapper(
        kinematics=_FiveDofKinematics(),
    )

    commands = mapper.map(
        MotionStep(
            SE3Delta(
                np.array([0, 0, 0, 0, 0, 0.1]), frame=SE3Frame.WORLD
            )
        ),
        {"left_robot.arm": _state()},
    )

    telemetry = mapper.telemetry()
    assert commands["left_robot.arm"].position == pytest.approx(np.zeros(5))
    assert telemetry["ik_reachable_rotation_rank"] == pytest.approx(2.0)
    assert telemetry["ik_rotation_projection_residual_rad"] == pytest.approx(
        0.1, abs=1e-5
    )
    assert telemetry["ik_position_error_m"] == pytest.approx(0.0, abs=1e-9)


def test_reachable_rotation_uses_nullspace_and_preserves_position():
    mapper = _mapper(kinematics=_FiveDofKinematics())

    commands = mapper.map(
        MotionStep(SE3Delta(np.array([0, 0, 0, 0.04, -0.03, 0]))),
        {"left_robot.arm": _state()},
    )

    output = commands["left_robot.arm"].position
    assert output[:3] == pytest.approx(np.zeros(3), abs=1e-8)
    assert output[3:] == pytest.approx([0.04, -0.03], abs=1e-5)


def test_world_delta_is_rotated_at_embodiment_boundary():
    world_to_base = Rotation.from_euler("z", 90, degrees=True).as_matrix()
    mapper = _mapper(
        world_to_base_rotation=world_to_base.reshape(-1).tolist()
    )

    commands = mapper.map(
        MotionStep(
            SE3Delta(np.array([0.01, 0, 0, 0, 0, 0]), frame="world")
        ),
        {"left_robot.arm": _state()},
    )

    assert commands["left_robot.arm"].position == pytest.approx(
        np.deg2rad([0, 1, 0, 0, 0]), abs=1e-6
    )


def test_absolute_position_target_converges_after_joint_step_limiting():
    mapper = _mapper(max_joint_step_deg=3.0)
    absolute = np.eye(4)
    absolute[0, 3] = 0.10
    first_step = MotionStep(
        SE3Delta.identity(frame="world"),
        absolute_offset=absolute,
        reset_reference=True,
    )
    repeated_step = MotionStep(
        SE3Delta.identity(frame="world"),
        absolute_offset=absolute,
    )

    positions = []
    state = _state()
    for index in range(4):
        command = mapper.map(
            first_step if index == 0 else repeated_step,
            {"left_robot.arm": state},
        )["left_robot.arm"]
        positions.append(np.rad2deg(command.position[0]))
        state = _state(np.rad2deg(command.position))

    assert positions == pytest.approx([3.0, 6.0, 9.0, 10.0], abs=0.01)
    assert mapper.telemetry()["ik_position_target_error_m"] == pytest.approx(
        0.01, abs=1e-4
    )


def test_absolute_target_does_not_echo_encoder_quantization():
    mapper = _mapper(max_joint_step_deg=3.0)
    absolute = np.eye(4)
    first = MotionStep(
        SE3Delta.identity(frame="world"),
        absolute_offset=absolute,
        reset_reference=True,
    )
    repeated = MotionStep(
        SE3Delta.identity(frame="world"),
        absolute_offset=absolute,
    )

    initial = mapper.map(first, {"left_robot.arm": _state()})[
        "left_robot.arm"
    ].position
    positive_noise = mapper.map(
        repeated, {"left_robot.arm": _state([0.1, 0, 0, 0, 0.1])}
    )["left_robot.arm"].position
    negative_noise = mapper.map(
        repeated, {"left_robot.arm": _state([-0.1, 0, 0, 0, -0.1])}
    )["left_robot.arm"].position

    assert positive_noise == pytest.approx(initial, abs=1e-8)
    assert negative_noise == pytest.approx(initial, abs=1e-8)


def test_absolute_target_is_bounded_ahead_of_stalled_measured_state():
    mapper = _mapper(max_joint_step_deg=3.0, max_command_lead_deg=4.0)
    absolute = np.eye(4)
    absolute[0, 3] = 0.10
    first = MotionStep(
        SE3Delta.identity(frame="world"),
        absolute_offset=absolute,
        reset_reference=True,
    )
    repeated = MotionStep(
        SE3Delta.identity(frame="world"),
        absolute_offset=absolute,
    )

    commands = []
    for index in range(8):
        command = mapper.map(
            first if index == 0 else repeated,
            {"left_robot.arm": _state()},
        )["left_robot.arm"]
        commands.append(float(np.rad2deg(command.position[0])))

    assert max(commands) == pytest.approx(4.0, abs=0.01)


def test_absolute_target_smoothing_uses_mapper_clock_and_converges():
    now = [0.0]
    mapper = _mapper(
        pose_smoothing_time_constant_sec=0.015,
        monotonic=lambda: now[0],
    )
    absolute = np.eye(4)
    absolute[0, 3] = 0.03
    first = MotionStep(
        SE3Delta.identity(frame="world"),
        absolute_offset=np.eye(4),
        reset_reference=True,
    )
    target = MotionStep(
        SE3Delta.identity(frame="world"),
        absolute_offset=absolute,
    )

    mapper.map(first, {"left_robot.arm": _state()})
    now[0] += 1.0 / 60.0
    first_filtered = mapper.map(target, {"left_robot.arm": _state()})[
        "left_robot.arm"
    ].position[0]
    for _ in range(20):
        now[0] += 1.0 / 60.0
        final = mapper.map(target, {"left_robot.arm": _state()})[
            "left_robot.arm"
        ].position[0]

    assert 0.0 < np.rad2deg(first_filtered) < 3.0
    assert np.rad2deg(final) == pytest.approx(3.0, abs=0.01)


def test_repeated_unreachable_absolute_rotation_does_not_drift():
    mapper = _mapper(kinematics=_FiveDofKinematics())
    absolute = np.eye(4)
    absolute[:3, :3] = Rotation.from_rotvec([0, 0, 0.2]).as_matrix()
    first_step = MotionStep(
        SE3Delta.identity(frame="world"),
        absolute_offset=absolute,
        reset_reference=True,
    )
    repeated_step = MotionStep(
        SE3Delta.identity(frame="world"),
        absolute_offset=absolute,
    )

    for index in range(20):
        command = mapper.map(
            first_step if index == 0 else repeated_step,
            {"left_robot.arm": _state()},
        )["left_robot.arm"]

    assert command.position == pytest.approx(np.zeros(5), abs=1e-8)
    assert mapper.telemetry()[
        "ik_rotation_projection_residual_rad"
    ] == pytest.approx(0.2, abs=1e-5)


def test_clutch_local_control_rotation_drives_reachable_wrist_axis():
    mapper = _mapper(kinematics=_FiveDofKinematics())
    absolute = np.eye(4)
    control_rotation = Rotation.from_rotvec([0.1, 0, 0]).as_matrix()

    command = mapper.map(
        MotionStep(
            SE3Delta.identity(frame="world"),
            absolute_offset=absolute,
            control_rotation_offset=control_rotation,
            reset_reference=True,
        ),
        {"left_robot.arm": _state()},
    )["left_robot.arm"]

    assert command.position[3] == pytest.approx(0.1, abs=1e-5)
    assert command.position[:3] == pytest.approx(np.zeros(3), abs=1e-8)


def test_bounded_position_ik_uses_redundancy_at_wrist_limit():
    mapper = _mapper(kinematics=_LimitRedundantPositionKinematics())
    absolute = np.eye(4)
    absolute[2, 3] = 0.03
    initial = np.array([0, 0, 0, -95, 0], dtype=float)

    command = mapper.map(
        MotionStep(
            SE3Delta.identity(frame="world"),
            absolute_offset=absolute,
            reset_reference=True,
        ),
        {"left_robot.arm": _state(initial)},
    )["left_robot.arm"]
    command_deg = np.rad2deg(command.position)

    assert command_deg[3] >= -95.0 - 1e-6
    assert command_deg[1] > 0.0
    assert command_deg[2] > 0.0
    start_z = mapper._kinematics.forward(initial)[2, 3]
    next_z = mapper.forward_kinematics(command.position)[2, 3]
    assert next_z > start_z


def test_position_ik_reserves_wrist_roll_for_rotation():
    mapper = _mapper(
        kinematics=_WristRedundantPositionKinematics(),
        position_joint_weights=[1, 1, 1, 3, 30],
    )

    command = mapper.map(
        MotionStep(SE3Delta(np.array([0.01, 0, 0, 0, 0, 0]))),
        {"left_robot.arm": _state()},
    )["left_robot.arm"]
    command_deg = np.rad2deg(command.position)

    # In this test model q4 can create Y translation, but it represents wrist
    # roll and must not be selected for a pure positional gesture when the
    # proximal position joints can solve the task.
    assert abs(command_deg[4]) < 0.1


def test_position_acceptance_rejects_cross_axis_motion():
    mapper = _mapper(
        max_position_error_m=0.001,
        max_uncommanded_position_error_m=0.00015,
    )

    accepted, total, cross = mapper._position_error_acceptable(
        np.array([0.005, 0.0, 0.0]),
        np.array([0.005, 0.0003, 0.0]),
    )

    assert accepted is False
    assert total == pytest.approx(0.0003)
    assert cross == pytest.approx(0.0003)


def test_nonlinear_backtracking_refines_power_of_two_bracket():
    mapper = _mapper(
        kinematics=_QuadraticPositionKinematics(),
        max_position_error_m=0.005,
        max_uncommanded_position_error_m=0.001,
        backtracking_refinement_steps=8,
    )
    seed = np.zeros(5)
    current = mapper._kinematics.forward(seed)

    candidate, scale = mapper._backtrack(
        seed,
        current,
        np.deg2rad([10.0, 0.0, 0.0, 0.0, 0.0]),
        np.array([0.01, 0.0, 0.0]),
        np.zeros(3),
    )

    assert 0.70 < scale < 0.71
    assert scale != pytest.approx(0.5)
    actual = mapper._kinematics.forward(candidate)[:3, 3]
    assert np.linalg.norm(actual - np.array([0.01 * scale, 0.0, 0.0])) <= 0.005
    assert mapper.telemetry()["ik_backtracking_count"] == pytest.approx(1.0)


def test_rotation_at_joint_limit_cannot_cancel_primary_translation():
    mapper = _mapper(kinematics=_FiveDofKinematics())
    initial = np.array([0, 0, 0, -95, 0], dtype=float)

    command = mapper.map(
        MotionStep(SE3Delta(np.array([0.02, 0, 0, -0.1, 0, 0]))),
        {"left_robot.arm": _state(initial)},
    )["left_robot.arm"]
    command_deg = np.rad2deg(command.position)

    assert command_deg[0] > 1.9
    assert command_deg[3] == pytest.approx(-95.0, abs=1e-6)


def test_weak_rotation_direction_is_discarded_not_amplified():
    mapper = _mapper(
        kinematics=_WeakRotationKinematics(),
        rotation_singular_value_min=0.05,
    )

    command = mapper.map(
        MotionStep(SE3Delta(np.array([0, 0, 0, 0, 0.1, 0]))),
        {"left_robot.arm": _state()},
    )["left_robot.arm"]

    assert command.position == pytest.approx(np.zeros(5), abs=1e-8)
    assert mapper.telemetry()["ik_reachable_rotation_rank"] == pytest.approx(1)
    assert mapper.telemetry()["ik_joint_step_deg"] == pytest.approx(0.0)


def test_rotation_projection_pointing_along_wrong_axis_is_discarded():
    mapper = _mapper(
        kinematics=_MisalignedRotationKinematics(),
        rotation_projection_min_alignment=0.75,
    )

    command = mapper.map(
        MotionStep(SE3Delta(np.array([0, 0, 0, 0, 0, 0.1]))),
        {"left_robot.arm": _state()},
    )["left_robot.arm"]

    assert command.position == pytest.approx(np.zeros(5), abs=1e-8)
    assert mapper.telemetry()[
        "ik_rotation_projection_alignment"
    ] == pytest.approx(2**-0.5, abs=1e-4)


def test_mapper_rejects_missing_or_wrong_resource_state():
    mapper = _mapper()

    with pytest.raises(ValueError, match="missing SO-101 arm state"):
        mapper.map(MotionStep(SE3Delta.identity()), {})
