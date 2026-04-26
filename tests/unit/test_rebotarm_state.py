import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import numpy as np
from rebotarm_daemon.state import SharedRobotState


def test_snapshot_returns_independent_copy():
    s = SharedRobotState(dof=6)
    pos = np.array([1, 2, 3, 4, 5, 6], dtype=np.float32)
    s.set(joint_pos=pos, joint_vel=np.zeros(6, dtype=np.float32),
          joint_effort=np.zeros(6, dtype=np.float32),
          ee_pos=np.array([0.1, 0.2, 0.3], dtype=np.float32),
          ee_rotvec=np.array([0.0, 0.0, 0.5], dtype=np.float32),
          gripper_pos=42.0,
          motor_temps_c=np.array([35.0]*6, dtype=np.float32),
          motor_torques_nm=np.array([0.1]*6, dtype=np.float32))
    snap = s.snapshot()
    pos[0] = 999  # mutate original
    assert snap["joint_pos"][0] == 1  # snapshot unaffected
    assert snap["ee_pos"][0] == 0.1
    assert snap["gripper_pos"] == 42.0
    assert snap["motor_temps_c"][0] == 35.0


def test_snapshot_before_first_set_returns_zeros():
    s = SharedRobotState(dof=6)
    snap = s.snapshot()
    assert snap["joint_pos"].shape == (6,)
    assert (snap["joint_pos"] == 0).all()
    assert snap["ee_pos"] is None  # never been set
