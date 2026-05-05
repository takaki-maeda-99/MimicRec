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


def test_slow_stop_alpha_series():
    s = _make_safety(slow_stop_ticks=5)
    s.filter(StepAction(q=np.full(5, 5.0), gripper=0.5),
             q_curr=np.zeros(5), tick_t_ns=1)
    # _last_safe_q is now ~ [2,2,2,2,2] (clamped to max_delta=2)
    # Now buffer empty -> slow-stop tries to converge to q_curr=10
    expected_alphas = [0.2, 0.4, 0.6, 0.8, 1.0]
    last = s._last_safe_q.copy()
    for tick, expected_alpha in enumerate(expected_alphas, start=1):
        cmd = s.filter(None, q_curr=np.full(5, 10.0), tick_t_ns=tick)
        # alpha-interpolated between last and 10.0
        expected_q = last + (np.full(5, 10.0) - last) * expected_alpha
        if expected_alpha < 1.0:
            assert np.allclose(cmd.q, expected_q, atol=1e-6), \
                f"tick {tick}: alpha {expected_alpha}"


def test_filter_with_step_gripper_none_holds_last():
    s = _make_safety()
    s.filter(StepAction(q=np.zeros(5), gripper=0.7), q_curr=np.zeros(5), tick_t_ns=1)
    cmd = s.filter(StepAction(q=np.zeros(5), gripper=None), q_curr=np.zeros(5), tick_t_ns=2)
    assert cmd.gripper == 0.7


def test_on_new_chunk_resets_clamp_count():
    s = _make_safety(max_delta=0.1)
    s.filter(StepAction(q=np.full(5, 5.0), gripper=0.0), q_curr=np.zeros(5), tick_t_ns=1)
    assert s.clamps_in_current_chunk() == 1
    s.on_new_chunk()
    assert s.clamps_in_current_chunk() == 0
