from __future__ import annotations
import asyncio
import logging
import threading
from typing import Optional

import numpy as np

from mimicrec.types import Frame

log = logging.getLogger(__name__)


class GoProPreviewSource:
    """Camera I/F view over UDP MPEG-TS preview. Decode runs in a worker thread."""

    def __init__(self, device, udp_port: int) -> None:
        self._device = device
        self._port = udp_port
        self._latest: asyncio.Queue[Frame] = asyncio.Queue(maxsize=1)
        self._never: asyncio.Event = asyncio.Event()
        self._decode_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._connected = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def name(self) -> str: return self._device.name

    async def connect(self) -> None:
        if getattr(self._device, "is_disabled", False):
            return
        try:
            await self._device.start_preview(self._port)
        except Exception as e:
            log.warning("start_preview failed for %s: %s", self._device.name, e)
            return
        self._loop = asyncio.get_running_loop()
        self._stop_event.clear()
        self._decode_thread = threading.Thread(
            target=self._decode_loop_sync, name=f"gopro-preview-{self._device.name}", daemon=True,
        )
        self._decode_thread.start()
        self._connected = True

    async def disconnect(self) -> None:
        self._stop_event.set()
        try:
            await self._device.stop_preview()
        except Exception as e:
            log.warning("stop_preview failed for %s: %s", self._device.name, e)
        if self._decode_thread is not None:
            self._decode_thread.join(timeout=2.0)
            self._decode_thread = None
        self._connected = False

    async def read(self) -> Frame:
        if getattr(self._device, "is_disabled", False) or not self._connected:
            await self._never.wait()
        return await self._latest.get()

    def _decode_loop_sync(self) -> None:
        """Runs in worker thread. Pushes decoded frames to self._latest via the loop."""
        import av
        url = f"udp://0.0.0.0:{self._port}?fifo_size=50000&overrun_nonfatal=1"
        try:
            with av.open(url, mode="r", timeout=5) as ctx:
                for packet in ctx.demux(video=0):
                    if self._stop_event.is_set():
                        break
                    for av_frame in packet.decode():
                        if self._stop_event.is_set():
                            break
                        img = av_frame.to_ndarray(format="bgr24")
                        if self._loop is not None:
                            asyncio.run_coroutine_threadsafe(
                                self._push(img), self._loop,
                            )
        except Exception as e:
            log.warning("preview decode loop ended for %s: %s", self._device.name, e)

    async def _push(self, img: "np.ndarray") -> None:
        f = Frame(image=img, preview_only=True)
        try:
            self._latest.put_nowait(f)
        except asyncio.QueueFull:
            try: self._latest.get_nowait()
            except asyncio.QueueEmpty: pass
            self._latest.put_nowait(f)

    async def _push_frame_for_test(self, image: np.ndarray) -> None:
        """Test hook bypassing UDP/pyav."""
        await self._push(image)
        self._connected = True
