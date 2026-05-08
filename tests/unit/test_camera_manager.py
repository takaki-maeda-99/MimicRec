import asyncio
import pytest

from mimicrec.cameras.manager import CameraManager
from mimicrec.cameras.mock_camera import MockCamera
from mimicrec.errors import HardwareError
from mimicrec.util.error_bus import ErrorBus


async def test_manager_fans_out_frames_to_preview_subscriber():
    cm = CameraManager(cameras={"front": MockCamera("front")}, error_bus=ErrorBus())
    preview_q = cm.subscribe_preview("front")
    await cm.start()
    frame = await asyncio.wait_for(preview_q.get(), timeout=1.0)
    assert isinstance(frame, (bytes, bytearray))
    await cm.stop()


async def test_manager_slow_preview_does_not_block_recording():
    cm = CameraManager(cameras={"front": MockCamera("front")}, error_bus=ErrorBus())
    await cm.start()

    for _ in range(10):
        s = cm.latest("front").peek()
        if s is not None:
            break
        await asyncio.sleep(0.05)
    assert cm.latest("front").peek() is not None
    await cm.stop()


async def test_manager_surfaces_drop_as_hardware_error():
    cam = MockCamera("front")
    cam.drop_next = 1
    bus = ErrorBus()
    sub = bus.subscribe()
    cm = CameraManager(cameras={"front": cam}, error_bus=bus)
    await cm.start()
    evt = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert isinstance(evt, HardwareError)
    await cm.stop()


async def test_manager_start_aborts_when_a_camera_connect_fails():
    """If any camera's connect() raises, manager.start() must propagate the
    error and disconnect previously-connected cameras."""

    class FakeCam:
        def __init__(self, name, fail=False):
            self.name = name
            self.fail = fail
            self.connected = False
            self.disconnected = False

        async def connect(self):
            if self.fail:
                raise RuntimeError(f"{self.name} connect failed")
            self.connected = True

        async def disconnect(self):
            self.disconnected = True

        async def read(self):
            await asyncio.sleep(3600)
            raise AssertionError

    cam_a = FakeCam("a", fail=False)
    cam_b = FakeCam("b", fail=True)
    cam_c = FakeCam("c", fail=False)

    cm = CameraManager(cameras={"a": cam_a, "b": cam_b, "c": cam_c}, error_bus=ErrorBus())

    with pytest.raises(RuntimeError, match="b connect failed"):
        await cm.start()

    assert cam_a.disconnected, "previously-connected camera should be disconnected on rollback"
    assert not cam_c.connected, "later cameras should not be attempted after a failure"
    assert cm._tasks == [], "no read tasks should be spawned when start() aborts"
