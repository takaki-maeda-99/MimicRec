from __future__ import annotations
from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport

from mimicrec.api.app import create_app
from mimicrec.cloud.push_state import PushCoordinator


@pytest.fixture
def client_and_app(tmp_path):
    app = create_app()
    app.state.datasets_root = tmp_path
    app.state.push_coordinator = PushCoordinator()
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    return client, app


@pytest.mark.asyncio
async def test_auth_status_env_locked_false_when_no_env_var(client_and_app, monkeypatch):
    """env_locked must be in the response and false when neither env var is set."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    client, _ = client_and_app
    with patch("mimicrec.api.routes.cloud.get_token", return_value=None), \
         patch("mimicrec.api.routes.cloud.HfApi"):
        async with client as ac:
            r = await ac.get("/api/cloud/auth-status")
    assert r.status_code == 200
    body = r.json()
    assert body["env_locked"] is False
    assert body["authenticated"] is False


@pytest.mark.asyncio
async def test_auth_status_env_locked_true_when_hf_token_set(client_and_app, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "envtok")
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    client, _ = client_and_app
    with patch("mimicrec.api.routes.cloud.get_token", return_value="envtok"), \
         patch("mimicrec.api.routes.cloud.HfApi") as MockApi:
        MockApi.return_value.whoami.return_value = {"name": "alice"}
        async with client as ac:
            r = await ac.get("/api/cloud/auth-status")
    assert r.status_code == 200
    assert r.json()["env_locked"] is True


@pytest.mark.asyncio
async def test_auth_status_env_locked_true_with_legacy_var(client_and_app, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "envtok")
    client, _ = client_and_app
    with patch("mimicrec.api.routes.cloud.get_token", return_value="envtok"), \
         patch("mimicrec.api.routes.cloud.HfApi") as MockApi:
        MockApi.return_value.whoami.return_value = {"name": "alice"}
        async with client as ac:
            r = await ac.get("/api/cloud/auth-status")
    assert r.json()["env_locked"] is True


@pytest.mark.asyncio
async def test_auth_status_env_locked_false_when_whitespace_env(client_and_app, monkeypatch):
    """Whitespace-only env var must NOT be treated as set."""
    monkeypatch.setenv("HF_TOKEN", "   ")
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    client, _ = client_and_app
    with patch("mimicrec.api.routes.cloud.get_token", return_value=None), \
         patch("mimicrec.api.routes.cloud.HfApi"):
        async with client as ac:
            r = await ac.get("/api/cloud/auth-status")
    assert r.json()["env_locked"] is False
