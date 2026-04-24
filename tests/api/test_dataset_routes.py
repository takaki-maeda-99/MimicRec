import json
import zipfile
import io
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from mimicrec.api.app import create_app
from mimicrec.recording.dataset_layout import init_dataset

REPO_ROOT = Path(__file__).resolve().parents[2]


async def test_create_and_list_datasets(tmp_path: Path):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/datasets", json={"name": "ds1", "fps": 30, "joint_names": ["j1"], "camera_names": []})
        assert r.status_code == 200
        assert r.json()["name"] == "ds1"

        r = await ac.get("/api/datasets")
        assert r.status_code == 200
        names = [d["name"] for d in r.json()]
        assert "ds1" in names


async def test_delete_episode_tombstones(tmp_path: Path):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create dataset and record an episode via session
        await ac.post("/api/datasets", json={"name": "ds2", "fps": 30, "joint_names": ["j1", "j2"], "camera_names": []})

        import asyncio
        await ac.post("/api/session/start", json={
            "mode": "teleop", "dataset": "ds2", "task": "pick",
            "robot": "mock", "teleop": "mock_leader", "mapper": "identity",
            "cameras": [], "fps": 30,
        })
        await ac.post("/api/episode/start")
        await asyncio.sleep(0.1)
        await ac.post("/api/episode/stop")
        await ac.post("/api/episode/save")
        await ac.post("/api/session/end")

        # Delete episode
        r = await ac.delete("/api/datasets/ds2/episodes/0")
        assert r.status_code == 204

        # Verify tombstoned
        r = await ac.get("/api/datasets/ds2/episodes")
        assert len(r.json()) == 0

        r = await ac.get("/api/datasets/ds2/episodes", params={"include_deleted": "true"})
        assert len(r.json()) == 1


async def test_archive_download(tmp_path: Path):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        import asyncio
        await ac.post("/api/datasets", json={"name": "ds3", "fps": 30, "joint_names": ["j1", "j2"], "camera_names": []})
        await ac.post("/api/session/start", json={
            "mode": "teleop", "dataset": "ds3", "task": "pick",
            "robot": "mock", "teleop": "mock_leader", "mapper": "identity",
            "cameras": [], "fps": 30,
        })
        await ac.post("/api/episode/start")
        await asyncio.sleep(0.1)
        await ac.post("/api/episode/stop")
        await ac.post("/api/episode/save")
        await ac.post("/api/session/end")

        r = await ac.get("/api/datasets/ds3/archive")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"
        buf = io.BytesIO(r.content)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
            assert any("episode_000000.parquet" in n for n in names)
