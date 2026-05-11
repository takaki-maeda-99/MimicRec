from __future__ import annotations
from pathlib import Path

import pytest
from fastapi import FastAPI

from mimicrec.api.deps import create_session_from_request
from mimicrec.api.schemas import HandTeachSessionRequest, SlotAssignment

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def app(tmp_path):
    app = FastAPI()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir(parents=True, exist_ok=True)
    app.state.push_coordinator = None
    return app


@pytest.mark.asyncio
async def test_resolved_config_records_full_slot_assignment_snapshot(app):
    req = HandTeachSessionRequest(
        dataset="ds_res", task="t", robot="mock",
        slot_assignments=[SlotAssignment(slot="front", device="mock_cam")],
    )
    sm = await create_session_from_request(app, req)
    try:
        rc = app.state.resolved_config
        assert "slot_assignments" in rc
        snap = rc["slot_assignments"]
        assert len(snap) == 1
        assert snap[0]["slot"] == "front"
        assert snap[0]["device"] == "mock_cam"
        assert snap[0]["kind"] == "camera"
        assert "device_config" in snap[0]
        assert snap[0]["device_config"]["_target_"].endswith("MockCamera")
    finally:
        await sm.end()
