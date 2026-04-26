import numpy as np
from mimicrec.types import RobotState


def test_robot_state_default_ee_fields_are_none():
    s = RobotState(
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
    )
    assert s.ee_pos is None
    assert s.ee_rotvec is None
    assert s.gripper_pos is None


def test_robot_state_can_carry_ee_fields():
    s = RobotState(
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
        ee_pos=np.array([0.1, 0.2, 0.3], dtype=np.float32),
        ee_rotvec=np.array([0.0, 0.0, 0.5], dtype=np.float32),
        gripper_pos=42.0,
    )
    assert s.ee_pos.shape == (3,)
    assert s.ee_rotvec.shape == (3,)
    assert s.gripper_pos == 42.0
