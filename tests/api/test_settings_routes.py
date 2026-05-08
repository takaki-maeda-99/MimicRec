from httpx import AsyncClient, ASGITransport


async def test_serial_devices_has_no_store_cache_control(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/settings/devices/serial")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"


async def test_camera_devices_has_no_store_cache_control(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/settings/devices/cameras")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"


async def test_list_group_configs_has_no_store_cache_control(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/settings/configs/cameras")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"


async def test_get_config_has_no_store_cache_control(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/settings/configs/cameras/mock_cam")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"


async def test_list_calibrations_has_no_store_cache_control(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/settings/calibration")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"
