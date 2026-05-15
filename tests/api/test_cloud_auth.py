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


@pytest.mark.asyncio
async def test_auth_status_env_locked_recomputed_on_each_call_despite_cache(
    client_and_app, monkeypatch
):
    """env_locked must be recomputed on every call, not served stale from the cache.

    The auth_cache TTL (60s) exists to amortize the HfApi().whoami() network call,
    but _env_token_present() is a cheap os.environ lookup. If the env var toggles
    during the cache window, the response must reflect the new value immediately.
    """
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    client, _ = client_and_app
    async with client as ac:
        # First call: no env var -> env_locked false, populates cache.
        with patch("mimicrec.api.routes.cloud.get_token", return_value=None), \
             patch("mimicrec.api.routes.cloud.HfApi"):
            r1 = await ac.get("/api/cloud/auth-status")
        assert r1.status_code == 200
        assert r1.json()["env_locked"] is False

        # Set the env var without busting the cache (no refresh=1).
        monkeypatch.setenv("HF_TOKEN", "envtok")

        # Second call within TTL: env_locked must now be true even though the
        # cached whoami value is reused.
        with patch("mimicrec.api.routes.cloud.get_token", return_value=None), \
             patch("mimicrec.api.routes.cloud.HfApi"):
            r2 = await ac.get("/api/cloud/auth-status")
        assert r2.status_code == 200
        assert r2.json()["env_locked"] is True


@pytest.mark.asyncio
async def test_login_missing_origin_returns_403(client_and_app):
    client, _ = client_and_app
    async with client as ac:
        r = await ac.post("/api/cloud/login", json={"token": "hf_xxx"})
    assert r.status_code == 403
    assert r.json()["detail"] == "origin header required"


@pytest.mark.asyncio
async def test_login_cross_origin_returns_403(client_and_app):
    client, _ = client_and_app
    async with client as ac:
        r = await ac.post(
            "/api/cloud/login",
            json={"token": "hf_xxx"},
            headers={"Origin": "http://evil.example.com"},
        )
    assert r.status_code == 403
    assert r.json()["detail"] == "cross-origin request rejected"


@pytest.mark.asyncio
async def test_login_empty_token_returns_400(client_and_app, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    client, _ = client_and_app
    async with client as ac:
        r = await ac.post(
            "/api/cloud/login",
            json={"token": ""},
            headers={"Origin": "http://test"},
        )
    # Pydantic min_length=1 → 422; the route's body strip() check is unreachable
    # if the body fails validation first, so 422 is acceptable here.
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_login_whitespace_token_returns_400(client_and_app, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    client, _ = client_and_app
    async with client as ac:
        r = await ac.post(
            "/api/cloud/login",
            json={"token": "   "},
            headers={"Origin": "http://test"},
        )
    assert r.status_code == 400
    assert r.json()["detail"] == "token is required"


@pytest.mark.asyncio
async def test_login_env_locked_returns_409(client_and_app, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "envtok")
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    client, _ = client_and_app
    with patch("mimicrec.api.routes.cloud.HfApi") as MockApi, \
         patch("mimicrec.api.routes.cloud.hf_login") as MockLogin:
        async with client as ac:
            r = await ac.post(
                "/api/cloud/login",
                json={"token": "hf_xxx"},
                headers={"Origin": "http://test"},
            )
    assert r.status_code == 409
    assert "HF_TOKEN" in r.json()["detail"]
    MockApi.return_value.whoami.assert_not_called()
    MockLogin.assert_not_called()


@pytest.mark.asyncio
async def test_login_env_locked_legacy_var_returns_409(client_and_app, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "envtok")
    client, _ = client_and_app
    with patch("mimicrec.api.routes.cloud.HfApi") as MockApi, \
         patch("mimicrec.api.routes.cloud.hf_login") as MockLogin:
        async with client as ac:
            r = await ac.post(
                "/api/cloud/login",
                json={"token": "hf_xxx"},
                headers={"Origin": "http://test"},
            )
    assert r.status_code == 409
    MockApi.return_value.whoami.assert_not_called()
    MockLogin.assert_not_called()


def _make_http_error(status_code: int):
    """Build a real HfHubHTTPError with an httpx.Response — the installed
    huggingface_hub version (0.35.x) requires `response: httpx.Response` and
    will introspect `response.request` during string formatting, so a plain
    duck-typed `_Resp` shim fails with `AttributeError`."""
    import httpx
    from huggingface_hub.errors import HfHubHTTPError

    request = httpx.Request("GET", "https://huggingface.co/api/whoami-v2")
    response = httpx.Response(status_code=status_code, request=request)
    return HfHubHTTPError("http error", response=response)


@pytest.mark.asyncio
async def test_login_invalid_token_returns_401(client_and_app, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    client, _ = client_and_app
    with patch("mimicrec.api.routes.cloud.HfApi") as MockApi, \
         patch("mimicrec.api.routes.cloud.hf_login") as MockLogin:
        MockApi.return_value.whoami.side_effect = _make_http_error(401)
        async with client as ac:
            r = await ac.post(
                "/api/cloud/login",
                json={"token": "hf_invalid"},
                headers={"Origin": "http://test"},
            )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid token"
    MockLogin.assert_not_called()


@pytest.mark.asyncio
async def test_login_403_also_returns_401(client_and_app, monkeypatch):
    """403 from whoami means the token lacks permission — surface as 'invalid token' for the UI."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    client, _ = client_and_app
    with patch("mimicrec.api.routes.cloud.HfApi") as MockApi, \
         patch("mimicrec.api.routes.cloud.hf_login"):
        MockApi.return_value.whoami.side_effect = _make_http_error(403)
        async with client as ac:
            r = await ac.post(
                "/api/cloud/login",
                json={"token": "hf_xxx"},
                headers={"Origin": "http://test"},
            )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_network_error_returns_503(client_and_app, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    client, _ = client_and_app
    with patch("mimicrec.api.routes.cloud.HfApi") as MockApi, \
         patch("mimicrec.api.routes.cloud.hf_login"):
        MockApi.return_value.whoami.side_effect = ConnectionError("dns fail")
        async with client as ac:
            r = await ac.post(
                "/api/cloud/login",
                json={"token": "hf_xxx"},
                headers={"Origin": "http://test"},
            )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_login_whoami_no_name_returns_502(client_and_app, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    client, _ = client_and_app
    with patch("mimicrec.api.routes.cloud.HfApi") as MockApi, \
         patch("mimicrec.api.routes.cloud.hf_login") as MockLogin:
        MockApi.return_value.whoami.return_value = {"orgs": []}  # no 'name'
        async with client as ac:
            r = await ac.post(
                "/api/cloud/login",
                json={"token": "hf_xxx"},
                headers={"Origin": "http://test"},
            )
    assert r.status_code == 502
    MockLogin.assert_not_called()
