from __future__ import annotations
import asyncio
import cv2

from mimicrec.types import Frame


def decode_fourcc(v: int) -> str:
    """Decode the 4-byte little-endian fourcc int returned by cv2 into a 4-char string."""
    return bytes(
        [v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF]
    ).decode("ascii", errors="replace")


class OpenCVCamera:
    def __init__(
        self,
        name: str,
        device_id: int = 0,
        width: int = 640,
        height: int = 480,
        pixel_format: str | None = None,
        capture_fps: int | None = None,
    ):
        self.name = name
        self._device_id = device_id
        self._width = width
        self._height = height
        self._pixel_format = pixel_format
        self._capture_fps = capture_fps
        self._cap = None

    def _open(self):
        # Use device path for reliability (index-based open fails on some V4L2 drivers)
        path = f"/dev/video{self._device_id}"
        self._cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
        if not self._cap.isOpened():
            # Fallback to index
            self._cap = cv2.VideoCapture(self._device_id)
        if not self._cap.isOpened():
            raise RuntimeError(f"cannot open camera {self._device_id} ({path})")

        # V4L2 typical property order: fourcc -> width/height -> fps.
        # Setting in reverse can cause silent driver-side fallbacks.
        if self._pixel_format is not None:
            self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self._pixel_format))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        if self._capture_fps is not None:
            self._cap.set(cv2.CAP_PROP_FPS, self._capture_fps)

        # Strict readback: cv2.VideoCapture.set() returns True even when the
        # driver clamps to a different format/size/fps. We compare what we
        # asked for to what the driver actually negotiated and raise on
        # mismatch. Skip the comparison for fields the user did not specify.
        actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fourcc = decode_fourcc(int(self._cap.get(cv2.CAP_PROP_FOURCC)))
        # Round nominal frame rates: drivers report 29.97 when sensors run at
        # NTSC rates; rounding to 30 matches what users typically request.
        actual_fps = int(round(self._cap.get(cv2.CAP_PROP_FPS)))

        mismatches: list[str] = []
        if actual_w != self._width or actual_h != self._height:
            mismatches.append(
                f"size: requested {self._width}x{self._height}, got {actual_w}x{actual_h}"
            )
        if self._pixel_format is not None and actual_fourcc != self._pixel_format:
            mismatches.append(
                f"fourcc: requested {self._pixel_format}, got {actual_fourcc!r}"
            )
        if self._capture_fps is not None and actual_fps != self._capture_fps:
            mismatches.append(
                f"fps: requested {self._capture_fps}, got {actual_fps}"
            )

        if mismatches:
            self._cap.release()
            self._cap = None
            raise RuntimeError(
                f"camera {self.name}: cv2 negotiated different parameters: "
                + "; ".join(mismatches)
            )

    def _close(self):
        if self._cap:
            self._cap.release()
            self._cap = None

    async def connect(self):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._open)

    async def disconnect(self):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._close)

    async def read(self) -> Frame:
        loop = asyncio.get_running_loop()
        ret, frame = await loop.run_in_executor(None, self._cap.read)
        if not ret or frame is None:
            raise TimeoutError(f"camera {self.name} read failed")
        return Frame(image=frame)
