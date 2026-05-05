import numpy as np
from mimicrec.recording.parquet_row import sample_bundle_to_row
from mimicrec.types import RobotState, RobotCommand, SampleBundle, Stamped


class _StubFK:
    def __init__(self):
        self.n_kin_joints = 5
        self.calls = 0

    def pose(self, q):
        self.calls += 1
        return (
            np.array([99.0, 99.0, 99.0], dtype=np.float32),
            np.array([99.0, 99.0, 99.0], dtype=np.float32),
        )


def _bundle_with_state(state: RobotState) -> SampleBundle:
    cmd = RobotCommand(q=np.zeros(6, dtype=np.float32))
    cmd.t_mono_ns = 1
    return SampleBundle(
        tick_t_mono_ns=100,
        state=Stamped(value=state, t_mono_ns=1),
        action=cmd,
        frames={},
    )


def test_uses_state_ee_when_present_and_skips_fk():
    state = RobotState(
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
        ee_pos=np.array([0.1, 0.2, 0.3], dtype=np.float32),
        ee_rotvec=np.array([0.0, 0.0, 0.4], dtype=np.float32),
        gripper_pos=33.3,
    )
    fk = _StubFK()
    row = sample_bundle_to_row(_bundle_with_state(state), 0, fk=fk)
    np.testing.assert_allclose(row["observation.state.ee_pos"], [0.1, 0.2, 0.3])
    np.testing.assert_allclose(row["observation.state.ee_rotvec"], [0.0, 0.0, 0.4])
    assert row["observation.state.gripper_pos"] == 33.3
    # FK NOT called for observation. Action-side EE still uses FK because
    # RobotCommand has no EE channel, so we expect exactly 1 call (action only).
    assert fk.calls == 1


def test_falls_back_to_fk_when_state_ee_is_none():
    state = RobotState(
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
    )
    fk = _StubFK()
    row = sample_bundle_to_row(_bundle_with_state(state), 0, fk=fk)
    # FK was used (StubFK returns 99,99,99)
    np.testing.assert_allclose(row["observation.state.ee_pos"], [99.0, 99.0, 99.0])
    assert fk.calls == 2  # once for state, once for action


def test_no_ee_columns_when_state_none_and_no_fk():
    state = RobotState(
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
    )
    row = sample_bundle_to_row(_bundle_with_state(state), 0, fk=None)
    assert "observation.state.ee_pos" not in row


def test_action_gripper_pos_derived_from_q_when_command_has_no_gripper():
    """Symmetric to obs: when RobotCommand.gripper is None but q has more dims
    than the kinematic chain, derive gripper from q[n_kin_joints]."""
    state = RobotState(
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
        gripper_pos=12.0,
    )
    cmd = RobotCommand(
        q=np.array([0.1, 0.2, 0.3, 0.4, 0.5, 42.5], dtype=np.float32),
        gripper=None,
    )
    cmd.t_mono_ns = 1
    bundle = SampleBundle(
        tick_t_mono_ns=100,
        state=Stamped(value=state, t_mono_ns=1),
        action=cmd,
        frames={},
    )
    fk = _StubFK()  # n_kin_joints = 5
    row = sample_bundle_to_row(bundle, 0, fk=fk)
    assert "action.gripper_pos" in row
    assert row["action.gripper_pos"] == 42.5


def test_action_gripper_pos_written_when_no_fk_and_command_has_gripper():
    """reBotArm hand-teach case: fk is None (daemon supplies obs EE directly),
    and the synthesized RobotCommand carries the gripper in its dedicated
    field. The action-side gripper column must still be written; otherwise
    the replay reader sees no gripper_targets and the dispatcher never
    drives the gripper during playback."""
    state = RobotState(
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
        ee_pos=np.array([0.1, 0.2, 0.3], dtype=np.float32),
        ee_rotvec=np.array([0.0, 0.0, 0.4], dtype=np.float32),
        gripper_pos=12.0,
    )
    cmd = RobotCommand(q=np.zeros(6, dtype=np.float32), gripper=42.5)
    cmd.t_mono_ns = 1
    bundle = SampleBundle(
        tick_t_mono_ns=100,
        state=Stamped(value=state, t_mono_ns=1),
        action=cmd,
        frames={},
    )
    row = sample_bundle_to_row(bundle, 0, fk=None)
    assert "action.gripper_pos" in row
    assert row["action.gripper_pos"] == 42.5
    # observation.state.gripper_pos already worked for this case; assert it
    # too so a future regression on the obs side is also caught.
    assert row["observation.state.gripper_pos"] == 12.0
