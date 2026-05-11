import time

import pytest

from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.gopro.registry import GoProDeviceRegistry
from mimicrec.recording.dataset_layout import dataset_paths
from mimicrec.util.error_bus import ErrorBus


@pytest.fixture
def paths(tmp_path):
    p = dataset_paths(tmp_path / "ds")
    for d in (p.meta_dir, p.pending_dir, p.videos_dir):
        d.mkdir(parents=True, exist_ok=True)
    return p


@pytest.mark.asyncio
async def test_registry_preview_disabled_yields_empty_sources(paths):
    a = MockGoProDevice(name="g1", usb_serial="S1")
    reg = GoProDeviceRegistry(
        devices=[(a.name, a)], paths=paths, errors=ErrorBus(), preview_enabled=False,
    )
    await reg.start()
    try:
        assert reg.preview_sources() == {}, "no preview sources when disabled"
        assert "g1" in reg.gopro_specs(), "gopro_specs unchanged so info.json schema works"
    finally:
        await reg.stop()


@pytest.mark.asyncio
async def test_registry_preview_disabled_does_not_call_start_preview(paths):
    a = MockGoProDevice(name="g1", usb_serial="S1")
    calls: list[int] = []
    real_start = a.start_preview

    async def spy_start(port: int) -> None:
        calls.append(port)
        await real_start(port)

    a.start_preview = spy_start  # type: ignore[assignment]

    reg = GoProDeviceRegistry(
        devices=[(a.name, a)], paths=paths, errors=ErrorBus(), preview_enabled=False,
    )
    await reg.start()
    try:
        assert calls == [], "start_preview must not be invoked when preview disabled"
    finally:
        await reg.stop()


@pytest.mark.asyncio
async def test_registry_default_preview_enabled_is_true(paths):
    """Existing behavior: preview_enabled defaults to True and sources are populated."""
    a = MockGoProDevice(name="g1", usb_serial="S1")
    reg = GoProDeviceRegistry(devices=[(a.name, a)], paths=paths, errors=ErrorBus())
    await reg.start()
    try:
        assert "g1" in reg.preview_sources()
    finally:
        await reg.stop()


@pytest.mark.asyncio
async def test_registry_preview_disabled_episode_lifecycle_still_works(paths):
    """episode_start and episode_stop complete without errors when preview is disabled.

    Spec item (d): the recording path (shutter_on/off via GoProRecorder) is
    independent of the preview pipeline; disabling preview must not break it.
    """
    a = MockGoProDevice(name="g1", usb_serial="S1")
    errs = ErrorBus()
    sub = errs.subscribe()
    reg = GoProDeviceRegistry(
        devices=[(a.name, a)], paths=paths, errors=errs, preview_enabled=False,
    )
    await reg.start()
    try:
        await reg.episode_start(0, t_host_mono_ns=time.monotonic_ns())
        await reg.episode_stop(0)
        # No hardware errors should have been emitted by start/stop.
        errors_seen: list = []
        while not sub.empty():
            errors_seen.append(sub.get_nowait())
        assert errors_seen == [], f"Unexpected errors during episode lifecycle: {errors_seen}"
    finally:
        await reg.stop()
