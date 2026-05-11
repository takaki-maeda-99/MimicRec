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
    a = SlotAssignment(slot="front", device="gopro_external")
    assert a.slot == "front"
    assert a.device == "gopro_external"


def test_image_source_parses():
    s = ImageSource(slot="front", device="gopro_external", kind="gopro")
    assert s.kind == "gopro"


def test_session_request_accepts_slot_assignments():
    req = TeleopSessionRequest(**_teleop_kwargs(
        slot_assignments=[
            {"slot": "front", "device": "gopro_external"},
            {"slot": "wrist", "device": "mock_cam"},
        ],
    ))
    assert [a.slot for a in req.slot_assignments] == ["front", "wrist"]


def test_session_request_still_accepts_legacy_cameras_gopros():
    """Backward-compat: legacy clients sending cameras/gopros must still
    parse; the deps layer normalizes them into slot_assignments."""
    req = HandTeachSessionRequest(
        dataset="ds", task="t", robot="r",
        cameras=["front"], gopros=["gopro_external"],
    )
    assert req.cameras == ["front"]
    assert req.gopros == ["gopro_external"]
    assert req.slot_assignments == []


def test_session_state_payload_includes_image_sources():
    p = SessionStatePayload(
        state="ready",
        image_sources=[
            ImageSource(slot="front", device="gopro_external", kind="gopro"),
        ],
    )
    dumped = p.model_dump()
    assert dumped["image_sources"] == [
        {"slot": "front", "device": "gopro_external", "kind": "gopro"}
    ]
