import pytest

from mimicrec.api.schemas import (
    HandTeachSessionRequest,
    ImageSource,
    SessionStatePayload,
    SlotAssignment,
    TeleopSessionRequest,
)


def _teleop_kwargs(**extra):
    base = dict(
        dataset="ds", task="t", robot="r",
        teleop="tl", mapper="mp",
    )
    base.update(extra)
    return base


def test_slot_assignment_parses():
    a = SlotAssignment(slot="front", device="mock_cam")
    assert a.slot == "front"
    assert a.device == "mock_cam"


def test_image_source_parses():
    s = ImageSource(slot="front", device="mock_cam", kind="camera")
    assert s.kind == "camera"


def test_session_request_accepts_slot_assignments():
    req = TeleopSessionRequest(**_teleop_kwargs(
        slot_assignments=[
            {"slot": "front", "device": "front_cam"},
            {"slot": "wrist", "device": "mock_cam"},
        ],
    ))
    assert [a.slot for a in req.slot_assignments] == ["front", "wrist"]


def test_session_request_still_accepts_legacy_cameras():
    """Backward-compat: legacy clients sending cameras must still parse;
    the deps layer normalizes them into slot_assignments."""
    req = HandTeachSessionRequest(
        dataset="ds", task="t", robot="r",
        cameras=["front"],
    )
    assert req.cameras == ["front"]
    assert req.slot_assignments == []


def test_session_state_payload_includes_image_sources():
    p = SessionStatePayload(
        state="ready",
        image_sources=[
            ImageSource(slot="front", device="mock_cam", kind="camera"),
        ],
    )
    dumped = p.model_dump()
    assert dumped["image_sources"] == [
        {"slot": "front", "device": "mock_cam", "kind": "camera"}
    ]
