from __future__ import annotations
import pytest
from httpx import AsyncClient, ASGITransport

from mimicrec.api.app import create_app
from mimicrec.cloud.push_state import PushCoordinator
from mimicrec.recording.dataset_layout import init_dataset


@pytest.fixture
def client_and_root(tmp_path):
    app = create_app()
    app.state.datasets_root = tmp_path
    app.state.push_coordinator = PushCoordinator()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), tmp_path, app


@pytest.mark.asyncio
async def test_post_tasks_acquires_lock(client_and_root, monkeypatch):
    client, root, app = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])

    captured = {}
    from mimicrec.recording import metadata as meta_mod
    real = meta_mod.upsert_task

    def spy(meta_dir, name, instr, *, coordinator=None, ds_name=None):
        captured["coordinator"] = coordinator
        captured["ds_name"] = ds_name
        return real(meta_dir, name, instr, coordinator=coordinator, ds_name=ds_name)

    # Patch BOTH the source module's symbol AND the routes module's binding
    # (because routes/datasets.py likely does `from ...metadata import upsert_task`)
    monkeypatch.setattr(meta_mod, "upsert_task", spy)
    from mimicrec.api.routes import datasets as routes_mod
    if hasattr(routes_mod, "upsert_task"):
        monkeypatch.setattr(routes_mod, "upsert_task", spy)

    async with client as ac:
        r = await ac.post("/api/datasets/ds/tasks", json={
            "name": "pick", "instruction": "pick the ball",
        })
    assert r.status_code == 200
    assert captured["coordinator"] is not None
    assert captured["ds_name"] == "ds"


@pytest.mark.asyncio
async def test_delete_episode_acquires_lock(client_and_root, monkeypatch):
    client, root, app = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    from mimicrec.recording.metadata import append_episode
    append_episode(
        root / "ds" / "meta",
        {"episode_index": 0, "task": "t", "num_frames": 1, "duration_sec": 0.1, "cameras": []},
    )

    from mimicrec.recording import metadata as meta_mod
    captured = {}
    real = meta_mod.tombstone_episode

    def spy(meta_dir, idx, deleted_at_unix, *, coordinator=None, ds_name=None):
        captured["coordinator"] = coordinator
        captured["ds_name"] = ds_name
        return real(meta_dir, idx, deleted_at_unix, coordinator=coordinator, ds_name=ds_name)

    monkeypatch.setattr(meta_mod, "tombstone_episode", spy)
    from mimicrec.api.routes import datasets as routes_mod
    if hasattr(routes_mod, "tombstone_episode"):
        monkeypatch.setattr(routes_mod, "tombstone_episode", spy)

    async with client as ac:
        r = await ac.delete("/api/datasets/ds/episodes/0")
    assert r.status_code == 204
    assert captured["coordinator"] is not None
    assert captured["ds_name"] == "ds"
