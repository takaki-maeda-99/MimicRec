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


@pytest.mark.asyncio
async def test_duplicate_opencv_device_id_400(tmp_path):
    """Two OpenCV cameras with the same device_id (e.g. both pointing at /dev/video0)
    must be rejected before adapters are instantiated."""
    app = _make_app(tmp_path)
    # configs/cameras/front.yaml and configs/cameras/wrist.yaml both have
    # device_id: 0; front/wrist are both in camera_roles.yaml, so the
    # slot-vocab check passes and the physical-ID check is the one that fires.
    req = _req(slot_assignments=[
        SlotAssignment(slot="front", device="front"),
        SlotAssignment(slot="wrist", device="wrist"),
    ])
    with pytest.raises(HTTPException) as exc:
        await create_session_from_request(app, req)
    assert exc.value.status_code == 400
    assert "device_id" in str(exc.value.detail) or "device id" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_duplicate_gopro_usb_serial_400(tmp_path):
    """Two GoPros sharing usb_serial must be rejected by deps before the
    registry-level check ever runs (registry would raise ValueError → 500
    without the deps-level wrap)."""
    app = _make_app(tmp_path)
    # configs/gopros/mock_gopro.yaml has usb_serial = "MOCK0001". To trigger
    # the duplicate detection we need TWO yamls with the same serial. Create
    # a sibling on disk temporarily.
    import shutil
    src = app.state.configs_root / "gopros" / "mock_gopro.yaml"
    dup = app.state.configs_root / "gopros" / "mock_gopro_dup.yaml"
    shutil.copy(src, dup)
    try:
        req = _req(slot_assignments=[
            SlotAssignment(slot="front", device="mock_gopro"),
            SlotAssignment(slot="wrist", device="mock_gopro_dup"),
        ])
        with pytest.raises(HTTPException) as exc:
            await create_session_from_request(app, req)
        assert exc.value.status_code == 400
        assert "usb_serial" in str(exc.value.detail)
    finally:
        dup.unlink(missing_ok=True)
