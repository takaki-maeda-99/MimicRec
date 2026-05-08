from __future__ import annotations
import logging
from datetime import datetime
from pathlib import Path

from mimicrec.errors import HardwareError
from mimicrec.gopro.preset_picker import pick_preset
from mimicrec.gopro.types import GoProSpec, MediaItem, NativePreset

log = logging.getLogger(__name__)

try:
    from open_gopro import WiredGoPro                # type: ignore
    from open_gopro.models import constants, proto   # type: ignore
except Exception:
    WiredGoPro = None  # type: ignore[assignment]
    constants = None   # type: ignore[assignment]
    proto = None       # type: ignore[assignment]


# Phase 0 confirmed: SD remaining is at state.data["54"] in KB.
_STORAGE_MIN_KB = 500_000   # 500 MB ≈ 500_000 KB


class GoProDevice:
    def __init__(
        self,
        name: str,
        usb_serial: str,
        width: int,
        height: int,
        fps: int,
        aspect_mode: str = "crop",
    ) -> None:
        self._preset, self._aspect_match = pick_preset(width, height, fps, aspect_mode)
        self._name = name
        self._serial = usb_serial
        self._target_w = width
        self._target_h = height
        self._target_fps = fps
        self._aspect_mode = aspect_mode
        self._client_ctx = None
        self._client = None
        self._disabled = False

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

    def get_spec(self) -> GoProSpec:
        return GoProSpec(
            name=self._name,
            width=self._target_w, height=self._target_h, fps=self._target_fps,
            codec="libx264",
        )

    async def connect(self) -> None:
        if self._client is not None: return
        if WiredGoPro is None:
            raise HardwareError("open_gopro is not installed")
        # NOTE: WiredGoPro's exact init kwarg name depends on open_gopro version.
        # Phase 0 verification establishes whether it's `target=` or `serial=`.
        # If neither works without args, omit (open_gopro auto-discovers a single GoPro).
        try:
            self._client_ctx = WiredGoPro()
            self._client = await self._client_ctx.__aenter__()
        except Exception as e:
            self._client_ctx = None
            raise HardwareError(f"WiredGoPro init failed: {e}") from e

        await self._must_ok(
            self._client.http_command.set_date_time(date_time=datetime.now()),
            "set_date_time",
        )
        await self._must_ok(
            self._client.http_command.load_preset_group(
                group=proto.EnumPresetGroup.PRESET_GROUP_ID_VIDEO),
            "load_preset_group video",
        )
        await self._must_ok(
            self._client.http_command.load_preset(preset=self._preset.sdk_id),
            f"load_preset {self._preset.name}",
        )
        state = await self._must_ok(
            self._client.http_command.get_camera_state(), "get_camera_state",
        )
        # state.data is keyed by Status ID string. "54" = SD remaining in KB.
        remaining_kb = int(state.data.get("54", 0))
        if remaining_kb < _STORAGE_MIN_KB:
            raise HardwareError(
                f"GoPro {self._name} storage too low: {remaining_kb} KB remaining")

    async def disconnect(self) -> None:
        if self._client_ctx is None: return
        try:
            await self._client_ctx.__aexit__(None, None, None)
        except Exception as e:
            log.warning("GoPro %s disconnect failed: %s", self._name, e)
        self._client = None
        self._client_ctx = None

    async def shutter_on(self) -> None:
        if self._disabled or self._client is None: return
        await self._must_ok(
            self._client.http_command.set_shutter(shutter=constants.Toggle.ENABLE),
            "set_shutter on",
        )

    async def shutter_off(self) -> None:
        if self._disabled or self._client is None: return
        await self._must_ok(
            self._client.http_command.set_shutter(shutter=constants.Toggle.DISABLE),
            "set_shutter off",
        )

    async def media_list(self) -> list[MediaItem]:
        if self._disabled or self._client is None: return []
        r = await self._must_ok(self._client.http_command.get_media_list(), "get_media_list")
        out: list[MediaItem] = []
        for f in r.data.files:
            mtime_ns = int(getattr(f, "creation_timestamp", 0)) * 1_000_000_000
            out.append(MediaItem(filename=f.filename, size=int(f.size), mtime_ns=mtime_ns))
        return out

    async def start_preview(self, port: int) -> None:
        if self._disabled or self._client is None: return
        await self._must_ok(
            self._client.http_command.set_preview_stream(
                mode=constants.Toggle.ENABLE, port=port),
            "set_preview_stream on",
        )

    async def stop_preview(self) -> None:
        if self._disabled or self._client is None: return
        await self._must_ok(
            self._client.http_command.set_preview_stream(mode=constants.Toggle.DISABLE),
            "set_preview_stream off",
        )

    async def download_file(self, sd_filename: str, dest: Path) -> None:
        if self._disabled or self._client is None: return
        await self._must_ok(
            self._client.http_command.download_file(camera_file=sd_filename, local_file=dest),
            f"download_file {sd_filename}",
        )

    async def get_storage_remaining(self) -> int:
        if self._disabled or self._client is None: return 0
        r = await self._must_ok(self._client.http_command.get_camera_state(), "get_camera_state")
        return int(r.data.get("54", 0)) * 1024   # KB → bytes

    def disable(self, reason: str) -> None:
        if self._disabled: return
        self._disabled = True
        log.warning("GoProDevice %s disabled: %s", self._name, reason)

    async def _must_ok(self, awaitable, what: str):
        r = await awaitable
        if not getattr(r, "ok", True):
            raise HardwareError(f"GoPro {self._name} {what} failed: {r}")
        return r
