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
async def test_new_dataset_uses_slot_names_as_image_keys(tmp_path: Path):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir(parents=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = {
            "mode": "hand_teach",
            "dataset": "slot_ds",
            "task": "t",
            "robot": "mock",
            "fps": 30,
            "slot_assignments": [
                {"slot": "front", "device": "mock_cam"},
            ],
        }
        r = await ac.post("/api/session/start", json=body)
        assert r.status_code == 200, r.text
        # Schema endpoint reflects the slot, not the device basename
        r = await ac.get("/api/datasets/slot_ds/schema")
        assert r.status_code == 200
        assert r.json()["image_keys"] == ["front"]
        await ac.post("/api/session/end")


@pytest.mark.asyncio
async def test_second_session_can_swap_device_for_same_slot(tmp_path: Path):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir(parents=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # First session: front = mock_cam
        body1 = {
            "mode": "hand_teach", "dataset": "swap_ds", "task": "t", "robot": "mock", "fps": 30,
            "slot_assignments": [{"slot": "front", "device": "mock_cam"}],
        }
        r = await ac.post("/api/session/start", json=body1)
        assert r.status_code == 200, r.text
        await ac.post("/api/session/end")

        # Second session, same slot, different device
        body2 = {
            "mode": "hand_teach", "dataset": "swap_ds", "task": "t", "robot": "mock", "fps": 30,
            "slot_assignments": [{"slot": "front", "device": "mock_front"}],
        }
        r = await ac.post("/api/session/start", json=body2)
        assert r.status_code == 200, r.text
        # info.json schema unchanged — same slot
        r = await ac.get("/api/datasets/swap_ds/schema")
        assert r.json()["image_keys"] == ["front"]
        await ac.post("/api/session/end")


@pytest.mark.asyncio
async def test_second_session_with_different_slot_set_400(tmp_path: Path):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir(parents=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body1 = {
            "mode": "hand_teach", "dataset": "schema_strict_ds", "task": "t", "robot": "mock", "fps": 30,
            "slot_assignments": [{"slot": "front", "device": "mock_cam"}],
        }
        await ac.post("/api/session/start", json=body1)
        await ac.post("/api/session/end")

        body2 = {
            "mode": "hand_teach", "dataset": "schema_strict_ds", "task": "t", "robot": "mock", "fps": 30,
            "slot_assignments": [{"slot": "wrist", "device": "mock_cam"}],
        }
        r = await ac.post("/api/session/start", json=body2)
        assert r.status_code == 400, r.text
        assert "slot" in r.text.lower()
