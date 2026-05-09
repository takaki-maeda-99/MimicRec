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
        """Runs in worker thread. Pushes decoded frames to self._latest via the loop.

        The GoPro takes a few seconds to start emitting MPEG-TS packets after
        ``set_preview_stream(ENABLE)`` returns ok, and on USB hot-plug the
        first attempt sometimes drops before any packet arrives. We retry the
        open a few times so a single slow start doesn't permanently break
        the preview source for the rest of the session.

        Diagnostic milestones (open / first packet / first frame / first
        push) are logged at WARNING level on purpose: this is a one-shot
        bring-up sequence and we want them visible regardless of the host's
        log threshold so a failure mode like "stream opens but no packets"
        is bisectable from a single ``journalctl`` view.
        """
        import time
        import av
        # Match the SDK demo's options: bigger fifo so a slow consumer doesn't
        # drop packets, and overrun_nonfatal so the demuxer keeps going on
        # transient overflow instead of erroring out.
        url = (
            f"udp://0.0.0.0:{self._port}"
            f"?fifo_size=50000000&overrun_nonfatal=1"
        )
        # Per-attempt open timeout (seconds). The previous 5-second budget was
        # tight enough that a slow first packet from the GoPro tripped pyav's
        # interrupt callback and the decode thread exited before the camera
        # ever sent anything.
        open_timeout_s = 15
        max_attempts = 4
        first_packet_logged = False
        first_frame_logged = False
        first_push_logged = False
        for attempt in range(1, max_attempts + 1):
            if self._stop_event.is_set():
                return
            try:
                log.warning("preview opening %s (attempt %d/%d) for %s",
                            url, attempt, max_attempts, self._device.name)
                with av.open(url, mode="r", timeout=open_timeout_s) as ctx:
                    log.warning("preview stream opened for %s; demuxing video stream",
                                self._device.name)
                    for packet in ctx.demux(video=0):
                        if self._stop_event.is_set():
                            return
                        if not first_packet_logged:
                            log.warning("preview first packet demuxed for %s",
                                        self._device.name)
                            first_packet_logged = True
                        for av_frame in packet.decode():
                            if self._stop_event.is_set():
                                return
                            if not first_frame_logged:
                                log.warning("preview first frame decoded for %s on udp:%d",
                                            self._device.name, self._port)
                                first_frame_logged = True
                            img = av_frame.to_ndarray(format="bgr24")
                            if self._loop is not None:
                                fut = asyncio.run_coroutine_threadsafe(
                                    self._push(img), self._loop,
                                )
                                if not first_push_logged:
                                    try:
                                        fut.result(timeout=2.0)
                                    except Exception as e:
                                        log.warning(
                                            "preview first push for %s failed: %s",
                                            self._device.name, e,
                                        )
                                    else:
                                        log.warning(
                                            "preview first push reached event loop for %s",
                                            self._device.name,
                                        )
                                    first_push_logged = True
                # demux returned without a stop_event — treat as remote closed
                # and try to reconnect (camera may have hiccuped mid-stream).
                log.warning("preview demux ended for %s; reopening", self._device.name)
            except Exception as e:
                if first_frame_logged or attempt == max_attempts:
                    log.warning(
                        "preview decode loop ended for %s after %d attempt(s): %s",
                        self._device.name, attempt, e,
                    )
                    return
                log.warning(
                    "preview open attempt %d/%d for %s timed out (%s); retrying",
                    attempt, max_attempts, self._device.name, e,
                )
                time.sleep(1.0)

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
