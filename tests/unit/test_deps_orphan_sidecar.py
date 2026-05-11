from __future__ import annotations
import json
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
    app.state.datasets_root.mkdir(parents=True, exist_ok=True)
    app.state.push_coordinator = None
    return app


def _seed_sidecar(datasets_root: Path, ds: str, content: dict | str) -> None:
    pdir = datasets_root / ds / ".pending" / "gopro_dl"
    pdir.mkdir(parents=True)
    sidecar = pdir / "stale.json"
    if isinstance(content, str):
        sidecar.write_text(content)
    else:
        sidecar.write_text(json.dumps(content))


@pytest.mark.asyncio
async def test_orphan_sidecar_with_unknown_cam_name_409(tmp_path):
    _seed_sidecar(tmp_path / "datasets", "ds1", {
        "job_id": "j1", "gopro_serial": "S0", "sd_filename": "GX010001.MP4",
        "episode_index": 0, "chunk_index": 0, "cam_name": "ghost_slot",
        "episode_start_mono_ns": 0, "episode_stop_mono_ns": 10_000_000_000,
        "state": "pending_dl",
    })
    app = _make_app(tmp_path)
    req = HandTeachSessionRequest(dataset="ds1", task="t", robot="mock",
        slot_assignments=[SlotAssignment(slot="front", device="mock_cam")])
    with pytest.raises(HTTPException) as exc:
        await create_session_from_request(app, req)
    assert exc.value.status_code == 409
    assert "ghost_slot" in str(exc.value.detail) or "orphan" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_corrupt_sidecar_409(tmp_path):
    _seed_sidecar(tmp_path / "datasets", "ds_corrupt", "not valid json {")
    app = _make_app(tmp_path)
    req = HandTeachSessionRequest(dataset="ds_corrupt", task="t", robot="mock",
        slot_assignments=[SlotAssignment(slot="front", device="mock_cam")])
    with pytest.raises(HTTPException) as exc:
        await create_session_from_request(app, req)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_sidecar_with_matching_slot_passes(tmp_path):
    _seed_sidecar(tmp_path / "datasets", "ds_ok", {
        "job_id": "j1", "gopro_serial": "S0", "sd_filename": "GX010001.MP4",
        "episode_index": 0, "chunk_index": 0, "cam_name": "front",
        "episode_start_mono_ns": 0, "episode_stop_mono_ns": 10_000_000_000,
        "state": "pending_dl",
    })
    app = _make_app(tmp_path)
    req = HandTeachSessionRequest(dataset="ds_ok", task="t", robot="mock",
        slot_assignments=[SlotAssignment(slot="front", device="mock_cam")])
    # Should NOT raise an orphan check 409. (Other errors may surface
    # from the rest of the start flow but the orphan check itself passes.)
    try:
        sm = await create_session_from_request(app, req)
        await sm.end()
    except HTTPException as e:
        assert e.status_code != 409, f"unexpected 409: {e.detail}"
