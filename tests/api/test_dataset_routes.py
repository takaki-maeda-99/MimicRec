import json
import zipfile
import io
from pathlib import Path
import pytest
import pyarrow as pa
import pyarrow.parquet as pq
from httpx import AsyncClient, ASGITransport
from mimicrec.api.app import create_app
from mimicrec.recording.dataset_layout import dataset_paths, init_dataset
from mimicrec.recording.metadata import append_episode, tombstone_episode

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


async def test_episodes_have_display_index_compacting_after_delete(tmp_path: Path):
    """Live episodes should expose a 1-based display_index that closes the gap
    left by tombstoned episodes — the UI shows ordinals, not internal episode_index."""
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.post("/api/datasets", json={"name": "dsx", "fps": 30, "joint_names": ["j1", "j2"], "camera_names": []})

        import asyncio
        await ac.post("/api/session/start", json={
            "mode": "teleop", "dataset": "dsx", "task": "pick",
            "robot": "mock", "teleop": "mock_leader", "mapper": "identity",
            "cameras": [], "fps": 30,
        })
        for _ in range(3):
            await ac.post("/api/episode/start")
            await asyncio.sleep(0.1)
            await ac.post("/api/episode/stop")
            await ac.post("/api/episode/save")
        await ac.post("/api/session/end")

        r = await ac.get("/api/datasets/dsx/episodes")
        eps = r.json()
        assert [e["episode_index"] for e in eps] == [0, 1, 2]
        assert [e["display_index"] for e in eps] == [1, 2, 3]

        # Tombstone the middle one
        r = await ac.delete("/api/datasets/dsx/episodes/1")
        assert r.status_code == 204

        r = await ac.get("/api/datasets/dsx/episodes")
        eps = r.json()
        assert [e["episode_index"] for e in eps] == [0, 2]
        assert [e["display_index"] for e in eps] == [1, 2], "display_index should compact to 1,2"

        # Detail endpoint should return display_index too, ordinal-based
        r = await ac.get("/api/datasets/dsx/episodes/2")
        body = r.json()
        assert body["episode_index"] == 2
        assert body["display_index"] == 2


@pytest.mark.asyncio
async def test_deleted_episode_media_and_frames_are_not_served(tmp_path: Path):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path

    ds = tmp_path / "ds_media"
    init_dataset(ds, fps=30, joint_names=["j1"], camera_names=["front"])
    append_episode(
        ds / "meta",
        {
            "episode_index": 0,
            "task": "pick",
            "num_frames": 1,
            "duration_sec": 1 / 30,
            "cameras": ["front"],
        },
    )
    paths = dataset_paths(ds)
    paths.chunk_dir(0).mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist([{"timestamp": 0.0, "action.joint_pos": [0.0]}]),
        paths.episode_parquet(0, 0),
    )
    video = paths.episode_video(0, "front", 0)
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"fake-mp4")

    tombstone_episode(ds / "meta", 0, deleted_at_unix=1)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/datasets/ds_media/episodes/0/video/front")
        assert r.status_code == 404
        r = await ac.get("/api/datasets/ds_media/episodes/0/frames")
        assert r.status_code == 404


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


@pytest.mark.asyncio
async def test_archive_with_vla_compat_format_returns_400(tmp_path: Path):
    from mimicrec.api.app import create_app
    from mimicrec.recording.dataset_layout import init_dataset
    a = create_app()
    a.state.datasets_root = tmp_path
    init_dataset(tmp_path / "ds_vla", fps=15,
                 joint_names=["j1","j2","j3","j4","j5","j6"], camera_names=[])
    transport = ASGITransport(app=a)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get("/api/datasets/ds_vla/archive?format=vla_compat")
    assert r.status_code == 400
    assert "POST" in r.json()["detail"]


@pytest.mark.asyncio
async def test_archive_with_v3_native_format_succeeds(tmp_path: Path):
    from mimicrec.api.app import create_app
    from mimicrec.recording.dataset_layout import init_dataset
    a = create_app()
    a.state.datasets_root = tmp_path
    init_dataset(tmp_path / "ds_native", fps=15,
                 joint_names=["j1","j2","j3","j4","j5","j6"], camera_names=[])
    transport = ASGITransport(app=a)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get("/api/datasets/ds_native/archive?format=lerobot_v3_native")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
