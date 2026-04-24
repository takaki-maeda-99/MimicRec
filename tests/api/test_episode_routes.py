import asyncio
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


async def test_full_episode_cycle(tmp_path: Path):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Start session
        r = await ac.post("/api/session/start", json={
            "mode": "teleop", "dataset": "test_ds", "task": "pick",
            "robot": "mock", "teleop": "mock_leader", "mapper": "identity",
            "cameras": [], "fps": 30,
        })
        assert r.status_code == 200

        # Episode start
        r = await ac.post("/api/episode/start")
        assert r.status_code == 200
        assert r.json()["state"] == "recording"

        await asyncio.sleep(0.15)

        # Episode stop
        r = await ac.post("/api/episode/stop")
        assert r.status_code == 200
        assert r.json()["state"] == "review"

        # Episode save
        r = await ac.post("/api/episode/save", json={"success": True, "comment": "test"})
        assert r.status_code == 200
        assert r.json()["state"] == "ready"

        # Verify parquet exists
        ds_path = tmp_path / "datasets" / "test_ds" / "data" / "chunk-000" / "episode_000000.parquet"
        assert ds_path.exists()

        # End session
        r = await ac.post("/api/session/end")
        assert r.status_code == 200
        assert r.json()["state"] == "idle"


async def test_episode_discard(tmp_path: Path):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.post("/api/session/start", json={
            "mode": "teleop", "dataset": "test_ds", "task": "pick",
            "robot": "mock", "teleop": "mock_leader", "mapper": "identity",
            "cameras": [], "fps": 30,
        })
        await ac.post("/api/episode/start")
        await asyncio.sleep(0.1)
        await ac.post("/api/episode/stop")

        r = await ac.post("/api/episode/discard")
        assert r.status_code == 200
        assert r.json()["state"] == "ready"

        ds_path = tmp_path / "datasets" / "test_ds" / "data" / "chunk-000" / "episode_000000.parquet"
        assert not ds_path.exists()

        await ac.post("/api/session/end")


async def test_episode_requires_session(tmp_path: Path):
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/episode/start")
        assert r.status_code == 409
