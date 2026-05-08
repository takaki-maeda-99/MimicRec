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


async def test_put_camera_config_validates_and_writes(app, tmp_path):
    cameras_dir = tmp_path / "cameras"
    cameras_dir.mkdir()
    (cameras_dir / "wrist.yaml").write_text(
        "_target_: mimicrec.cameras.opencv_camera.OpenCVCamera\n"
        "name: wrist\n"
        "device_id: 0\n"
        "width: 640\n"
        "height: 480\n"
    )
    app.state.configs_root = tmp_path

    class FakeCap:
        def isOpened(self):
            return True
        def get(self, prop):
            import cv2
            mapping = {
                cv2.CAP_PROP_FRAME_WIDTH: 1280,
                cv2.CAP_PROP_FRAME_HEIGHT: 720,
                cv2.CAP_PROP_FOURCC: int.from_bytes(b"MJPG", "little"),
                cv2.CAP_PROP_FPS: 30,
            }
            return mapping[prop]
        def set(self, *_):
            return True
        def release(self):
            pass

    with patch("mimicrec.api.routes.settings.cv2.VideoCapture", return_value=FakeCap()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.put(
                "/api/settings/configs/cameras/wrist",
                json={"content": {
                    "_target_": "mimicrec.cameras.opencv_camera.OpenCVCamera",
                    "name": "wrist",
                    "device_id": 0,
                    "width": 1280,
                    "height": 720,
                    "pixel_format": "MJPG",
                    "capture_fps": 30,
                }},
            )
    assert r.status_code == 200
    written = (cameras_dir / "wrist.yaml").read_text()
    assert "MJPG" in written
    assert "capture_fps: 30" in written


async def test_put_camera_config_returns_409_on_mismatch(app, tmp_path):
    cameras_dir = tmp_path / "cameras"
    cameras_dir.mkdir()
    (cameras_dir / "wrist.yaml").write_text(
        "_target_: mimicrec.cameras.opencv_camera.OpenCVCamera\n"
        "name: wrist\n"
        "device_id: 0\n"
        "width: 640\n"
        "height: 480\n"
    )
    app.state.configs_root = tmp_path

    class FakeCap:
        def isOpened(self):
            return True
        def get(self, prop):
            import cv2
            mapping = {
                cv2.CAP_PROP_FRAME_WIDTH: 640,
                cv2.CAP_PROP_FRAME_HEIGHT: 480,
                cv2.CAP_PROP_FOURCC: int.from_bytes(b"YUYV", "little"),
                cv2.CAP_PROP_FPS: 10,
            }
            return mapping[prop]
        def set(self, *_):
            return True
        def release(self):
            pass

    with patch("mimicrec.api.routes.settings.cv2.VideoCapture", return_value=FakeCap()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.put(
                "/api/settings/configs/cameras/wrist",
                json={"content": {
                    "_target_": "mimicrec.cameras.opencv_camera.OpenCVCamera",
                    "name": "wrist",
                    "device_id": 0,
                    "width": 1920,
                    "height": 1080,
                    "pixel_format": "MJPG",
                    "capture_fps": 30,
                }},
            )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "MJPG" in detail and "YUYV" in detail
    assert "1920" not in (cameras_dir / "wrist.yaml").read_text()


async def test_put_camera_config_skips_validation_when_busy(app, tmp_path):
    cameras_dir = tmp_path / "cameras"
    cameras_dir.mkdir()
    (cameras_dir / "wrist.yaml").write_text(
        "_target_: mimicrec.cameras.opencv_camera.OpenCVCamera\n"
        "name: wrist\n"
        "device_id: 0\n"
        "width: 640\n"
        "height: 480\n"
    )
    app.state.configs_root = tmp_path

    class BusyCap:
        def isOpened(self):
            return False
        def release(self):
            pass

    with patch("mimicrec.api.routes.settings.cv2.VideoCapture", return_value=BusyCap()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.put(
                "/api/settings/configs/cameras/wrist",
                json={"content": {
                    "_target_": "mimicrec.cameras.opencv_camera.OpenCVCamera",
                    "name": "wrist",
                    "device_id": 0,
                    "width": 1920,
                    "height": 1080,
                    "pixel_format": "MJPG",
                    "capture_fps": 30,
                }},
            )
    assert r.status_code == 200
    assert r.headers.get("X-Validation-Skipped") == "device-busy"
    assert "1920" in (cameras_dir / "wrist.yaml").read_text()


async def test_put_non_camera_config_skips_validation(app, tmp_path):
    robot_dir = tmp_path / "robot"
    robot_dir.mkdir()
    (robot_dir / "mock.yaml").write_text("_target_: mimicrec.adapters.mock_robot.MockRobotAdapter\ndof: 6\n")
    app.state.configs_root = tmp_path

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.put(
            "/api/settings/configs/robot/mock",
            json={"content": {
                "_target_": "mimicrec.adapters.mock_robot.MockRobotAdapter",
                "dof": 7,
            }},
        )
    assert r.status_code == 200
    assert "dof: 7" in (robot_dir / "mock.yaml").read_text()
