from __future__ import annotations
import asyncio
import json
import os
import re
from pathlib import Path

from mimicrec.errors import HardwareError
from mimicrec.recording.dataset_layout import DatasetPaths


_CHAPTER_RE = re.compile(r"^G(?P<q>[A-Z])(?P<ch>\d{2})(?P<id>\d{4})\.MP4$", re.IGNORECASE)


def parse_chapter_filename(filename: str) -> tuple[str, int, str]:
    """Return (quality_letter, chapter_number, episode_id_4digit).
    Raises ValueError if filename does not match GoPro's G<q><ch><id>.MP4 format."""
    m = _CHAPTER_RE.match(filename)
    if not m:
        raise ValueError(f"not a GoPro chapter filename: {filename!r}")
    return m.group("q").upper(), int(m.group("ch")), m.group("id")


async def _run_ffmpeg(cmd: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = stderr.decode(errors="replace")[-2000:] if stderr else "(no stderr)"
        raise HardwareError(f"ffmpeg failed (rc={proc.returncode}): {msg}")


async def ffmpeg_copy(src: Path, dst: Path) -> None:
    """Stream copy video + GPMF only (drop TCD + audio).

    Phase 0 verification confirmed: -map 0 -c copy -copy_unknown FAILS on
    Hero 11 because the TCD timecode track has codec=none which ffmpeg
    cannot remux. Use explicit per-stream map. Stream index 0:d:1 is the
    GPMF data stream (handler="GoPro MET") on Hero 11."""
    cmd = [
        "ffmpeg", "-y", "-nostdin", "-i", str(src),
        "-map", "0:v:0", "-map", "0:d:1",
        "-c", "copy",
        str(dst),
    ]
    await _run_ffmpeg(cmd)


async def ffmpeg_downscale(
    src: Path, dst: Path,
    target_w: int, target_h: int,
    aspect_mode: str,
    aspect_match: bool,
) -> None:
    """Re-encode video with libx264 + scale; copy GPMF data stream.
    Drops TCD timecode and audio. aspect_match=True → simple scale;
    False → crop or stretch per aspect_mode."""
    if aspect_match:
        vf = f"scale={target_w}:{target_h}"
    elif aspect_mode == "crop":
        vf = (
            f"scale={target_w}:{target_h}"
            f":force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h}"
        )
    elif aspect_mode == "stretch":
        vf = f"scale={target_w}:{target_h}"
    else:
        raise ValueError(f"unknown aspect_mode: {aspect_mode!r}")

    cmd = [
        "ffmpeg", "-y", "-nostdin", "-i", str(src),
        "-map", "0:v:0", "-map", "0:d:1",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-vf", vf,
        "-c:d", "copy",
        str(dst),
    ]
    await _run_ffmpeg(cmd)


async def update_info_json_codec(paths: DatasetPaths, cam_name: str) -> None:
    """Read first available episode video for cam_name, ffprobe codec,
    update info.json features placeholder. Idempotent."""
    cam_dir = paths.videos_dir / f"observation.images.{cam_name}"
    if not cam_dir.exists():
        return
    sample = next(iter(sorted(cam_dir.rglob("episode_*.mp4"))), None)
    if sample is None:
        return

    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(sample),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return
    codec = stdout.decode().strip()

    info_path = paths.meta_dir / "info.json"
    if not info_path.exists():
        return
    info = json.loads(info_path.read_text())
    key = f"observation.images.{cam_name}"
    if key not in info.get("features", {}):
        return
    if info["features"][key]["info"].get("video.codec") == codec:
        return

    info["features"][key]["info"]["video.codec"] = codec
    tmp = info_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(info, indent=2))
    os.replace(str(tmp), str(info_path))
