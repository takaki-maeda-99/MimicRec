from __future__ import annotations
import asyncio
import logging
import shutil
from pathlib import Path

from mimicrec.errors import HardwareError
from mimicrec.gopro.dl_queue import DLQueue
from mimicrec.gopro.ffmpeg_pass import (
    ffmpeg_copy, ffmpeg_downscale, update_info_json_codec,
)
from mimicrec.recording.dataset_layout import DatasetPaths
from mimicrec.util.error_bus import ErrorBus

log = logging.getLogger(__name__)


def _probe_mp4_duration(path: Path) -> float:
    import av
    with av.open(str(path)) as ctx:
        s = ctx.streams.video[0]
        if s.duration is None or s.time_base is None:
            return 0.0
        return float(s.duration * s.time_base)


class GoProDLWorker:
    def __init__(
        self,
        queue: DLQueue,
        devices: dict[str, object],
        paths: DatasetPaths,
        errors: ErrorBus,
        shutdown_grace_sec: float = 30.0,
    ) -> None:
        self._queue = queue
        self._devices = devices
        self._paths = paths
        self._errors = errors
        self._grace = shutdown_grace_sec
        self._stop = asyncio.Event()
        self._inflight: asyncio.Task | None = None

    async def run(self) -> None:
        while not self._stop.is_set():
            dq_task = asyncio.create_task(self._queue.dequeue())
            stop_task = asyncio.create_task(self._stop.wait())
            done, pending = await asyncio.wait(
                {dq_task, stop_task}, return_when=asyncio.FIRST_COMPLETED,
            )
            for p in pending: p.cancel()
            if stop_task in done:
                if not dq_task.cancelled():
                    try: dq_task.result()
                    except Exception: pass
                return
            try:
                job = dq_task.result()
            except Exception:
                continue
            self._inflight = asyncio.create_task(self._process_one(job))
            try:
                await self._inflight
            except asyncio.CancelledError:
                return
            self._inflight = None

    async def _process_one(self, job) -> None:
        # If the registry already requested discard before DLWorker dequeued
        # the job, terminate immediately without downloading.
        if job.state == "discard_pending":
            await self._queue.mark_done(job.job_id)
            return

        device = self._devices.get(job.gopro_serial)
        if device is None or getattr(device, "is_disabled", False):
            await self._errors.publish(HardwareError(
                f"GoPro DL: no device for serial {job.gopro_serial}, "
                f"sidecar kept (episode {job.episode_index})"))
            return

        tmp_raw = self._paths.pending_dir / f"gopro_dl_{job.job_id}_raw.mp4"
        staged = self._paths.pending_dir / "gopro_staged" / f"{job.job_id}.mp4"

        # Resume from tmp_raw if it matches SD-side size.
        skip_dl = False
        if tmp_raw.exists() and tmp_raw.stat().st_size > 0:
            try:
                files = await device.media_list()
                match = next((f for f in files if f.filename == job.sd_filename), None)
                if match is not None and tmp_raw.stat().st_size == match.size:
                    skip_dl = True
            except Exception:
                skip_dl = False

        if not skip_dl:
            try:
                await device.download_file(job.sd_filename, tmp_raw)
            except Exception as e:
                await self._errors.publish(HardwareError(
                    f"GoPro DL failed for ep {job.episode_index}: {e}"))
                return

        # Duration check: only flag "shorter than expected" by > 2.0s.
        try:
            duration = await asyncio.to_thread(_probe_mp4_duration, tmp_raw)
            expected = (job.episode_stop_mono_ns - job.episode_start_mono_ns) / 1e9
            if duration < expected - 2.0:
                await self._errors.publish(HardwareError(
                    f"GoPro recording shorter than episode: ep {job.episode_index} "
                    f"duration={duration:.3f}s expected≈{expected:.3f}s"))
        except Exception as e:
            log.warning("duration probe failed for %s: %s", tmp_raw, e)

        # ffmpeg pass: stage the output (no move to dataset path here).
        try:
            staged.parent.mkdir(parents=True, exist_ok=True)
            spec = device.get_spec()
            native = device.selected_preset
            aspect_match = abs(
                (native.width / native.height) - (spec.width / spec.height)
            ) < 0.01
            if native.width == spec.width and native.height == spec.height:
                await ffmpeg_copy(tmp_raw, staged)
            else:
                await ffmpeg_downscale(
                    tmp_raw, staged,
                    target_w=spec.width, target_h=spec.height,
                    aspect_mode=device.aspect_mode,
                    aspect_match=aspect_match,
                )
        except Exception as e:
            await self._errors.publish(HardwareError(
                f"GoPro ffmpeg failed for ep {job.episode_index}: {e}"))
            return

        try:
            tmp_raw.unlink(missing_ok=True)
        except Exception:
            pass

        # Re-read sidecar: registry may have requested commit/discard during DL.
        fresh = await self._queue.read_sidecar(job.job_id)
        if fresh is None:
            # Sidecar disappeared (registry already committed/discarded?).
            staged.unlink(missing_ok=True)
            return

        if fresh.state == "commit_pending":
            await self._commit_to_dataset(job, staged)
            await self._queue.mark_done(job.job_id)
            return
        if fresh.state == "discard_pending":
            staged.unlink(missing_ok=True)
            await self._queue.mark_done(job.job_id)
            return

        # Normal path: mark as staged, await registry's commit/discard.
        fresh.state = "staged"
        fresh.staged_path = str(staged)
        await self._queue.update_sidecar(fresh)

        # Race: registry may have written commit_pending/discard_pending between
        # our read and update. Re-read once more.
        after = await self._queue.read_sidecar(job.job_id)
        if after is None:
            staged.unlink(missing_ok=True)
            return
        if after.state == "commit_pending":
            await self._commit_to_dataset(after, staged)
            await self._queue.mark_done(job.job_id)
        elif after.state == "discard_pending":
            staged.unlink(missing_ok=True)
            await self._queue.mark_done(job.job_id)
        # else: state="staged" persisted — registry will commit/discard later.

    async def _commit_to_dataset(self, job, staged: Path) -> None:
        """Move staged MP4 into the dataset, patch info.json codec."""
        dest = self._paths.episode_video(job.chunk_index, job.cam_name, job.episode_index)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staged), str(dest))
        except Exception as e:
            await self._errors.publish(HardwareError(
                f"GoPro move failed for ep {job.episode_index}: {e}"))
            return
        try:
            await update_info_json_codec(self._paths, job.cam_name)
        except Exception as e:
            log.warning("update_info_json_codec failed: %s", e)

    async def stop(self) -> None:
        self._stop.set()
        if self._inflight is not None:
            try:
                await asyncio.wait_for(self._inflight, timeout=self._grace)
            except asyncio.TimeoutError:
                self._inflight.cancel()
                try: await self._inflight
                except (asyncio.CancelledError, Exception): pass
