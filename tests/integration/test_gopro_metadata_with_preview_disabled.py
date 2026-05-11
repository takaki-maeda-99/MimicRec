"""Regression: episode metadata's `cameras` field must include GoPro names
even when the session is started with `preview_enabled=False`.

Bug discovered after merging the session-preview-toggle feature: when preview
is disabled, GoPro preview sources are not merged into `CameraManager._cameras`
(by design), but `lifecycle.episode_save` derived `metadata["cameras"]` from
that dict, so GoPro names disappeared from saved episodes. The Replay UI uses
`episode.cameras` to render video tiles, so the GoPro tile failed to appear
even though the GoPro mp4 was correctly downloaded into the dataset.

This test replicates the exact failure mode: configure preview_enabled=False,
record one episode, assert the saved episode metadata still lists the gopro
camera name.
"""
from __future__ import annotations

import asyncio
import glob
from pathlib import Path

import pytest
import pyarrow.parquet as pq
from httpx import AsyncClient, ASGITransport

from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_MP4 = REPO_ROOT / "tests" / "fixtures" / "gopro" / "sample_episode.mp4"


@pytest.mark.asyncio
async def test_episode_metadata_lists_gopro_when_preview_disabled(tmp_path: Path):
    """preview_enabled=False must not drop the GoPro from episode metadata."""
    pytest.importorskip("av")
    if not FIXTURE_MP4.exists():
        pytest.skip(f"fixture MP4 not found: {FIXTURE_MP4}")

    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir(parents=True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/session/start", json={
            "mode": "teleop",
            "dataset": "preview_off_ds",
            "task": "pick_block",
            "robot": "mock",
            "teleop": "mock_leader",
            "mapper": "identity",
            "cameras": [],
            "fps": 30,
            "gopros": ["mock_gopro"],
            "preview_enabled": False,
        })
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "ready"
        assert r.json()["preview_enabled"] is False

        r = await ac.post("/api/episode/start")
        assert r.status_code == 200, r.text
        await asyncio.sleep(0.15)
        r = await ac.post("/api/episode/stop")
        assert r.status_code == 200, r.text

        # Save now refuses while the GoPro DL is in flight (the FE
        # disables the Save buttons until pending==0). Mirror that wait.
        for _ in range(100):
            pending = (await ac.get("/api/session/gopro_pending")).json()["pending"]
            if pending == 0:
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail("gopro_pending never reached 0 within 10s")

        r = await ac.post("/api/episode/save", json={"success": True})
        assert r.status_code == 200, r.text

        await ac.post("/api/session/end")

    ds_root = app.state.datasets_root / "preview_off_ds"
    meta_files = sorted(glob.glob(str(ds_root / "meta" / "episodes" / "chunk-*" / "file-*.parquet")))
    assert meta_files, f"no episode metadata written under {ds_root}"
    rows = pq.read_table(meta_files[-1]).to_pylist()
    assert rows, "episode metadata parquet has no rows"
    cameras = rows[-1].get("cameras") or []
    assert "mock_gopro" in cameras, (
        f"GoPro 'mock_gopro' missing from episode metadata cameras={cameras}; "
        f"the Replay UI iterates this list and will not render the GoPro tile."
    )
