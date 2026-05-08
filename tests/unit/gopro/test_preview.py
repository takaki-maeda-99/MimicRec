import asyncio

import numpy as np
import pytest

from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.gopro.preview import GoProPreviewSource


@pytest.mark.asyncio
async def test_push_for_test_emits_preview_only_frame():
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    src = GoProPreviewSource(d, udp_port=18556)
    img = np.zeros((48, 64, 3), dtype=np.uint8)
    await src._push_frame_for_test(img)
    f = await asyncio.wait_for(src.read(), timeout=1.0)
    assert f.preview_only is True
    assert f.image.shape == (48, 64, 3)


@pytest.mark.asyncio
async def test_disabled_device_read_blocks_cleanly():
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    d.disable("test")
    src = GoProPreviewSource(d, udp_port=18557)
    await src.connect()  # no-op when disabled
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(src.read(), timeout=0.3)
