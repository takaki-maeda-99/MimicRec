from __future__ import annotations

import asyncio
import time

from mimicrec.motion.types import MotionSampleBundle
from mimicrec.recording.motion_row import motion_bundle_to_row
from mimicrec.recording.pending import PendingEpisode
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics


async def run_motion_writer(
    *,
    current_pending: LatestValue,
    queue: asyncio.Queue,
    metrics: Metrics,
    stopped: asyncio.Event,
) -> None:
    last_pending: PendingEpisode | None = None
    episode_start_t_mono_ns: int | None = None
    frame_counter = 0
    while not stopped.is_set() or not queue.empty():
        try:
            bundle: MotionSampleBundle = await asyncio.wait_for(
                queue.get(), timeout=0.05
            )
        except asyncio.TimeoutError:
            continue
        try:
            pending_slot = current_pending.peek()
            pending = pending_slot.value if pending_slot is not None else None
            if pending is not last_pending:
                last_pending = pending
                episode_start_t_mono_ns = None
                frame_counter = 0
            if pending is None:
                metrics.inc("writer_dropped_no_pending")
                continue
            if episode_start_t_mono_ns is None:
                episode_start_t_mono_ns = bundle.tick_t_mono_ns
            row = motion_bundle_to_row(
                bundle,
                episode_start_t_mono_ns,
                frame_index=frame_counter,
                episode_index=pending.episode_index,
            )
            loop = asyncio.get_running_loop()
            started = time.monotonic_ns()
            await loop.run_in_executor(None, pending.append_row, row, bundle.frames)
            frame_counter += 1
            metrics.inc("writer_rows_written")
            metrics.set_gauge(
                "writer_lag_ms", (time.monotonic_ns() - started) / 1_000_000
            )
        finally:
            queue.task_done()
