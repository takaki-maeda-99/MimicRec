from __future__ import annotations
import asyncio
import time
from typing import Mapping

from mimicrec.cameras.preview import downscale, encode_jpeg
from mimicrec.errors import HardwareError
from mimicrec.types import Frame
from mimicrec.util.error_bus import ErrorBus
from mimicrec.util.latest_value import LatestValue


class CameraManager:
    def __init__(self, cameras: Mapping[str, object], error_bus: ErrorBus) -> None:
        self._cameras = dict(cameras)
        self._errors = error_bus
        self._latest: dict[str, LatestValue[Frame]] = {n: LatestValue() for n in cameras}
        self._preview_subs: dict[str, list[asyncio.Queue]] = {n: [] for n in cameras}
        self._tasks: list[asyncio.Task] = []
        self._stopped = asyncio.Event()

    def latest(self, name: str) -> LatestValue[Frame]:
        return self._latest[name]

    def subscribe_preview(self, name: str, maxsize: int = 2) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._preview_subs[name].append(q)
        return q

    async def start(self) -> None:
        for name, cam in self._cameras.items():
            self._tasks.append(asyncio.create_task(self._run_camera(name, cam)))

    async def stop(self) -> None:
        self._stopped.set()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        # Release underlying device handles (e.g. cv2.VideoCapture) so the next
        # session can re-open the camera. Task cancellation alone does not free
        # the OS-level handle.
        for name, cam in self._cameras.items():
            if hasattr(cam, "disconnect"):
                try:
                    await cam.disconnect()
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(
                        "camera %s disconnect failed: %s", name, e,
                    )

    async def _run_camera(self, name: str, cam) -> None:
        # Connect camera if it has a connect method (OpenCVCamera needs it, MockCamera doesn't)
        if hasattr(cam, "connect"):
            try:
                await cam.connect()
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"camera {name} connect failed: {e}")
                return  # Don't publish to ErrorBus — failed camera shouldn't kill the session
        while not self._stopped.is_set():
            try:
                frame = await cam.read()
            except Exception as e:
                await self._errors.publish(HardwareError(f"camera {name}: {e}"))
                await asyncio.sleep(0.05)
                continue
            stamped_ns = time.monotonic_ns()
            frame.t_mono_ns = stamped_ns
            self._latest[name].set(frame, t_mono_ns=stamped_ns)
            jpg: bytes | None = None
            for q in list(self._preview_subs[name]):
                if q.full():
                    continue
                if jpg is None:
                    jpg = encode_jpeg(downscale(frame.image))
                try:
                    q.put_nowait(jpg)
                except asyncio.QueueFull:
                    pass
