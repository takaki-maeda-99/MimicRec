import pytest

from mimicrec.gopro.types import GoProSpec, MediaItem, NativePreset, NATIVE_PRESETS


def test_gopro_spec_frozen():
    s = GoProSpec(name="g1", width=1920, height=1080, fps=60, codec="libx264")
    with pytest.raises(Exception):
        s.width = 1280  # type: ignore[misc]


def test_media_item_fields():
    m = MediaItem(filename="GX010001.MP4", size=12345, mtime_ns=1_700_000_000_000_000_000)
    assert m.filename == "GX010001.MP4"
    assert m.size == 12345
    assert m.mtime_ns == 1_700_000_000_000_000_000


def test_native_preset_fields():
    p = NativePreset(
        name="1080p_30_wide", sdk_id=1, width=1920, height=1080,
        fps=30, native_codec="h264", chapter_seconds=24 * 60,
    )
    assert p.width == 1920
    assert p.chapter_seconds == 1440


def test_native_presets_table_includes_basics():
    names = {p.name for p in NATIVE_PRESETS}
    assert "1080p_30_wide" in names
    assert "1080p_60_wide" in names
