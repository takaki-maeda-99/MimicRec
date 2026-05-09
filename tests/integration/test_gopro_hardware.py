import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.gopro_hardware


@pytest.mark.asyncio
async def test_three_episodes_with_real_gopro(tmp_path: Path):
    """Manual prerequisites:
    - Hero 11 plugged in via USB and powered on
    - GOPRO_SERIAL env var set (or default to known serial from Phase 0)
    - cdc_ncm + avahi-daemon running on host
    """
    serial = os.environ.get("GOPRO_SERIAL", "C3471327153141")

    from mimicrec.gopro.device import GoProDevice
    from mimicrec.gopro.registry import GoProDeviceRegistry
    from mimicrec.recording.dataset_layout import dataset_paths
    from mimicrec.util.error_bus import ErrorBus

    paths = dataset_paths(tmp_path / "ds")
    for d in (paths.meta_dir, paths.pending_dir, paths.videos_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Pre-seed info.json so update_info_json_codec can patch it.
    (paths.meta_dir / "info.json").write_text(json.dumps({
        "features": {"observation.images.g_test": {"info": {"video.codec": "libx264"}}},
    }))

    dev = GoProDevice(name="g_test", usb_serial=serial,
                     width=1280, height=720, fps=30, aspect_mode="crop")
    reg = GoProDeviceRegistry(devices=[dev], paths=paths, errors=ErrorBus())
    await reg.start()
    try:
        for ep in range(3):
            await reg.episode_start(ep, t_host_mono_ns=0)
            await asyncio.sleep(2.0)
            await reg.episode_stop(ep)
            # Drive the registry's commit so DLWorker promotes staged → dataset.
            await reg.commit_episode(ep)
    finally:
        # Wait for DLWorker to drain
        for _ in range(120):
            if reg.pending_count == 0:
                break
            await asyncio.sleep(1.0)
        await reg.stop()

    # Verify all 3 MP4s
    for ep in range(3):
        mp4 = paths.episode_video(0, "g_test", ep)
        assert mp4.exists(), f"missing {mp4}"
        # Confirm downscale: 1280x720
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(mp4)],
            text=True,
        ).strip()
        assert out == "1280,720", f"resolution mismatch in {mp4.name}: {out}"
        # GPMF preserved
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "default=nk=1", str(mp4)],
            text=True,
        )
        assert "GoPro MET" in out, f"GPMF lost in {mp4}"

    # info.json codec patched (h264 from libx264 re-encode)
    info = json.loads((paths.meta_dir / "info.json").read_text())
    codec = info["features"]["observation.images.g_test"]["info"]["video.codec"]
    assert codec in {"h264", "hevc"}, f"unexpected codec: {codec}"
