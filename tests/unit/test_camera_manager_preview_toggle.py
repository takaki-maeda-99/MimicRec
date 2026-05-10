import asyncio
import pytest

from mimicrec.cameras.manager import CameraManager
from mimicrec.cameras.mock_camera import MockCamera
from mimicrec.errors import PreviewDisabledError
from mimicrec.util.error_bus import ErrorBus


async def test_subscribe_preview_raises_when_disabled():
    cm = CameraManager(
        cameras={"front": MockCamera("front")},
        error_bus=ErrorBus(),
        preview_enabled=False,
    )
    with pytest.raises(PreviewDisabledError):
        cm.subscribe_preview("front")


async def test_disabled_preview_skips_jpeg_fanout_but_keeps_latest():
    cm = CameraManager(
        cameras={"front": MockCamera("front")},
        error_bus=ErrorBus(),
        preview_enabled=False,
    )

    encode_calls = 0
    import mimicrec.cameras.manager as mgr_mod
    real_encode = mgr_mod.encode_jpeg

    def spy_encode(img):
        nonlocal encode_calls
        encode_calls += 1
        return real_encode(img)

    mgr_mod.encode_jpeg = spy_encode  # type: ignore[assignment]
    try:
        await cm.start()
        # Wait for the read loop to populate latest at least once.
        for _ in range(20):
            if cm.latest("front").peek() is not None:
                break
            await asyncio.sleep(0.05)
        assert cm.latest("front").peek() is not None, "read loop must still populate latest"
        assert encode_calls == 0, "encode_jpeg must not be called when preview disabled"
    finally:
        mgr_mod.encode_jpeg = real_encode  # type: ignore[assignment]
        await cm.stop()


async def test_default_preview_enabled_is_true():
    cm = CameraManager(
        cameras={"front": MockCamera("front")},
        error_bus=ErrorBus(),
    )
    # Default-on path: subscribe_preview must work and return a queue.
    q = cm.subscribe_preview("front")
    assert isinstance(q, asyncio.Queue)
