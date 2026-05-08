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


import asyncio
from unittest.mock import patch

from mimicrec.cameras.v4l2_caps import FormatCaps, FrameSize


async def test_camera_capabilities_returns_parsed_list(app):
    fake = [
        FormatCaps(
            fourcc="MJPG",
            description="Motion-JPEG (compressed)",
            sizes=[FrameSize(width=1280, height=720, fps=[30])],
        )
    ]
    with patch("mimicrec.api.routes.settings.glob.glob", return_value=["/dev/video0"]), \
         patch("mimicrec.api.routes.settings.enumerate_capabilities", return_value=fake):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/settings/devices/cameras/0/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body == [
        {
            "fourcc": "MJPG",
            "description": "Motion-JPEG (compressed)",
            "sizes": [{"width": 1280, "height": 720, "fps": [30]}],
        }
    ]


async def test_camera_capabilities_has_no_store_cache_control(app):
    with patch("mimicrec.api.routes.settings.glob.glob", return_value=["/dev/video0"]), \
         patch("mimicrec.api.routes.settings.enumerate_capabilities", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/settings/devices/cameras/0/capabilities")
    assert r.headers.get("cache-control") == "no-store"


async def test_camera_capabilities_returns_404_for_missing_device(app):
    with patch("mimicrec.api.routes.settings.glob.glob", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/settings/devices/cameras/99/capabilities")
    assert r.status_code == 404


async def test_camera_capabilities_empty_list_when_v4l2_ctl_unavailable(app):
    with patch("mimicrec.api.routes.settings.glob.glob", return_value=["/dev/video0"]), \
         patch("mimicrec.api.routes.settings.enumerate_capabilities", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/settings/devices/cameras/0/capabilities")
    assert r.status_code == 200
    assert r.json() == []
