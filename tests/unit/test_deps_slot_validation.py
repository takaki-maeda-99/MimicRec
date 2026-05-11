from __future__ import annotations
from pathlib import Path

import pytest
from fastapi import HTTPException, FastAPI

from mimicrec.api.deps import create_session_from_request
from mimicrec.api.schemas import HandTeachSessionRequest, SlotAssignment


REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir(parents=True)
    app.state.push_coordinator = None
    return app


def _req(**extra) -> HandTeachSessionRequest:
    base = dict(dataset="ds1", task="t", robot="mock", fps=30)
    base.update(extra)
    return HandTeachSessionRequest(**base)


@pytest.mark.asyncio
async def test_legacy_cameras_gopros_normalized_into_slot_assignments(tmp_path):
    """Legacy clients sending {cameras: ['mock_cam']} must be rewritten."""
    app = _make_app(tmp_path)
    req = _req(cameras=["mock_cam"], gopros=[])
    sm = await create_session_from_request(app, req)
    try:
        slot_assigns = app.state.session_meta["slot_assignments"]
        assert {a["slot"] for a in slot_assigns} == {"mock_cam"}
        assert {a["device"] for a in slot_assigns} == {"mock_cam"}
    finally:
        await sm.end()


@pytest.mark.asyncio
async def test_duplicate_slot_400(tmp_path):
    app = _make_app(tmp_path)
    req = _req(slot_assignments=[
        SlotAssignment(slot="front", device="mock_cam"),
        SlotAssignment(slot="front", device="mock_front"),
    ])
    with pytest.raises(HTTPException) as exc:
        await create_session_from_request(app, req)
    assert exc.value.status_code == 400
    assert "duplicate slot" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_duplicate_device_basename_400(tmp_path):
    app = _make_app(tmp_path)
    req = _req(slot_assignments=[
        SlotAssignment(slot="front", device="mock_cam"),
        SlotAssignment(slot="wrist", device="mock_cam"),
    ])
    with pytest.raises(HTTPException) as exc:
        await create_session_from_request(app, req)
    assert exc.value.status_code == 400
    assert "duplicate device" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_slot_not_in_roles_or_image_keys_400(tmp_path):
    app = _make_app(tmp_path)
    req = _req(slot_assignments=[
        SlotAssignment(slot="bogus_slot", device="mock_cam"),
    ])
    with pytest.raises(HTTPException) as exc:
        await create_session_from_request(app, req)
    assert exc.value.status_code == 400
    assert "bogus_slot" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_path_unsafe_slot_400(tmp_path):
    app = _make_app(tmp_path)
    req = _req(slot_assignments=[
        SlotAssignment(slot="../escape", device="mock_cam"),
    ])
    with pytest.raises(HTTPException) as exc:
        await create_session_from_request(app, req)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_missing_device_400(tmp_path):
    app = _make_app(tmp_path)
    req = _req(slot_assignments=[
        SlotAssignment(slot="front", device="ghost_device"),
    ])
    with pytest.raises(HTTPException) as exc:
        await create_session_from_request(app, req)
    assert exc.value.status_code == 400
    assert "ghost_device" in str(exc.value.detail)
