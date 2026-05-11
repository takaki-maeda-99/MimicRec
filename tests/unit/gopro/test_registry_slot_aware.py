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
async def test_registry_keys_recorders_previews_specs_by_slot(paths):
    """Slot is the dict key throughout. device.name is preserved on the
    adapter for physical-ID logging but is not the registry key."""
    d = MockGoProDevice(name="gopro_external", usb_serial="S1")
    reg = GoProDeviceRegistry(
        devices=[("front", d)], paths=paths, errors=ErrorBus(),
    )
    await reg.start()
    try:
        assert "front" in reg.preview_sources()
        assert "gopro_external" not in reg.preview_sources()
        assert "front" in reg.gopro_specs()
        assert "gopro_external" not in reg.gopro_specs()
        assert "front" in reg._recorders  # type: ignore[attr-defined]
    finally:
        await reg.stop()


def test_registry_rejects_duplicate_slot(paths):
    a = MockGoProDevice(name="gopro_a", usb_serial="SA")
    b = MockGoProDevice(name="gopro_b", usb_serial="SB")
    with pytest.raises(ValueError, match="duplicate slot"):
        GoProDeviceRegistry(
            devices=[("front", a), ("front", b)],
            paths=paths, errors=ErrorBus(),
        )


def test_registry_rejects_duplicate_usb_serial_unchanged(paths):
    """Existing serial-uniqueness check still fires."""
    a = MockGoProDevice(name="ga", usb_serial="S1")
    b = MockGoProDevice(name="gb", usb_serial="S1")
    with pytest.raises(ValueError, match="duplicate usb_serial"):
        GoProDeviceRegistry(
            devices=[("front", a), ("wrist", b)],
            paths=paths, errors=ErrorBus(),
        )
