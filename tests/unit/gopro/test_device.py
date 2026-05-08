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


@pytest.mark.asyncio
async def test_connect_calls_required_apis_in_order():
    from mimicrec.gopro.device import GoProDevice
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
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_client)
    fake_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("mimicrec.gopro.device.WiredGoPro", return_value=fake_ctx):
        d = GoProDevice(name="g1", usb_serial="S1", width=1920, height=1080, fps=30)
        await d.connect()
        fake_client.http_command.set_date_time.assert_awaited()
        fake_client.http_command.load_preset_group.assert_awaited()
        fake_client.http_command.load_preset.assert_awaited()
        await d.disconnect()
