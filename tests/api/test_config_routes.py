from pathlib import Path
from httpx import AsyncClient, ASGITransport
from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


async def test_list_robot_configs():
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/configs/robot")
    assert r.status_code == 200
    assert "mock" in r.json()


async def test_list_cameras_configs():
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/configs/cameras")
    assert r.status_code == 200
    assert "mock_cam" in r.json()


async def test_unknown_config_group_returns_404():
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/configs/nonexistent")
    assert r.status_code == 404
