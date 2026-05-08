from pathlib import Path
from httpx import AsyncClient, ASGITransport
from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


def _client_app():
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    return app


async def test_serial_devices_has_no_store_cache_control():
    app = _client_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/settings/devices/serial")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"


async def test_camera_devices_has_no_store_cache_control():
    app = _client_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/settings/devices/cameras")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"
