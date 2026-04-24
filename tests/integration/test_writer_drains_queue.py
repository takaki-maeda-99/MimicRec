import asyncio
from pathlib import Path

import numpy as np

from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.recording.pending import PendingEpisode
from mimicrec.recording.writer import run_writer
from mimicrec.types import Frame, RobotCommand, RobotState, SampleBundle, Stamped
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics


async def test_writer_drains_queue_into_pending_with_mp4(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=["front"])
    pe = PendingEpisode.open(ds, episode_index=0)
    pe.open_video_writers(fps=30, cameras={"front": (64, 48)})

    current: LatestValue[PendingEpisode | None] = LatestValue()
    current.set(pe, t_mono_ns=1)
    q: asyncio.Queue = asyncio.Queue()
    metrics = Metrics()
    stopped = asyncio.Event()

    task = asyncio.create_task(run_writer(
        current_pending=current, queue=q, metrics=metrics, stopped=stopped,
    ))

    img = np.zeros((48, 64, 3), dtype=np.uint8)
    for i in range(10):
        state = Stamped(
            RobotState(
                joint_pos=np.array([0.0, 0.0], dtype=np.float32),
                joint_vel=np.zeros(2, np.float32),
                joint_effort=np.zeros(2, np.float32),
                t_mono_ns=i * 33_000_000,
            ),
            t_mono_ns=i * 33_000_000,
        )
        action = RobotCommand(q=np.zeros(2, np.float32), t_mono_ns=i * 33_000_000)
        frame = Stamped(Frame(image=img.copy(), t_mono_ns=i * 33_000_000), t_mono_ns=i * 33_000_000)
        await q.put(SampleBundle(
            tick_t_mono_ns=i * 33_000_000,
            state=state, action=action, frames={"front": frame},
        ))

    while q.qsize() > 0:
        await asyncio.sleep(0.01)
    stopped.set()
    await task

    pe.finalize()
    staged_parquet = list(pe.stage_dir.glob("*.parquet"))
    staged_mp4 = list(pe.stage_dir.glob("*.mp4"))
    assert len(staged_parquet) == 1
    assert len(staged_mp4) == 1
    assert metrics.get("writer_rows_written") == 10
    assert metrics.gauge("queue_depth") == 0


async def test_writer_drops_bundles_when_no_current_pending(tmp_path: Path):
    current: LatestValue[object] = LatestValue()
    current.set(None, t_mono_ns=1)
    q: asyncio.Queue = asyncio.Queue()
    metrics = Metrics()
    stopped = asyncio.Event()

    task = asyncio.create_task(run_writer(
        current_pending=current, queue=q, metrics=metrics, stopped=stopped,
    ))
    state = Stamped(
        RobotState(
            joint_pos=np.zeros(2, np.float32),
            joint_vel=np.zeros(2, np.float32),
            joint_effort=np.zeros(2, np.float32),
        ),
        t_mono_ns=0,
    )
    action = RobotCommand(q=np.zeros(2, np.float32))
    for _ in range(3):
        await q.put(SampleBundle(
            tick_t_mono_ns=0, state=state, action=action, frames={}
        ))
    while q.qsize() > 0:
        await asyncio.sleep(0.01)
    stopped.set()
    await task

    assert metrics.get("writer_dropped_no_pending") == 3
    assert metrics.get("writer_rows_written") == 0
