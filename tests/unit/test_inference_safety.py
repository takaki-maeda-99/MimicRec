import numpy as np
import pytest

from mimicrec.inference.safety import InferenceSafety
from mimicrec.inference.types import StepAction


def _make_safety(max_delta: float = 2.0, slow_stop_ticks: int = 5) -> InferenceSafety:
    return InferenceSafety(
        max_delta=max_delta,
        joint_min=np.array([-90.0]*5),
        joint_max=np.array([+90.0]*5),
        slow_stop_ticks=slow_stop_ticks,
    )


def test_filter_passes_within_limits():
    s = _make_safety()
    cmd = s.filter(StepAction(q=np.full(5, 1.0), gripper=0.5),
                   q_curr=np.zeros(5), tick_t_ns=1)
    assert np.allclose(cmd.q, 1.0)
    assert cmd.gripper == 0.5


def test_filter_clamps_delta():
    s = _make_safety(max_delta=1.0)
    cmd = s.filter(StepAction(q=np.full(5, 5.0), gripper=None),
                   q_curr=np.zeros(5), tick_t_ns=1)
    assert np.allclose(cmd.q, 1.0)        # clamped to ±1.0


def test_filter_clips_at_joint_limit():
    s = _make_safety(max_delta=100.0)
    cmd = s.filter(StepAction(q=np.full(5, 200.0), gripper=None),
                   q_curr=np.full(5, 80.0), tick_t_ns=1)
    assert np.allclose(cmd.q, 90.0)
