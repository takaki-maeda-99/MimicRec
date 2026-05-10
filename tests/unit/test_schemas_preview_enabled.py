from mimicrec.api.schemas import (
    HandTeachSessionRequest,
    SessionStatePayload,
    TeleopSessionRequest,
)


def _teleop_kwargs(**extra):
    base = dict(
        dataset="ds", task="t", robot="r", cameras=["c"],
        teleop="tl", mapper="mp",
    )
    base.update(extra)
    return base


def test_teleop_request_preview_enabled_defaults_true():
    req = TeleopSessionRequest(**_teleop_kwargs())
    assert req.preview_enabled is True


def test_teleop_request_accepts_preview_enabled_false():
    req = TeleopSessionRequest(**_teleop_kwargs(preview_enabled=False))
    assert req.preview_enabled is False


def test_handteach_request_inherits_preview_enabled_default():
    req = HandTeachSessionRequest(
        dataset="ds", task="t", robot="r", cameras=["c"],
    )
    assert req.preview_enabled is True


def test_state_payload_preview_enabled_defaults_true():
    p = SessionStatePayload(state="idle")
    assert p.preview_enabled is True


def test_state_payload_round_trips_preview_enabled_false():
    p = SessionStatePayload(state="ready", preview_enabled=False)
    dumped = p.model_dump()
    assert dumped["preview_enabled"] is False
