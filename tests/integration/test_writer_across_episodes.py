import asyncio
from pathlib import Path
import numpy as np

from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.pending import PendingEpisode
from mimicrec.recording.writer import run_writer
from mimicrec.types import RobotCommand, RobotState, SampleBundle, Stamped
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics


async def test_writer_handles_two_episodes_without_restart(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=[])

    current: LatestValue[PendingEpisode | None] = LatestValue()
    q: asyncio.Queue = asyncio.Queue()
    metrics = Metrics()
    stopped = asyncio.Event()
    task = asyncio.create_task(run_writer(
        current_pending=current, queue=q, metrics=metrics, stopped=stopped,
    ))

    # Episode 0
    pe0 = PendingEpisode.open(ds, episode_index=0)
    current.set(pe0, t_mono_ns=1)
    state = Stamped(
        RobotState(joint_pos=np.zeros(2, np.float32), joint_vel=np.zeros(2, np.float32),
                   joint_effort=np.zeros(2, np.float32)),
        t_mono_ns=0,
    )
    action = RobotCommand(q=np.zeros(2, np.float32))
    for i in range(5):
        await q.put(SampleBundle(tick_t_mono_ns=i, state=state, action=action, frames={}))
    while q.qsize() > 0:
        await asyncio.sleep(0.01)

    # REVIEW: writer should drain and drop
    current.set(None, t_mono_ns=2)
    await q.put(SampleBundle(tick_t_mono_ns=99, state=state, action=action, frames={}))
    while q.qsize() > 0:
        await asyncio.sleep(0.01)

    # Episode 1
    pe1 = PendingEpisode.open(ds, episode_index=1)
    current.set(pe1, t_mono_ns=3)
    for i in range(3):
        await q.put(SampleBundle(tick_t_mono_ns=100 + i, state=state, action=action, frames={}))
    while q.qsize() > 0:
        await asyncio.sleep(0.01)

    stopped.set()
    await task

    pe0.finalize()
    pe1.finalize()
    assert metrics.get("writer_rows_written") == 8   # 5 + 3
    assert metrics.get("writer_dropped_no_pending") == 1
