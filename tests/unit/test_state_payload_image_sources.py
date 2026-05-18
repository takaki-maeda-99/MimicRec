from __future__ import annotations
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MIMICREC_CONFIGS_ROOT", str(REPO_ROOT / "configs"))
    monkeypatch.setenv("MIMICREC_DATASETS_ROOT", str(tmp_path / "datasets"))
    app = create_app()
    # MockRobotAdapter has 2 DOF but configs/rebotarm/idle_pose.yaml has 6.
    # Patch out move_to_idle so HAND_TEACH session start doesn't raise a
    # DOF-mismatch ValueError.
    with patch("mimicrec.session.lifecycle.move_to_idle", new=AsyncMock()):
        with TestClient(app) as c:
            yield c


def _start_body() -> dict:
    return {
        "mode": "hand_teach",
        "dataset": "img_src_ds",
        "task": "default",
        "robot": "mock",
        "fps": 30,
        "slot_assignments": [
            {"slot": "front", "device": "mock_cam"},
        ],
    }


def test_rest_state_includes_image_sources(client: TestClient):
    r = client.post("/api/session/start", json=_start_body())
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["image_sources"] == [
        {"slot": "front", "device": "mock_cam", "kind": "camera"}
    ]
    # Legacy mirror still populated by kind-filtered slot names
    assert state["cameras"] == ["front"]
    client.post("/api/session/end")


def test_ws_state_includes_image_sources(client: TestClient):
    client.post("/api/session/start", json=_start_body())
    try:
        with client.websocket_connect("/ws/session") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "session_state"
            assert msg["data"]["image_sources"] == [
                {"slot": "front", "device": "mock_cam", "kind": "camera"}
            ]
    finally:
        client.post("/api/session/end")
