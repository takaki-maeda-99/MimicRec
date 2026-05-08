"""Tests that session schemas carry a gopros field (default empty list)."""
from mimicrec.api.schemas import TeleopSessionRequest, HandTeachSessionRequest, SessionStatePayload


def test_teleop_session_request_gopros_default_empty():
    r = TeleopSessionRequest(
        dataset="ds",
        task="task1",
        robot="robot1",
        cameras=["cam0"],
        teleop="leader",
        mapper="identity",
    )
    assert r.gopros == []


def test_teleop_session_request_gopros_explicit():
    r = TeleopSessionRequest(
        dataset="ds",
        task="task1",
        robot="robot1",
        cameras=["cam0"],
        teleop="leader",
        mapper="identity",
        gopros=["g1"],
    )
    assert r.gopros == ["g1"]


def test_session_state_payload_gopros_default_empty():
    p = SessionStatePayload(state="IDLE")
    assert p.gopros == []
