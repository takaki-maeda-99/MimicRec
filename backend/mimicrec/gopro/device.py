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
    from open_gopro.models.constants import settings as _gp_settings  # type: ignore
except Exception:
    WiredGoPro = None  # type: ignore[assignment]
    constants = None   # type: ignore[assignment]
    proto = None       # type: ignore[assignment]
    _gp_settings = None  # type: ignore[assignment]


# Phase 0 confirmed: SD remaining is at state.data["54"] in KB.
_STORAGE_MIN_KB = 500_000   # 500 MB ≈ 500_000 KB


_MAX_LENS_MOD_VALUES = {
    "none": "NONE",
    "max_lens_1_0": "MAX_LENS_1_0",
    "max_lens_2_0": "MAX_LENS_2_0",
    "max_lens_2_5": "MAX_LENS_2_5",
    "macro": "MACRO",
    "anamorphic": "ANAMORPHIC",
    "nd_4": "ND_4", "nd_8": "ND_8", "nd_16": "ND_16", "nd_32": "ND_32",
    "standard_lens": "STANDARD_LENS",
    "auto_detect": "AUTO_DETECT",
}

_VIDEO_LENS_VALUES = {
    "max_superview": "MAX_SUPERVIEW",
    "linear_horizon_leveling": "LINEAR_HORIZON_LEVELING",
    "linear_horizon_lock": "LINEAR_HORIZON_LOCK",
    "max_hyperview": "MAX_HYPERVIEW",
}


# HERO9–11 only expose the legacy on/off setting 162 (`MAX_LENS`); they
# return 403 Forbidden for the granular 189/190 pair introduced for Max Lens
# Mod 2.0 on HERO12/13. We pick the right API automatically from the mod
# value so the operator doesn't have to know which firmware uses which.
_LEGACY_API_MODS = {"max_lens_1_0", "none"}


def _resolve_max_lens(cfg: dict | None) -> tuple[object, object | None, str]:
    """Validate the optional ``max_lens`` block from a GoPro yaml.

    Returns ``(mod_enum, fov_enum_or_None, api_kind)`` where ``api_kind`` is
    ``"legacy"`` (setting 162) or ``"modern"`` (settings 189+190). Returns
    ``(None, None, "legacy")`` when the block is omitted. Validation runs
    at construction time so a typo in yaml fails fast (before the camera
    is even connected) instead of surfacing as an opaque HardwareError
    mid-session.
    """
    if cfg is None:
        return (None, None, "legacy")
    if _gp_settings is None:
        raise ValueError("max_lens configured but open_gopro is not installed")
    mod_key = str(cfg.get("mod", "")).lower()
    if mod_key not in _MAX_LENS_MOD_VALUES:
        raise ValueError(
            f"max_lens.mod={cfg.get('mod')!r} is invalid; "
            f"expected one of {sorted(_MAX_LENS_MOD_VALUES)}"
        )
    mod_enum = getattr(_gp_settings.MaxLensMod, _MAX_LENS_MOD_VALUES[mod_key])

    fov_enum = None
    fov_key = cfg.get("fov")
    if fov_key is not None:
        fov_key = str(fov_key).lower()
        if fov_key not in _VIDEO_LENS_VALUES:
            raise ValueError(
                f"max_lens.fov={cfg.get('fov')!r} is invalid; "
                f"expected one of {sorted(_VIDEO_LENS_VALUES)}"
            )
        fov_enum = getattr(_gp_settings.VideoLens, _VIDEO_LENS_VALUES[fov_key])
    api_kind = "legacy" if mod_key in _LEGACY_API_MODS else "modern"
    return (mod_enum, fov_enum, api_kind)


class GoProDevice:
    def __init__(
        self,
        name: str,
        usb_serial: str,
        width: int,
        height: int,
        fps: int,
        aspect_mode: str = "crop",
        max_lens: dict | None = None,
        udp_preview_port: int = 8554,
    ) -> None:
        self._preset, self._aspect_match = pick_preset(width, height, fps, aspect_mode)
        self._name = name
        self._serial = usb_serial
        self._target_w = width
        self._target_h = height
        self._target_fps = fps
        self._aspect_mode = aspect_mode
        self._max_lens_mod, self._max_lens_fov, self._max_lens_api = _resolve_max_lens(max_lens)
        # HERO9–11 firmware ignores the ``port`` argument to
        # ``set_preview_stream`` and always emits to UDP 8554. HERO12/13
        # respect the port argument. Defaulting to the OpenGoPro spec's
        # canonical port (8554) makes the single-camera HERO11 case work
        # out of the box; multi-camera HERO12+ setups should override per
        # device in yaml.
        self._udp_preview_port = int(udp_preview_port)
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
    @property
    def udp_preview_port(self) -> int: return self._udp_preview_port

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
        if self._max_lens_mod is not None:
            if self._max_lens_api == "legacy":
                # HERO9–11 expose only setting 162 (a simple on/off). The
                # specific mod variant is implicit (only 1.0 exists for these
                # cameras), so we don't need to declare it separately.
                await self._must_ok(
                    self._client.http_setting.max_lens.set(_gp_settings.MaxLens.ON),
                    "max_lens on (legacy 162)",
                )
            else:
                # HERO12/13 require the granular 189/190 pair. Enable BEFORE
                # declaring which mod is attached, otherwise the camera
                # rejects the mod ID with "lens mod disabled".
                await self._must_ok(
                    self._client.http_setting.max_lens_mod_enable.set(
                        _gp_settings.MaxLensModEnable.ON),
                    "max_lens_mod_enable on",
                )
                await self._must_ok(
                    self._client.http_setting.max_lens_mod.set(self._max_lens_mod),
                    f"max_lens_mod {self._max_lens_mod.name}",
                )
            if self._max_lens_fov is not None:
                await self._must_ok(
                    self._client.http_setting.video_lens.set(self._max_lens_fov),
                    f"video_lens {self._max_lens_fov.name}",
                )
        state = await self._must_ok(
            self._client.http_command.get_camera_state(), "get_camera_state",
        )
        # state.data is keyed by StatusId enum. SD_CARD_REMAINING (54) = KB remaining.
        # Fall back to integer key 54 for forward-compat if SDK changes key type.
        from open_gopro.models.constants import StatusId  # type: ignore
        remaining_kb = int(
            state.data.get(StatusId.SD_CARD_REMAINING,
                           state.data.get(54, state.data.get("54", 0)))
        )
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
            # open_gopro MediaItem has no top-level 'size'; use lrv/low_res as proxy or 0.
            size = int(
                getattr(f, "size", None)
                or getattr(f, "low_res_video_size", None)
                or getattr(f, "lrv_file_size", None)
                or 0
            )
            out.append(MediaItem(filename=f.filename, size=size, mtime_ns=mtime_ns))
        return out

    async def start_preview(self, port: int) -> None:
        if self._disabled or self._client is None: return
        # Mirror open_gopro.features.streaming.preview_stream's pre-flight:
        # if a previous session left the preview stream running (or a stale
        # one on a different port), the camera silently keeps it on the
        # OLD port and the new ENABLE returns ok without actually emitting
        # anything to the new port. A leading DISABLE makes ENABLE
        # idempotent. Suppress errors — if it wasn't running, that's fine.
        try:
            await self._client.http_command.set_preview_stream(
                mode=constants.Toggle.DISABLE)
        except Exception as e:
            log.debug("preview pre-flight DISABLE failed (ignored): %s", e)
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
        from open_gopro.models.constants import StatusId  # type: ignore
        kb = int(r.data.get(StatusId.SD_CARD_REMAINING,
                            r.data.get(54, r.data.get("54", 0))))
        return kb * 1024   # KB → bytes

    def disable(self, reason: str) -> None:
        if self._disabled: return
        self._disabled = True
        log.warning("GoProDevice %s disabled: %s", self._name, reason)

    async def _must_ok(self, awaitable, what: str):
        r = await awaitable
        if not getattr(r, "ok", True):
            raise HardwareError(f"GoPro {self._name} {what} failed: {r}")
        return r
