from httpx import AsyncClient, ASGITransport


async def test_health_returns_ok(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_session_state_idle_when_no_session(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/session/state")
    assert r.status_code == 200
    assert r.json()["state"] == "idle"


async def test_session_start_and_end(app, tmp_path):
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
        assert r.status_code == 200
        assert r.json()["state"] == "ready"
        assert r.json()["mode"] == "teleop"
        assert r.json()["cameras"] == []
        assert r.json()["gopros"] == []

        r = await ac.get("/api/session/state")
        assert r.json()["state"] == "ready"
        assert r.json()["gopros"] == []

        r = await ac.post("/api/session/end")
        assert r.status_code == 200
        assert r.json()["state"] == "idle"


async def test_session_config_requires_active_session(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/session/config")
    assert r.status_code == 409
