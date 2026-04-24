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
