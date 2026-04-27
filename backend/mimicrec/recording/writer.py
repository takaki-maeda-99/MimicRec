from __future__ import annotations
import asyncio
import time
from typing import TYPE_CHECKING

from mimicrec.recording.pending import PendingEpisode
from mimicrec.recording.parquet_row import sample_bundle_to_row
from mimicrec.types import SampleBundle
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics

if TYPE_CHECKING:
    from mimicrec.kinematics import FKService


async def run_writer(
    current_pending: LatestValue,   # LatestValue[PendingEpisode | None]
    queue: asyncio.Queue,
    metrics: Metrics,
    stopped: asyncio.Event,
    fk: "FKService | None" = None,
) -> None:
    last_pending: PendingEpisode | None = None
    episode_start_t_mono_ns: int | None = None
    video_frame_index: dict[str, int] = {}
    frame_counter: int = 0

    while not stopped.is_set() or not queue.empty():
        try:
            bundle: SampleBundle = await asyncio.wait_for(queue.get(), timeout=0.05)
        except asyncio.TimeoutError:
            metrics.set_gauge("queue_depth", float(queue.qsize()))
            continue
        # Every successful ``queue.get()`` must be matched by
        # ``queue.task_done()`` so ``await queue.join()`` in
        # ``episode_stop`` can tell when the writer has truly drained.
        # Wrap the entire processing block in try/finally so dropped
        # bundles (pending is None) and exceptions still call task_done.
        try:
            started_ns = time.monotonic_ns()
            metrics.set_gauge("queue_depth", float(queue.qsize()))

            slot = current_pending.peek()
            pending = slot.value if slot is not None else None

            if pending is not last_pending:
                last_pending = pending
                episode_start_t_mono_ns = None
                video_frame_index = {}
                frame_counter = 0

            if pending is None:
                metrics.inc("writer_dropped_no_pending")
                continue

            if episode_start_t_mono_ns is None:
                episode_start_t_mono_ns = bundle.tick_t_mono_ns
                video_frame_index = {name: 0 for name in bundle.frames.keys()}

            advanced: dict[str, int] = {}
            for cam_name, stamped in bundle.frames.items():
                if cam_name not in video_frame_index:
                    video_frame_index[cam_name] = 0
                advanced[cam_name] = video_frame_index[cam_name]
                if stamped is not None:
                    video_frame_index[cam_name] += 1

            row = sample_bundle_to_row(
                bundle,
                episode_start_t_mono_ns,
                advanced,
                frame_index=frame_counter,
                episode_index=pending.episode_index,
                global_index=0,  # will be set properly when we have global tracking
                task_index=0,
                fk=fk,
            )
            # Defer append_row to a worker thread: H.264 encoding inside
            # Mp4EpisodeWriter.write_frame is CPU-bound (libx264) and can
            # take 30-50 ms per frame. Running it on the asyncio thread
            # blocked the backend long enough that the recording loop tick
            # missed by 100-260 ms — and once unblocked, several deferred
            # ticks fired back-to-back with sub-millisecond gaps. That's
            # exactly the jitter we observed (median 36 ms, min ~0 ms,
            # max 260+ ms). Writes for a given episode still serialize here
            # because we await each one, keeping writer state consistent.
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, pending.append_row, row, bundle.frames
            )
            frame_counter += 1
            metrics.inc("writer_rows_written")

            done_ns = time.monotonic_ns()
            metrics.set_gauge("writer_lag_ms", (done_ns - started_ns) / 1_000_000)
        finally:
            queue.task_done()
