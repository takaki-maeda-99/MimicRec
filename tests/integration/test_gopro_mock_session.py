"""End-to-end integration test: full GoPro recording session via MockGoProDevice.

No real GoPro hardware required. The fixture MP4 at
tests/fixtures/gopro/sample_episode.mp4 is used as the download payload.

Topology:
  FastAPI app (ASGI test client)
    └─ session/start  → mock robot + mock teleop + MockGoProDevice (mock_gopro.yaml)
    └─ 3× episode_start / episode_stop / episode_save
    └─ poll gopro_pending until 0
    └─ session/end
  DLWorker runs in-process, drains the queue during polling.

Assertions:
  1. episode_video(0, 'mock_gopro', i) exists for i in {0, 1, 2}
  2. info.json features['observation.images.mock_gopro'].info['has_gpmf'] is True
  3. info.json features['observation.images.mock_gopro'].info['video.codec'] is
     one of {"h264", "hevc", "libx264"} — the ffmpeg/ffprobe pass may update it
     from the init-time placeholder.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_MP4 = REPO_ROOT / "tests" / "fixtures" / "gopro" / "sample_episode.mp4"


@pytest.mark.asyncio
async def test_three_episodes_with_mock_gopro(tmp_path: Path):
    """End-to-end smoke test: 3 episodes recorded via the mock,
    DLWorker drains, registry.commit_episode moves to dataset, info.json updated."""
    pytest.importorskip("av")

    if not FIXTURE_MP4.exists():
        pytest.skip(f"fixture MP4 not found: {FIXTURE_MP4}")

    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir(parents=True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:

        # ── 1. Start session ──────────────────────────────────────────────────
        r = await ac.post("/api/session/start", json={
            "mode": "teleop",
            "dataset": "mock_ds",
            "task": "pick_block",
            "robot": "mock",
            "teleop": "mock_leader",
            "mapper": "identity",
            "cameras": [],
            "fps": 30,
            "gopros": ["mock_gopro"],
        })
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "ready"
        # GoPros declared at session start must round-trip through
        # /session/state so the frontend can render preview tiles for them.
        assert r.json()["gopros"] == ["mock_gopro"]

        # ── 2. Three episode cycles ───────────────────────────────────────────
        for ep_i in range(3):
            r = await ac.post("/api/episode/start")
            assert r.status_code == 200, f"ep {ep_i} start: {r.text}"
            assert r.json()["state"] == "recording"

            await asyncio.sleep(0.15)  # let a few frames accumulate

            r = await ac.post("/api/episode/stop")
            assert r.status_code == 200, f"ep {ep_i} stop: {r.text}"
            assert r.json()["state"] == "review"

            r = await ac.post("/api/episode/save", json={"success": True, "comment": f"ep{ep_i}"})
            assert r.status_code == 200, f"ep {ep_i} save: {r.text}"
            assert r.json()["state"] == "ready"

        # ── 3. Poll gopro_pending until 0 (DLWorker drains) ──────────────────
        deadline = 30.0  # generous for slow CI
        interval = 0.25
        elapsed = 0.0
        while elapsed < deadline:
            r = await ac.get("/api/session/gopro_pending")
            assert r.status_code == 200
            pending = r.json()["pending"]
            if pending == 0:
                break
            await asyncio.sleep(interval)
            elapsed += interval
        else:
            # Timed out — still show the pending count for diagnosis.
            pytest.fail(
                f"gopro_pending did not reach 0 within {deadline}s "
                f"(last value: {pending})"
            )

        # ── 4. End session ────────────────────────────────────────────────────
        r = await ac.post("/api/session/end")
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "idle"

    # ── 5. Assert episode video files exist ───────────────────────────────────
    from mimicrec.recording.dataset_layout import dataset_paths
    paths = dataset_paths(tmp_path / "datasets" / "mock_ds")
    for ep_i in range(3):
        vid = paths.episode_video(0, "mock_gopro", ep_i)
        assert vid.exists(), f"expected episode video missing: {vid}"

    # ── 6. Assert info.json GoPro feature block ───────────────────────────────
    info = json.loads((paths.meta_dir / "info.json").read_text())
    key = "observation.images.mock_gopro"
    assert key in info["features"], f"{key!r} not in info.json features"
    feat_info = info["features"][key]["info"]

    assert feat_info.get("has_gpmf") is True, (
        f"has_gpmf should be True in info.json, got: {feat_info}"
    )

    # ── 7. Assert codec is plausible ──────────────────────────────────────────
    codec = feat_info.get("video.codec", "")
    valid_codecs = {"h264", "hevc", "libx264"}
    assert codec in valid_codecs, (
        f"video.codec should be one of {valid_codecs}, got: {codec!r}"
    )
