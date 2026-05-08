from __future__ import annotations
from enum import Enum

from mimicrec.gopro.types import NATIVE_PRESETS, NativePreset


class AspectMatch(Enum):
    MATCH = "match"           # native aspect == target aspect (within tolerance)
    MISMATCH = "mismatch"     # need crop or stretch


_ASPECT_TOL = 0.01


def _aspect(w: int, h: int) -> float:
    return w / h


def pick_preset(width: int, height: int, fps: int, aspect_mode: str) -> tuple[NativePreset, AspectMatch]:
    """Spec の Resolution selection ロジックを実装。aspect 一致 preset を優先。"""
    if aspect_mode not in ("crop", "stretch"):
        raise ValueError(f"unknown aspect_mode: {aspect_mode!r}")

    target_aspect = _aspect(width, height)

    # candidates that satisfy size + fps
    candidates = [
        p for p in NATIVE_PRESETS
        if p.width >= width and p.height >= height and p.fps == fps
    ]
    if not candidates:
        # find what's wrong
        if not any(p.fps == fps for p in NATIVE_PRESETS):
            raise ValueError(f"GoPro Hero 11 does not support fps={fps}")
        raise ValueError(
            f"target {width}x{height}@{fps} exceeds Hero 11 native presets "
            f"(max width={max(p.width for p in NATIVE_PRESETS)})"
        )

    # aspect-matching first
    aspect_matches = [
        p for p in candidates
        if abs(_aspect(p.width, p.height) - target_aspect) <= _ASPECT_TOL
    ]
    if aspect_matches:
        # pick smallest by area
        chosen = min(aspect_matches, key=lambda p: p.width * p.height)
        return chosen, AspectMatch.MATCH

    # no aspect match — fall back to smallest 16:9 (or any) native
    chosen = min(candidates, key=lambda p: p.width * p.height)
    return chosen, AspectMatch.MISMATCH
