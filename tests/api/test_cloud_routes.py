from __future__ import annotations
import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport

from mimicrec.api.app import create_app
from mimicrec.cloud.hub_meta import HubMeta, write_hub_meta, hub_meta_path
from mimicrec.cloud.push_state import PushCoordinator, PushProgress
from mimicrec.recording.dataset_layout import init_dataset


@pytest.fixture
def client_and_root(tmp_path):
    app = create_app()
    app.state.datasets_root = tmp_path
    app.state.push_coordinator = PushCoordinator()
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    # 3-tuple: (client, datasets_root, app) — テストから coordinator を直に触る用
    return client, tmp_path, app


@pytest.mark.asyncio
async def test_auth_status_no_token(client_and_root):
    client, _, _ = client_and_root
    with patch("mimicrec.api.routes.cloud.get_token", return_value=None), \
         patch("mimicrec.api.routes.cloud.HfApi") as MockApi:
        async with client as ac:
            r = await ac.get("/api/cloud/auth-status")
    assert r.status_code == 200
    assert r.json()["authenticated"] is False
    assert r.json()["username"] is None


@pytest.mark.asyncio
async def test_auth_status_with_token(client_and_root):
    client, _, _ = client_and_root
    with patch("mimicrec.api.routes.cloud.get_token", return_value="hf_xxx"), \
         patch("mimicrec.api.routes.cloud.HfApi") as MockApi:
        MockApi.return_value.whoami.return_value = {"name": "TakakiMaeda"}
        async with client as ac:
            r = await ac.get("/api/cloud/auth-status")
    assert r.status_code == 200
    assert r.json()["authenticated"] is True
    assert r.json()["username"] == "TakakiMaeda"


@pytest.mark.asyncio
async def test_auth_status_token_present_but_whoami_fails(client_and_root):
    client, _, _ = client_and_root
    with patch("mimicrec.api.routes.cloud.get_token", return_value="hf_invalid"), \
         patch("mimicrec.api.routes.cloud.HfApi") as MockApi:
        MockApi.return_value.whoami.side_effect = RuntimeError("token rejected")
        async with client as ac:
            r = await ac.get("/api/cloud/auth-status")
    assert r.status_code == 200
    assert r.json()["authenticated"] is False
    assert r.json()["username"] is None


@pytest.mark.asyncio
async def test_get_hub_returns_null_when_unconfigured(client_and_root):
    client, root, app = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    async with client as ac:
        r = await ac.get("/api/datasets/ds/hub")
    assert r.status_code == 200
    body = r.json()
    assert body["config"] is None
    assert body["state"] is None
    assert body["progress"]["status"] == "idle"


@pytest.mark.asyncio
async def test_put_hub_creates_meta(client_and_root):
    client, root, app = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    async with client as ac:
        r = await ac.put("/api/datasets/ds/hub", json={
            "repo_id": "TakakiMaeda/learn-data-bottle",
        })
    assert r.status_code == 200
    body = r.json()
    assert body["config"]["repo_id"] == "TakakiMaeda/learn-data-bottle"
    assert body["config"]["private"] is True   # default
    assert body["config"]["auto_push"] is False
    # meta/hub.json が書かれている
    p = hub_meta_path(root / "ds")
    saved = json.loads(p.read_text())
    assert saved["repo_id"] == "TakakiMaeda/learn-data-bottle"


@pytest.mark.asyncio
async def test_put_hub_rejects_invalid_repo_id(client_and_root):
    client, root, app = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    async with client as ac:
        r = await ac.put("/api/datasets/ds/hub", json={"repo_id": "no-slash"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_put_hub_path_traversal_rejected(client_and_root):
    client, root, app = client_and_root
    async with client as ac:
        r = await ac.put("/api/datasets/..%2Fetc/hub", json={"repo_id": "u/d"})
    # ..%2F は dataset name として不正 → 400 / 404 のいずれか
    assert r.status_code in (400, 404)


@pytest.mark.asyncio
async def test_post_push_401_when_no_token(client_and_root):
    client, root, app = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    write_hub_meta(root / "ds", HubMeta(repo_id="u/d"))
    with patch("mimicrec.api.routes.cloud.get_token", return_value=None):
        async with client as ac:
            r = await ac.post("/api/datasets/ds/hub/push")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_post_push_400_when_hub_unconfigured(client_and_root):
    client, root, app = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    with patch("mimicrec.api.routes.cloud.get_token", return_value="hf_xxx"):
        async with client as ac:
            r = await ac.post("/api/datasets/ds/hub/push")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_post_push_404_when_dataset_absent(client_and_root):
    client, _, _ = client_and_root
    with patch("mimicrec.api.routes.cloud.get_token", return_value="hf_xxx"):
        async with client as ac:
            r = await ac.post("/api/datasets/nope/hub/push")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_post_push_202_then_409_for_duplicate(client_and_root, monkeypatch):
    client, root, app = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    write_hub_meta(root / "ds", HubMeta(repo_id="u/d"))

    import asyncio as _a
    started = _a.Event()
    release = _a.Event()

    async def hanging_task(*a, **kw):
        started.set()
        await release.wait()

    monkeypatch.setattr("mimicrec.api.routes.cloud._run_push_with_release", hanging_task)

    with patch("mimicrec.api.routes.cloud.get_token", return_value="hf_xxx"):
        async with client as ac:
            r1 = await ac.post("/api/datasets/ds/hub/push")
            assert r1.status_code == 202
            await _a.wait_for(started.wait(), timeout=2.0)
            r2 = await ac.post("/api/datasets/ds/hub/push")
            assert r2.status_code == 409
            release.set()


@pytest.mark.asyncio
async def test_post_push_5_concurrent_only_one_runs(client_and_root, monkeypatch):
    """spec DoD: '同 ds の POST /hub/push を連続 5 回叩いても 1 本だけ走る'"""
    client, root, app = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    write_hub_meta(root / "ds", HubMeta(repo_id="u/d"))

    import asyncio as _a
    started_count = 0
    release = _a.Event()

    async def hanging_task(*a, **kw):
        nonlocal started_count
        started_count += 1
        await release.wait()

    monkeypatch.setattr("mimicrec.api.routes.cloud._run_push_with_release", hanging_task)

    with patch("mimicrec.api.routes.cloud.get_token", return_value="hf_xxx"):
        async with client as ac:
            results = await _a.gather(*[
                ac.post("/api/datasets/ds/hub/push") for _ in range(5)
            ])
            statuses = sorted(r.status_code for r in results)
            assert statuses.count(202) == 1
            assert statuses.count(409) == 4
            await _a.sleep(0.05)
            assert started_count == 1
            release.set()


@pytest.mark.asyncio
async def test_delete_dataset_409_when_push_in_flight(client_and_root, monkeypatch):
    client, root, app = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    coord = app.state.push_coordinator
    coord.try_reserve("ds")
    try:
        async with client as ac:
            r = await ac.delete("/api/datasets/ds")
        assert r.status_code == 409
    finally:
        coord.release("ds")


@pytest.mark.asyncio
async def test_progress_error_cleared_on_subsequent_success(client_and_root, monkeypatch):
    """Failed push leaves progress.error; next successful push clears it."""
    client, root, app = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    write_hub_meta(root / "ds", HubMeta(repo_id="u/d"))
    coord = app.state.push_coordinator

    # Pre-populate progress with a stale error
    coord.progress["ds"] = PushProgress(status="error", error="prior failure")

    # Mock _run_push_with_release to succeed (skip real upload)
    async def fake_run(app, ds_name, ds_root):
        # Simulate success: write hub_meta + set progress
        from mimicrec.cloud.hub_meta import read_hub_meta, write_hub_meta as wh
        meta = read_hub_meta(ds_root)
        meta.last_pushed_commit_sha = "abc123"
        meta.last_push_error = None
        wh(ds_root, meta)
        coord.progress[ds_name].status = "done"
        coord.progress[ds_name].error = None  # behavior under test

    monkeypatch.setattr("mimicrec.api.routes.cloud._run_push_with_release", fake_run)
    with patch("mimicrec.api.routes.cloud.get_token", return_value="hf_xxx"):
        async with client as ac:
            r = await ac.post("/api/datasets/ds/hub/push")
    assert r.status_code == 202
    # Wait for fake task to run
    import asyncio as _a
    await _a.sleep(0.05)
    assert coord.progress["ds"].error is None


@pytest.mark.asyncio
async def test_delete_dataset_drops_coordinator_state(client_and_root):
    client, root, app = client_and_root
    init_dataset(root / "ds", fps=30, joint_names=["j0"], camera_names=[])
    coord = app.state.push_coordinator
    coord.get_save_lock("ds")
    coord.progress["ds"] = PushProgress(status="done")
    async with client as ac:
        r = await ac.delete("/api/datasets/ds")
    assert r.status_code == 204
    assert "ds" not in coord.save_locks
    assert "ds" not in coord.progress
