from __future__ import annotations
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient, ASGITransport

from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _mock_move_to_idle(monkeypatch):
    monkeypatch.setattr(
        "mimicrec.session.lifecycle.move_to_idle",
        AsyncMock(),
    )
    yield


@pytest.mark.asyncio
async def test_legacy_cameras_only_body_starts_session(tmp_path: Path):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir(parents=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = {
            "mode": "hand_teach", "dataset": "legacy_ds", "task": "t", "robot": "mock", "fps": 30,
            "cameras": ["mock_cam"],   # legacy field
            # no slot_assignments
        }
        r = await ac.post("/api/session/start", json=body)
        assert r.status_code == 200, r.text
        # Image sources are populated by the shim (slot == device == "mock_cam")
        assert r.json()["image_sources"] == [
            {"slot": "mock_cam", "device": "mock_cam", "kind": "camera"}
        ]
        await ac.post("/api/session/end")
