"""End-to-end test for the session-level preview_enabled toggle.

The toggle must:
1. Round-trip through REST `/api/session/state` payload.
2. Round-trip through WS `/ws/session` initial snapshot.
3. Cause `/ws/cameras/{name}` to close with code 1008 + reason
   "preview disabled this session".
"""
from __future__ import annotations
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from mimicrec.api.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("MIMICREC_CONFIGS_ROOT", str(repo_root / "configs"))
    monkeypatch.setenv("MIMICREC_DATASETS_ROOT", str(tmp_path / "datasets"))
    app = create_app()
    # MockRobotAdapter has 2 DOF but configs/rebotarm/idle_pose.yaml has 6.
    # Patch out move_to_idle so HAND_TEACH session start doesn't raise a
    # DOF-mismatch ValueError (the same approach used by
    # tests/integration/test_idle_skip_for_teleop.py).
    with patch("mimicrec.session.lifecycle.move_to_idle", new=AsyncMock()):
        with TestClient(app) as c:
            yield c


def _start_body(preview_enabled: bool) -> dict:
    # Config names match files in repo `configs/`:
    #   configs/robot/mock.yaml         → MockRobotAdapter
    #   configs/cameras/mock_cam.yaml   → MockCamera
    return {
        "mode": "hand_teach",
        "dataset": "preview_toggle_test",
        "task": "default",
        "robot": "mock",
        "cameras": ["mock_cam"],
        "fps": 30,
        "preview_enabled": preview_enabled,
    }


def test_rest_state_echoes_preview_enabled_false(client: TestClient):
    r = client.post("/api/session/start", json=_start_body(False))
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["preview_enabled"] is False
    state2 = client.get("/api/session/state").json()
    assert state2["preview_enabled"] is False
    client.post("/api/session/end")


def test_rest_state_default_preview_enabled_is_true(client: TestClient):
    body = _start_body(True)
    body.pop("preview_enabled")  # omit field entirely
    r = client.post("/api/session/start", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["preview_enabled"] is True
    client.post("/api/session/end")


def test_ws_session_initial_snapshot_carries_preview_enabled_false(client: TestClient):
    client.post("/api/session/start", json=_start_body(False))
    try:
        with client.websocket_connect("/ws/session") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "session_state"
            assert msg["data"]["preview_enabled"] is False
    finally:
        client.post("/api/session/end")


def test_ws_camera_closes_1008_when_preview_disabled(client: TestClient):
    client.post("/api/session/start", json=_start_body(False))
    try:
        # The server accepts the WebSocket, then immediately sends a close
        # frame with code 1008.  Starlette's TestClient does not raise on
        # __enter__; the disconnect surfaces only when you attempt to
        # receive on the socket.  WebSocketDisconnect carries .code and
        # .reason directly (confirmed against starlette 0.x used here).
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect("/ws/cameras/mock_cam") as ws:
                ws.receive_bytes()  # triggers the buffered close frame
        assert excinfo.value.code == 1008
        assert "preview disabled" in excinfo.value.reason
    finally:
        client.post("/api/session/end")
