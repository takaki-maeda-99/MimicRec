import numpy as np
import pytest
import asyncio
from scipy.spatial.transform import Rotation

from mimicrec.adapters.robot import RobotMode
from mimicrec.motion.input import LegacyTeleopMotionSource, TeleopActionConverter
from mimicrec.motion.legacy import LegacyRobotResourceAdapter, SE3DeltaToLegacyMapper
from mimicrec.motion.se3 import SE3Delta, SE3Frame
from mimicrec.motion.types import (
    JointPositionCommand,
    JointResourceState,
    MotionStep,
    ScalarPositionCommand,
    ScalarResourceState,
)
from mimicrec.types import RobotCommand, RobotState, TeleopAction


def _joint_state(n=2, ee_transform=None):
    return JointResourceState(
        position=np.zeros(n),
        velocity=np.zeros(n),
        effort=np.zeros(n),
        joint_names=tuple(f"j{i}" for i in range(n)),
        ee_transform=ee_transform,
    )


def test_absolute_pose_offsets_become_local_se3_increments():
    converter = TeleopActionConverter(default_rate_hz=50)

    first = converter.convert(
        TeleopAction(
            ee_pose_offset=np.array([0, 0, 0, 0, 0, np.pi / 2]),
            ee_pose_active=True,
            t_mono_ns=1_000_000_000,
        )
    )
    second = converter.convert(
        TeleopAction(
            ee_pose_offset=np.array([0, 0, 0, 0, 0, np.pi]),
            ee_pose_active=True,
            t_mono_ns=1_020_000_000,
        )
    )

    assert first is not None
    assert first.delta.tangent == pytest.approx(np.zeros(6))
    assert second is not None
    assert second.delta.tangent[3:] == pytest.approx([0, 0, np.pi / 2])
    assert second.delta.duration_sec == pytest.approx(0.02)


def test_pose_release_resets_increment_anchor():
    converter = TeleopActionConverter()
    converter.convert(TeleopAction(ee_pose_offset=np.ones(6), ee_pose_active=True))

    assert converter.convert(TeleopAction(ee_pose_active=False)) is None
    reacquired = converter.convert(
        TeleopAction(ee_pose_offset=np.ones(6), ee_pose_active=True)
    )

    assert reacquired is not None
    assert reacquired.delta.tangent == pytest.approx(np.zeros(6))


def test_pose_translation_is_converted_to_previous_eef_local_frame():
    converter = TeleopActionConverter()
    converter.convert(TeleopAction(
        ee_pose_offset=np.array([0, 0, 0, 0, 0, np.pi / 2]),
        ee_pose_active=True,
        t_mono_ns=1,
    ))

    step = converter.convert(TeleopAction(
        ee_pose_offset=np.array([0.1, 0, 0, 0, 0, np.pi / 2]),
        ee_pose_active=True,
        t_mono_ns=2,
    ))

    assert step is not None
    assert step.delta.tangent[:3] == pytest.approx([0, -0.1, 0], abs=1e-8)


def test_literal_world_cartesian_step_becomes_canonical_se3_delta():
    converter = TeleopActionConverter(frame=SE3Frame.WORLD)
    components = np.array([0.1, 0.0, 0.0, 0.0, 0.0, np.pi / 2])

    step = converter.convert(
        TeleopAction(
            ee_cartesian_delta=components,
            ee_pose_active=True,
            gripper_fraction=0.4,
        )
    )

    assert step is not None
    assert step.delta.frame == SE3Frame.WORLD
    assert step.delta.as_transform()[:3, 3] == pytest.approx([0.1, 0, 0])
    # For a combined translation and rotation, the strict Lie-log rho is not
    # the transform's literal translation column.
    assert step.delta.tangent[:3] != pytest.approx([0.1, 0, 0])
    assert step.auxiliary["gripper"] == pytest.approx(0.4)


def test_world_absolute_offsets_are_differentiated_but_retained_for_control():
    converter = TeleopActionConverter(frame=SE3Frame.WORLD)
    first = converter.convert(
        TeleopAction(
            ee_world_pose_offset=np.zeros(6),
            ee_control_rotation_offset=np.zeros(3),
            ee_pose_active=True,
            t_mono_ns=1_000_000_000,
        )
    )
    second = converter.convert(
        TeleopAction(
            ee_world_pose_offset=np.array(
                [0.1, 0, 0, 0, 0, np.pi / 2]
            ),
            ee_pose_active=True,
            ee_control_rotation_offset=np.array([0.2, 0, 0]),
            t_mono_ns=1_020_000_000,
        )
    )

    assert first is not None and first.reset_reference is True
    assert first.delta.tangent == pytest.approx(np.zeros(6))
    assert second is not None and second.reset_reference is False
    assert second.delta.frame == SE3Frame.WORLD
    assert second.delta.as_transform()[:3, 3] == pytest.approx([0.1, 0, 0])
    assert second.absolute_offset[:3, 3] == pytest.approx([0.1, 0, 0])
    assert second.absolute_offset[:3, :3] == pytest.approx(
        second.delta.as_transform()[:3, :3]
    )
    assert second.control_rotation_offset == pytest.approx(
        Rotation.from_rotvec([0.2, 0, 0]).as_matrix()
    )


class _RepeatingPoseTeleop:
    name = "repeating"
    control_rate_hz = 60

    def __init__(self):
        self.pose_message_sequence = 1
        self.calls = 0

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def read_action(self):
        self.calls += 1
        if self.calls == 3:
            self.pose_message_sequence = 2
        offset = 0.0 if self.calls < 3 else 0.02
        await asyncio.sleep(0)
        return TeleopAction(
            ee_pose_offset=np.array([offset, 0, 0, 0, 0, 0]),
            ee_pose_active=True,
            t_mono_ns=self.calls * 10_000_000,
        )


@pytest.mark.asyncio
async def test_motion_source_does_not_overwrite_real_pose_update_with_duplicates():
    teleop = _RepeatingPoseTeleop()
    source = LegacyTeleopMotionSource(teleop)
    await source.connect()

    first = await source.read_step()
    second = await source.read_step()

    assert first.delta.tangent == pytest.approx(np.zeros(6))
    assert second.delta.tangent[0] == pytest.approx(0.02)
    assert teleop.calls == 3


class _Robot:
    name = "legacy"
    dof = 2
    joint_names = ["j0", "j1"]

    def __init__(self):
        self.mode = None
        self.arm_commands = []
        self.gripper_commands = []
        self.estopped = False

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def set_mode(self, mode):
        self.mode = mode

    def supports_mode(self, mode):
        return True

    async def read_state(self):
        return RobotState(
            joint_pos=np.array([0.1, 0.2]),
            joint_vel=np.zeros(2),
            joint_effort=np.zeros(2),
            gripper_pos=0.3,
        )

    async def send_joint_command(self, q):
        self.arm_commands.append(q.copy())

    async def send_gripper_command(self, value):
        self.gripper_commands.append(value)

    async def estop(self):
        self.estopped = True
        return {"ok": True}

    async def clear_estop(self):
        self.estopped = False
        return {"ok": True}


@pytest.mark.asyncio
async def test_legacy_robot_exposes_and_dispatches_named_resources():
    robot = _Robot()
    adapter = LegacyRobotResourceAdapter(robot)
    await adapter.connect()

    state = await adapter.read_resources()
    await adapter.send_commands({
        "arm": JointPositionCommand(np.array([0.4, 0.5])),
        "gripper": ScalarPositionCommand(0.6),
    })
    await adapter.safe_stop()

    assert set(state) == {"arm", "gripper"}
    assert state["gripper"].position == pytest.approx(0.3)
    assert robot.arm_commands[-1] == pytest.approx([0.4, 0.5])
    assert robot.gripper_commands[-1] == pytest.approx(0.6)
    assert robot.mode == RobotMode.GRAVITY_COMP


@pytest.mark.asyncio
async def test_legacy_resource_wrapper_preserves_hardware_estop_surface():
    robot = _Robot()
    adapter = LegacyRobotResourceAdapter(robot)

    assert await adapter.estop() == {"ok": True}
    assert robot.estopped is True
    assert await adapter.clear_estop() == {"ok": True}
    assert robot.estopped is False


class _CartesianMapper:
    def map(self, action, state):
        assert action.ee_delta == pytest.approx([0.01, 0, 0, 0, 0, 0])
        assert state.gripper_pos == pytest.approx(0.2)
        return RobotCommand(q=np.array([0.3, 0.4]), gripper=0.8)


class _AbsoluteCartesianMapper:
    def __init__(self):
        self.reset_count = 0
        self.action = None

    def reset(self):
        self.reset_count += 1

    def map(self, action, _state):
        self.action = action
        return RobotCommand(q=np.array([0.1, 0.2]))


def test_legacy_mapper_bridge_emits_separate_arm_and_gripper_commands():
    mapper = SE3DeltaToLegacyMapper(
        _CartesianMapper(),
        arm_resource="right.arm",
        gripper_resource="right.gripper",
    )

    commands = mapper.map(
        MotionStep(
            SE3Delta(np.array([0.01, 0, 0, 0, 0, 0])),
            auxiliary={"gripper": 0.5},
        ),
        {
            "right.arm": _joint_state(),
            "right.gripper": ScalarResourceState(position=0.2),
        },
    )

    assert commands["right.arm"].position == pytest.approx([0.3, 0.4])
    assert commands["right.gripper"].position == pytest.approx(0.8)


def test_legacy_bridge_uses_absolute_pose_target_without_changing_delta():
    legacy = _AbsoluteCartesianMapper()
    mapper = SE3DeltaToLegacyMapper(
        legacy,
        arm_resource="right.arm",
        target_frame="base",
    )
    absolute = np.eye(4)
    absolute[:3, 3] = [0.2, -0.1, 0.05]
    step = MotionStep(
        SE3Delta.identity(frame="world"),
        absolute_offset=absolute,
        reset_reference=True,
    )

    mapper.map(step, {"right.arm": _joint_state(ee_transform=np.eye(4))})

    assert legacy.reset_count == 1
    assert legacy.action.ee_delta is None
    assert legacy.action.ee_pose_active is True
    assert legacy.action.ee_pose_offset == pytest.approx(
        [0.2, -0.1, 0.05, 0, 0, 0]
    )


def test_legacy_bridge_converts_clutch_local_rotation_to_base_offset():
    legacy = _AbsoluteCartesianMapper()
    mapper = SE3DeltaToLegacyMapper(
        legacy,
        arm_resource="right.arm",
        target_frame="base",
    )
    anchor = np.eye(4)
    anchor[:3, :3] = Rotation.from_euler("z", 90, degrees=True).as_matrix()
    control_rotation = Rotation.from_rotvec([0.2, 0, 0]).as_matrix()

    mapper.map(
        MotionStep(
            SE3Delta.identity(frame="world"),
            absolute_offset=np.eye(4),
            control_rotation_offset=control_rotation,
            reset_reference=True,
        ),
        {"right.arm": _joint_state(ee_transform=anchor)},
    )

    # The downstream legacy mapper consumes a spatial/base rotation offset:
    # R_desired = Exp(offset) @ R_anchor = R_anchor @ R_control_local.
    output_rotation = Rotation.from_rotvec(
        legacy.action.ee_pose_offset[3:]
    ).as_matrix()
    assert output_rotation @ anchor[:3, :3] == pytest.approx(
        anchor[:3, :3] @ control_rotation
    )
