"""POST /api/session/idle-pose/capture: 409 ガード + happy path。"""
from __future__ import annotations
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from httpx import AsyncClient, ASGITransport

from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.types import SessionMode, SessionState
from mimicrec.util.metrics import Metrics


async def test_returns_409_when_no_session_active(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/session/idle-pose/capture")
    assert r.status_code == 409
    assert "session" in r.text.lower()


def _install_fake_session(app, *, mode: SessionMode):
    """Replace app.state.session_manager with a minimal stand-in that has
    just the surface the route reads."""
    robot = MockRobotAdapter()
    fake_session = SimpleNamespace(mode=mode, state=SessionState.READY)
    app.state.session_manager = SimpleNamespace(
        _robot=robot,
        session=fake_session,
    )


async def test_returns_409_when_mode_is_not_hand_teach(app):
    _install_fake_session(app, mode=SessionMode.TELEOP)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/session/idle-pose/capture")
    assert r.status_code == 409
    assert "hand_teach" in r.text.lower() or "hand-teach" in r.text.lower()


async def test_writes_yaml_and_returns_pose(app, tmp_path, monkeypatch):
    target = tmp_path / "idle_pose.yaml"
    import mimicrec.session.idle as idle_mod
    monkeypatch.setattr(idle_mod, "DEFAULT_IDLE_POSE_PATH", target)

    _install_fake_session(app, mode=SessionMode.HAND_TEACH)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/session/idle-pose/capture")

    assert r.status_code == 200, r.text
    body = r.json()
    assert "joint_pos_rad" in body
    assert "joint_pos_deg" in body
    assert "captured_at_unix" in body
    assert body["source"].startswith("ui_capture")

    doc = yaml.safe_load(target.read_text())
    assert doc["joint_pos_rad"] == body["joint_pos_rad"]


async def test_session_home_delegates_to_manager(app):
    home = AsyncMock()
    app.state.session_manager = SimpleNamespace(
        return_home=home,
        session=SimpleNamespace(state=SessionState.READY),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/api/session/home")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "state": "ready"}
    home.assert_awaited_once_with()


async def test_teleop_metrics_returns_only_teleop_gauges(app):
    metrics = Metrics()
    metrics.set_gauge("teleop_measured_position_error_m", 0.012)
    metrics.set_gauge("writer_lag_ms", 5.0)
    app.state.session_manager = SimpleNamespace(_metrics=metrics)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/session/teleop-metrics")

    assert response.status_code == 200
    assert response.json() == {
        "gauges": {"teleop_measured_position_error_m": 0.012}
    }
