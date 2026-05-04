import numpy as np

from mimicrec.inference.types import StepAction, SafetyEvent


def test_step_action_basic():
    s = StepAction(q=np.array([0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float64),
                   gripper=0.5)
    assert s.gripper == 0.5
    assert s.ik_failed is False


def test_step_action_ik_failed():
    s = StepAction(q=np.zeros(5), gripper=None, ik_failed=True)
    assert s.ik_failed is True


def test_safety_event_serialization():
    e = SafetyEvent(kind="delta_clamp", step_index=3, joint="elbow_flex")
    d = e.as_dict()
    assert d == {"type": "safety_event", "kind": "delta_clamp",
                 "step_index": 3, "joint": "elbow_flex"}
