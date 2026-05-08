from __future__ import annotations
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport

from mimicrec.api.app import create_app
from mimicrec.cloud.hub_meta import HubMeta, write_hub_meta, hub_meta_path
from mimicrec.cloud.push_state import PushCoordinator
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
