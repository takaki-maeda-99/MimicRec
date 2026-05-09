from __future__ import annotations
import asyncio
import shutil
from pathlib import Path

from mimicrec.gopro.preset_picker import pick_preset, AspectMatch
from mimicrec.gopro.types import GoProSpec, MediaItem, NativePreset


class MockGoProDevice:
    """SDK を import せずに動く。"""

    def __init__(
        self,
        name: str,
        usb_serial: str,
        width: int = 1920,
        height: int = 1080,
        fps: int = 30,
        aspect_mode: str = "crop",
        fixture_mp4: Path | str | None = None,
        emit_preview: bool = False,
        storage_remaining: int = 1_000_000_000,
        chapters_per_episode: int = 1,
        udp_preview_port: int = 8554,
    ) -> None:
        # Validate via picker (raises if (w,h,fps) impossible).
        self._preset, self._aspect_match = pick_preset(width, height, fps, aspect_mode)

        self._name = name
        self._serial = usb_serial
        self._target_w = width
        self._target_h = height
        self._target_fps = fps
        self._aspect_mode = aspect_mode
        self._fixture = Path(fixture_mp4) if fixture_mp4 is not None else None
        self._emit_preview = emit_preview
        self._storage = storage_remaining
        self._chapters_per_episode = max(1, chapters_per_episode)

        self._udp_preview_port = int(udp_preview_port)
        self._connected = False
        self._disabled = False
        self._files: list[MediaItem] = []
        self._next_id = 1

    @property
    def name(self) -> str: return self._name
    @property
    def usb_serial(self) -> str: return self._serial
    @property
    def is_disabled(self) -> bool: return self._disabled
    @property
    def selected_preset(self) -> NativePreset: return self._preset
    @property
    def aspect_mode(self) -> str: return self._aspect_mode
    @property
    def udp_preview_port(self) -> int: return self._udp_preview_port

    def get_spec(self) -> GoProSpec:
        return GoProSpec(
            name=self._name,
            width=self._target_w, height=self._target_h, fps=self._target_fps,
            codec="libx264",
        )

    async def connect(self) -> None:
        if self._connected: return
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def shutter_on(self) -> None:
        if self._disabled or not self._connected: return

    async def shutter_off(self) -> None:
        if self._disabled or not self._connected: return
        # Generate `chapters_per_episode` files sharing same id, differing chapter.
        ep_id = f"{self._next_id:04d}"
        self._next_id += 1
        for ch in range(1, self._chapters_per_episode + 1):
            fn = f"GX{ch:02d}{ep_id}.MP4"
            self._files.append(MediaItem(filename=fn, size=12345, mtime_ns=0))

    async def media_list(self) -> list[MediaItem]:
        if self._disabled or not self._connected: return []
        return list(self._files)

    async def start_preview(self, port: int) -> None:
        pass

    async def stop_preview(self) -> None:
        pass

    async def download_file(self, sd_filename: str, dest: Path) -> None:
        if self._fixture is not None and self._fixture.exists():
            shutil.copy(str(self._fixture), str(dest))
        else:
            dest.write_bytes(b"\x00" * 1024)

    async def get_storage_remaining(self) -> int:
        return self._storage

    def disable(self, reason: str) -> None:
        if self._disabled: return
        self._disabled = True
        import logging
        logging.getLogger(__name__).warning("MockGoProDevice %s disabled: %s", self._name, reason)
