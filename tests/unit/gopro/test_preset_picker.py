import pytest

from mimicrec.gopro.preset_picker import pick_preset, AspectMatch
from mimicrec.gopro.types import NATIVE_PRESETS


def test_exact_native_match_no_aspect_concern():
    p, am = pick_preset(width=1920, height=1080, fps=30, aspect_mode="crop")
    assert p.name == "1080p_30_wide"
    assert am == AspectMatch.MATCH


def test_smaller_target_uses_smallest_native_with_matching_fps():
    p, am = pick_preset(width=1280, height=720, fps=30, aspect_mode="crop")
    # 1280x720 is 16:9, smallest 16:9 native at fps=30 is 1080p_30_wide
    assert p.name == "1080p_30_wide"
    assert am == AspectMatch.MATCH   # both 16:9


def test_43_target_prefers_43_native():
    # 640x480 is 4:3. should prefer a 4:3 native.
    p, am = pick_preset(width=640, height=480, fps=30, aspect_mode="crop")
    assert (p.width / p.height) == pytest.approx(4 / 3, rel=0.02)
    assert am == AspectMatch.MATCH


def test_43_target_falls_back_to_169_when_no_43_at_fps():
    # 4:3 + fps=120 — Hero 11 has no 4:3 native at 120fps.
    p, am = pick_preset(width=640, height=480, fps=120, aspect_mode="crop")
    assert p.fps == 120
    assert am == AspectMatch.MISMATCH   # source is 16:9


def test_unsupported_fps_raises_config_error():
    from mimicrec.errors import HardwareError  # ConfigError まだ無いなら HardwareError でラップ
    with pytest.raises((ValueError, HardwareError)):
        pick_preset(width=1920, height=1080, fps=25, aspect_mode="crop")


def test_target_too_large_raises_config_error():
    from mimicrec.errors import HardwareError
    with pytest.raises((ValueError, HardwareError)):
        pick_preset(width=7680, height=4320, fps=30, aspect_mode="crop")
