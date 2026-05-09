from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mimicrec.errors import HardwareError
from mimicrec.gopro.types import GoProSpec


@pytest.mark.asyncio
async def test_unsupported_fps_raises_at_init():
    from mimicrec.gopro.device import GoProDevice
    with pytest.raises(ValueError):
        GoProDevice(name="g1", usb_serial="S1", width=1920, height=1080, fps=25)


@pytest.mark.asyncio
async def test_get_spec_returns_yaml_target():
    from mimicrec.gopro.device import GoProDevice
    d = GoProDevice(name="g1", usb_serial="S1", width=1280, height=720, fps=30)
    s = d.get_spec()
    assert s == GoProSpec(name="g1", width=1280, height=720, fps=30, codec="libx264")


def test_udp_preview_port_defaults_to_8554():
    """HERO9–11 firmware ignores the port arg and forces 8554. The default
    must therefore be 8554 — the OpenGoPro spec's canonical port — so the
    out-of-the-box single-camera HERO11 case works without yaml tweaks."""
    from mimicrec.gopro.device import GoProDevice
    d = GoProDevice(name="g1", usb_serial="S1", width=1280, height=720, fps=30)
    assert d.udp_preview_port == 8554


def test_udp_preview_port_yaml_override():
    """HERO12/13 multi-camera setups need to pick a non-default port per
    device to avoid two listeners colliding on the same UDP socket."""
    from mimicrec.gopro.device import GoProDevice
    d = GoProDevice(
        name="g1", usb_serial="S1", width=1280, height=720, fps=30,
        udp_preview_port=18557,
    )
    assert d.udp_preview_port == 18557


def _build_fake_gopro_ctx():
    """Reusable mock that satisfies GoProDevice.connect()/disconnect()."""
    fake_client = MagicMock()
    fake_client.is_open = True
    fake_client.http_command = MagicMock()
    fake_client.http_command.set_date_time = AsyncMock(return_value=MagicMock(ok=True))
    fake_client.http_command.load_preset_group = AsyncMock(return_value=MagicMock(ok=True))
    fake_client.http_command.load_preset = AsyncMock(return_value=MagicMock(ok=True))
    fake_client.http_command.get_camera_state = AsyncMock(
        # Phase 0 confirmed: state.data is dict-of-status-id-string-keys.
        # Key "54" is SD remaining IN KB (not bytes).
        return_value=MagicMock(ok=True, data={"54": 25_000_000})
    )
    fake_client.http_setting = MagicMock()
    fake_client.http_setting.max_lens = MagicMock()
    fake_client.http_setting.max_lens.set = AsyncMock(return_value=MagicMock(ok=True))
    fake_client.http_setting.max_lens_mod_enable = MagicMock()
    fake_client.http_setting.max_lens_mod_enable.set = AsyncMock(return_value=MagicMock(ok=True))
    fake_client.http_setting.max_lens_mod = MagicMock()
    fake_client.http_setting.max_lens_mod.set = AsyncMock(return_value=MagicMock(ok=True))
    fake_client.http_setting.video_lens = MagicMock()
    fake_client.http_setting.video_lens.set = AsyncMock(return_value=MagicMock(ok=True))
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_client)
    fake_ctx.__aexit__ = AsyncMock(return_value=False)
    return fake_ctx, fake_client


@pytest.mark.asyncio
async def test_connect_calls_required_apis_in_order():
    from mimicrec.gopro.device import GoProDevice
    fake_ctx, fake_client = _build_fake_gopro_ctx()

    with patch("mimicrec.gopro.device.WiredGoPro", return_value=fake_ctx):
        d = GoProDevice(name="g1", usb_serial="S1", width=1920, height=1080, fps=30)
        await d.connect()
        fake_client.http_command.set_date_time.assert_awaited()
        fake_client.http_command.load_preset_group.assert_awaited()
        fake_client.http_command.load_preset.assert_awaited()
        # Without max_lens, NEITHER api's settings must be touched — the
        # camera otherwise reports the standard lens as a Max Lens Mod 1.0.
        fake_client.http_setting.max_lens.set.assert_not_awaited()
        fake_client.http_setting.max_lens_mod_enable.set.assert_not_awaited()
        fake_client.http_setting.max_lens_mod.set.assert_not_awaited()
        fake_client.http_setting.video_lens.set.assert_not_awaited()
        await d.disconnect()


@pytest.mark.asyncio
async def test_max_lens_block_invalid_mod_raises_at_init():
    from mimicrec.gopro.device import GoProDevice
    with pytest.raises(ValueError, match="max_lens.mod"):
        GoProDevice(
            name="g1", usb_serial="S1", width=1280, height=720, fps=30,
            max_lens={"mod": "max_lens_99"},
        )


@pytest.mark.asyncio
async def test_max_lens_block_invalid_fov_raises_at_init():
    from mimicrec.gopro.device import GoProDevice
    with pytest.raises(ValueError, match="max_lens.fov"):
        GoProDevice(
            name="g1", usb_serial="S1", width=1280, height=720, fps=30,
            max_lens={"mod": "max_lens_1_0", "fov": "ultra_wide"},
        )


@pytest.mark.asyncio
async def test_connect_applies_max_lens_legacy_for_hero11_mod_1_0():
    """HERO11 + Max Lens 1.0 + MAX SuperView: HERO9–11 reject setting 190 with
    403 Forbidden, so we must use the legacy on/off setting 162 (`MAX_LENS`)
    plus VIDEO_LENS for the FOV. The granular 189/190 pair must NOT be
    touched on these models."""
    from mimicrec.gopro.device import GoProDevice
    from open_gopro.models.constants import settings as gp_settings

    fake_ctx, fake_client = _build_fake_gopro_ctx()

    with patch("mimicrec.gopro.device.WiredGoPro", return_value=fake_ctx):
        d = GoProDevice(
            name="g1", usb_serial="S1", width=1280, height=720, fps=30,
            max_lens={"mod": "max_lens_1_0", "fov": "max_superview"},
        )
        await d.connect()
        fake_client.http_setting.max_lens.set.assert_awaited_once_with(
            gp_settings.MaxLens.ON,
        )
        fake_client.http_setting.max_lens_mod_enable.set.assert_not_awaited()
        fake_client.http_setting.max_lens_mod.set.assert_not_awaited()
        fake_client.http_setting.video_lens.set.assert_awaited_once_with(
            gp_settings.VideoLens.MAX_SUPERVIEW,
        )
        await d.disconnect()


@pytest.mark.asyncio
async def test_connect_applies_max_lens_modern_for_mod_2_0():
    """HERO12/13 + Max Lens 2.0 → use settings 189+190 because the camera
    needs to disambiguate between Mod 1.0 / 2.0 / 2.5 / Macro / etc., which
    the legacy on/off setting 162 cannot express. enable BEFORE mod ID."""
    from mimicrec.gopro.device import GoProDevice
    from open_gopro.models.constants import settings as gp_settings

    fake_ctx, fake_client = _build_fake_gopro_ctx()

    with patch("mimicrec.gopro.device.WiredGoPro", return_value=fake_ctx):
        d = GoProDevice(
            name="g1", usb_serial="S1", width=1280, height=720, fps=30,
            max_lens={"mod": "max_lens_2_0", "fov": "max_superview"},
        )
        await d.connect()
        fake_client.http_setting.max_lens.set.assert_not_awaited()
        fake_client.http_setting.max_lens_mod_enable.set.assert_awaited_once_with(
            gp_settings.MaxLensModEnable.ON,
        )
        fake_client.http_setting.max_lens_mod.set.assert_awaited_once_with(
            gp_settings.MaxLensMod.MAX_LENS_2_0,
        )
        fake_client.http_setting.video_lens.set.assert_awaited_once_with(
            gp_settings.VideoLens.MAX_SUPERVIEW,
        )
        await d.disconnect()


@pytest.mark.asyncio
async def test_connect_skips_video_lens_when_fov_omitted():
    """fov is optional — keep the preset's lens mode if the operator only
    wants to declare the mod attachment without overriding FOV."""
    from mimicrec.gopro.device import GoProDevice

    fake_ctx, fake_client = _build_fake_gopro_ctx()

    with patch("mimicrec.gopro.device.WiredGoPro", return_value=fake_ctx):
        d = GoProDevice(
            name="g1", usb_serial="S1", width=1280, height=720, fps=30,
            max_lens={"mod": "max_lens_1_0"},
        )
        await d.connect()
        fake_client.http_setting.max_lens.set.assert_awaited_once()
        fake_client.http_setting.video_lens.set.assert_not_awaited()
        await d.disconnect()
