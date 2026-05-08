from __future__ import annotations
import asyncio
from pathlib import Path
import pytest

from mimicrec.cloud.hub_meta import HubMeta, write_hub_meta
from mimicrec.cloud.push_state import PushCoordinator
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.pending import PendingEpisode


@pytest.mark.asyncio
async def test_auto_push_skips_when_disabled(tmp_path: Path):
    init_dataset(tmp_path / "ds", fps=30, joint_names=["j0"], camera_names=[])
    coord = PushCoordinator()
    write_hub_meta(tmp_path / "ds", HubMeta(repo_id="u/d", auto_push=False))

    triggered = []

    def fake_trigger(ds_root, ds_name, app_loop, **kwargs):
        triggered.append(ds_name)

    loop = asyncio.get_running_loop()
    ep = PendingEpisode.open(
        tmp_path / "ds", episode_index=0,
        coordinator=coord, ds_name="ds", app_loop=loop,
    )
    ep.append_row({"action": [0.1], "observation.state": [0.0],
                   "timestamp": 0.0, "frame_index": 0,
                   "episode_index": 0, "index": 0, "task_index": 0})
    ep.finalize()
    ep.save({"episode_index": 0, "task": "t", "num_frames": 1,
             "duration_sec": 0.0, "cameras": [], "fps": 30},
            _auto_push_trigger=fake_trigger)
    assert triggered == []


@pytest.mark.asyncio
async def test_auto_push_fires_when_enabled(tmp_path: Path):
    init_dataset(tmp_path / "ds", fps=30, joint_names=["j0"], camera_names=[])
    coord = PushCoordinator()
    write_hub_meta(tmp_path / "ds", HubMeta(repo_id="u/d", auto_push=True))

    triggered = []

    def fake_trigger(ds_root, ds_name, app_loop, **kwargs):
        triggered.append(ds_name)

    loop = asyncio.get_running_loop()
    ep = PendingEpisode.open(
        tmp_path / "ds", episode_index=0,
        coordinator=coord, ds_name="ds", app_loop=loop,
    )
    ep.append_row({"action": [0.1], "observation.state": [0.0],
                   "timestamp": 0.0, "frame_index": 0,
                   "episode_index": 0, "index": 0, "task_index": 0})
    ep.finalize()
    ep.save({"episode_index": 0, "task": "t", "num_frames": 1,
             "duration_sec": 0.0, "cameras": [], "fps": 30},
            _auto_push_trigger=fake_trigger)
    assert triggered == ["ds"]
