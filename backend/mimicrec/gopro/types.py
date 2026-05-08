from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class GoProSpec:
    """info.json features 用 (YAML target = downscale 後の値)。"""
    name: str
    width: int
    height: int
    fps: int
    codec: str   # init_dataset では "libx264" placeholder, DLWorker が ffprobe で更新


@dataclass
class MediaItem:
    """One file on the GoPro SD card."""
    filename: str            # "GX010001.MP4"
    size: int                # bytes
    mtime_ns: int            # camera-clock nanoseconds


@dataclass(frozen=True)
class NativePreset:
    """GoPro 内部 preset エントリ（Phase 0 verification で確定）。"""
    name: str            # human readable
    sdk_id: int          # open_gopro の preset ID
    width: int
    height: int
    fps: int
    native_codec: str    # "h264" or "h265"
    chapter_seconds: int


# Phase 0 verification で実機 enum したエントリで置換する。
# 現状はスペックの「出発セット」をそのまま。Phase 0 完了で書き換え。
NATIVE_PRESETS: list[NativePreset] = [
    # 16:9
    NativePreset("1080p_30_wide",  sdk_id=1,  width=1920, height=1080, fps=30,  native_codec="h264", chapter_seconds=24 * 60),
    NativePreset("1080p_60_wide",  sdk_id=2,  width=1920, height=1080, fps=60,  native_codec="h264", chapter_seconds=12 * 60),
    NativePreset("1080p_120_wide", sdk_id=3,  width=1920, height=1080, fps=120, native_codec="h264", chapter_seconds=6 * 60),
    NativePreset("2.7K_60_wide",   sdk_id=4,  width=2704, height=1520, fps=60,  native_codec="h264", chapter_seconds=8 * 60),
    NativePreset("2.7K_120_wide",  sdk_id=5,  width=2704, height=1520, fps=120, native_codec="h264", chapter_seconds=4 * 60),
    NativePreset("4K_30_wide",     sdk_id=6,  width=3840, height=2160, fps=30,  native_codec="h265", chapter_seconds=7 * 60),
    NativePreset("4K_60_wide",     sdk_id=7,  width=3840, height=2160, fps=60,  native_codec="h265", chapter_seconds=4 * 60),
    NativePreset("5.3K_30_wide",   sdk_id=8,  width=5312, height=2988, fps=30,  native_codec="h265", chapter_seconds=5 * 60),
    NativePreset("5.3K_60_wide",   sdk_id=9,  width=5312, height=2988, fps=60,  native_codec="h265", chapter_seconds=3 * 60),
    # 4:3
    NativePreset("2.7K_4_3_60",    sdk_id=10, width=2704, height=2028, fps=60,  native_codec="h264", chapter_seconds=8 * 60),
    NativePreset("4K_4_3_30",      sdk_id=11, width=4000, height=3000, fps=30,  native_codec="h265", chapter_seconds=6 * 60),
    NativePreset("5K_4_3_30",      sdk_id=12, width=5312, height=3984, fps=30,  native_codec="h265", chapter_seconds=4 * 60),
    # 8:7
    NativePreset("4K_8_7_30",      sdk_id=13, width=3840, height=3360, fps=30,  native_codec="h265", chapter_seconds=5 * 60),
    NativePreset("5.3K_8_7_30",    sdk_id=14, width=5312, height=4648, fps=30,  native_codec="h265", chapter_seconds=4 * 60),
]
