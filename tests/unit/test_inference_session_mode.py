from mimicrec.types import SessionMode


def test_session_mode_inference_exists():
    assert SessionMode.INFERENCE.value == "inference"


def test_session_mode_full_set():
    assert {m.value for m in SessionMode} >= {"teleop", "hand_teach", "inference"}
