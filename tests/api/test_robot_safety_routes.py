"""API tests for POST /api/robot/estop and /api/robot/clear_estop.

The "negative" paths (no active session, or active session whose adapter
lacks a safety surface) are checked here — they must map to a 4xx, never
500. The full happy-path round-trip (estop -> reject -> clear -> resume
against a real session pointing at the mock reBotArm daemon) is covered
by ``tests/integration/test_rebotarm_estop.py`` at the adapter level;
re-routing it through the FastAPI app would require spinning up the
mock daemon plus a temp robot YAML pointing at its dynamic port, which
the task plan explicitly defers.
"""
from __future__ import annotations

from httpx import AsyncClient, ASGITransport


async def test_estop_rejects_when_no_session(app):
    """Without an active session, /api/robot/estop must refuse cleanly
    (InvalidTransitionError -> 409), not crash with 500."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/robot/estop")
    assert r.status_code in (400, 404, 409), r.text


async def test_clear_estop_rejects_when_no_session(app):
    """Same contract as estop: no session -> 4xx, never 500."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/robot/clear_estop")
    assert r.status_code in (400, 404, 409), r.text


async def test_estop_rejects_when_adapter_lacks_safety(app, tmp_path):
    """Active session whose robot adapter has no estop() (e.g. mock,
    sim_so101) must also reject cleanly so the UI button is safe to
    expose unconditionally."""
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/session/start", json={
            "mode": "teleop",
            "dataset": "test_ds",
            "task": "pick",
            "robot": "mock",
            "teleop": "mock_leader",
            "mapper": "identity",
            "cameras": [],
            "fps": 30,
        })
        assert r.status_code == 200, r.text

        try:
            r = await ac.post("/api/robot/estop")
            assert r.status_code in (400, 404, 409), r.text

            r = await ac.post("/api/robot/clear_estop")
            assert r.status_code in (400, 404, 409), r.text
        finally:
            await ac.post("/api/session/end")
