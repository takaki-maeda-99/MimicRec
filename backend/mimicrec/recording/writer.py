from __future__ import annotations
import asyncio
import time

from mimicrec.recording.pending import PendingEpisode
from mimicrec.recording.parquet_row import sample_bundle_to_row
from mimicrec.types import SampleBundle
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics


async def run_writer(
    current_pending: LatestValue,   # LatestValue[PendingEpisode | None]
    queue: asyncio.Queue,
    metrics: Metrics,
    stopped: asyncio.Event,
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
        )
        pending.append_row(row, frames=bundle.frames)
        frame_counter += 1
        metrics.inc("writer_rows_written")

        done_ns = time.monotonic_ns()
        metrics.set_gauge("writer_lag_ms", (done_ns - started_ns) / 1_000_000)
