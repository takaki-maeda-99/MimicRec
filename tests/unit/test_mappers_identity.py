import numpy as np
import pytest
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.types import RobotState, TeleopAction


def test_identity_pass_through():
    m = IdentityMapper()
    action = TeleopAction(target_joint_pos=np.array([0.1, 0.2], dtype=np.float32))
    state = RobotState(
        joint_pos=np.zeros(2, np.float32),
        joint_vel=np.zeros(2, np.float32),
        joint_effort=np.zeros(2, np.float32),
    )
    cmd = m.map(action, state)
    assert cmd.q.tolist() == [pytest.approx(0.1), pytest.approx(0.2)]
