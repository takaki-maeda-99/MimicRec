import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from mimicrec.gopro.ffmpeg_pass import (
    ffmpeg_copy, ffmpeg_downscale, update_info_json_codec, parse_chapter_filename,
)
from mimicrec.recording.dataset_layout import dataset_paths


FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "gopro" / "sample_episode.mp4"


def _has_gpmf(p: Path) -> bool:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(p)],
        text=True,
    )
    return "GoPro MET" in out or "gpmd" in out


@pytest.mark.asyncio
async def test_ffmpeg_copy_produces_output(tmp_path):
    out = tmp_path / "out.mp4"
    await ffmpeg_copy(FIXTURE, out)
    assert out.exists() and out.stat().st_size > 100


@pytest.mark.asyncio
async def test_ffmpeg_copy_preserves_gpmf_if_present(tmp_path):
    if not _has_gpmf(FIXTURE):
        pytest.skip("fixture lacks GPMF — needs real Hero 11 sample")
    out = tmp_path / "out.mp4"
    await ffmpeg_copy(FIXTURE, out)
    assert _has_gpmf(out)


@pytest.mark.asyncio
async def test_ffmpeg_downscale_to_smaller_resolution(tmp_path):
    out = tmp_path / "out.mp4"
    await ffmpeg_downscale(FIXTURE, out, target_w=32, target_h=24, aspect_mode="crop", aspect_match=True)
    info = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,codec_name", "-of", "csv=p=0", str(out)],
        text=True,
    ).strip()
    parts = info.split(",")
    assert parts[0] == "h264"  # libx264 reports as h264
    assert parts[1] == "32"
    assert parts[2] == "24"


@pytest.mark.asyncio
async def test_update_info_json_codec_updates_placeholder(tmp_path):
    paths = dataset_paths(tmp_path / "ds")
    paths.meta_dir.mkdir(parents=True)
    paths.videos_dir.mkdir(parents=True)
    cam_dir = paths.videos_dir / "observation.images.gp" / "chunk-000"
    cam_dir.mkdir(parents=True)
    # Place an MP4 there
    sample = cam_dir / "episode_000000.mp4"
    sample.write_bytes(FIXTURE.read_bytes())

    info = {
        "features": {
            "observation.images.gp": {
                "info": {"video.codec": "libx264"},
            },
        },
    }
    (paths.meta_dir / "info.json").write_text(json.dumps(info))

    await update_info_json_codec(paths, "gp")
    after = json.loads((paths.meta_dir / "info.json").read_text())
    new_codec = after["features"]["observation.images.gp"]["info"]["video.codec"]
    assert new_codec in {"h264", "hevc"}   # depending on fixture


def test_parse_chapter_filename_normal():
    q, ch, eid = parse_chapter_filename("GH010001.MP4")
    assert q == "H" and ch == 1 and eid == "0001"


def test_parse_chapter_filename_chapter_03():
    q, ch, eid = parse_chapter_filename("GX030042.MP4")
    assert q == "X" and ch == 3 and eid == "0042"


def test_parse_chapter_filename_invalid_raises():
    with pytest.raises(ValueError):
        parse_chapter_filename("foo.bar")
