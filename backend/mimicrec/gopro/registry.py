from __future__ import annotations
import asyncio
import logging
from pathlib import Path

from mimicrec.errors import HardwareError
from mimicrec.gopro.dl_queue import DLQueue
from mimicrec.gopro.dl_worker import GoProDLWorker
from mimicrec.gopro.preview import GoProPreviewSource
from mimicrec.gopro.recorder import GoProRecorder
from mimicrec.gopro.types import GoProSpec
from mimicrec.recording.dataset_layout import DatasetPaths
from mimicrec.util.error_bus import ErrorBus

log = logging.getLogger(__name__)


class GoProDeviceRegistry:
    def __init__(
        self,
        devices: list,
        paths: DatasetPaths,
        errors: ErrorBus,
        preview_enabled: bool = True,
    ) -> None:
        names = [d.name for d in devices]
        serials = [d.usb_serial for d in devices]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate name in GoPro devices: {names}")
        if len(set(serials)) != len(serials):
            raise ValueError(f"duplicate usb_serial in GoPro devices: {serials}")
        self._devices = devices
        self._paths = paths
        self._errors = errors
        self._preview_enabled = preview_enabled
        self._queue: DLQueue | None = None
        self._worker: GoProDLWorker | None = None
        self._worker_task: asyncio.Task | None = None
        self._recorders: dict[str, GoProRecorder] = {}
        self._previews: dict[str, GoProPreviewSource] = {}

    async def start(self) -> None:
        # 1. Connect all devices, collecting exceptions and disabling failed devices.
        async def _try_connect(d):
            try:
                await d.connect()
                return None
            except Exception as e:
                if hasattr(d, "disable"):
                    d.disable(f"connect failed: {e}")
                return (d.name, e)

        results = await asyncio.gather(
            *[_try_connect(d) for d in self._devices],
            return_exceptions=False,
        )
        for r in results:
            if r is not None:
                name, exc = r
                await self._errors.publish(HardwareError(f"GoPro {name} connect failed: {exc}"))

        # 2. Restore queue, build recorders + (optionally) preview sources.
        self._queue = DLQueue.restore(self._paths.pending_dir / "gopro_dl")
        for d in self._devices:
            self._recorders[d.name] = GoProRecorder(d, self._queue, self._paths, self._errors)
            if self._preview_enabled:
                # The device knows which UDP port the camera will actually
                # emit to: HERO9–11 firmware ignores the port arg and forces
                # 8554, so the device must claim it via udp_preview_port and
                # the preview source binds the same.
                self._previews[d.name] = GoProPreviewSource(d, udp_port=d.udp_preview_port)

        # 3. Start the DL worker.
        devices_by_serial = {d.usb_serial: d for d in self._devices}
        self._worker = GoProDLWorker(self._queue, devices_by_serial, self._paths, self._errors)
        self._worker_task = asyncio.create_task(self._worker.run())

    async def stop(self) -> None:
        if self._worker is not None:
            await self._worker.stop()
        if self._worker_task is not None:
            try:
                await asyncio.wait_for(self._worker_task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                self._worker_task.cancel()
        for src in self._previews.values():
            try: await src.disconnect()
            except Exception: pass
        for d in self._devices:
            try: await d.disconnect()
            except Exception: pass

    async def _fan_out(self, op_name: str, coro_factory) -> None:
        """Run coro_factory for each recorder, gather, inspect exceptions."""
        results = await asyncio.gather(
            *[coro_factory(r) for r in self._recorders.values()],
            return_exceptions=True,
        )
        for (name, recorder), result in zip(self._recorders.items(), results):
            if isinstance(result, BaseException):
                if hasattr(recorder._device, "disable"):  # type: ignore[attr-defined]
                    recorder._device.disable(f"{op_name} failed: {result}")  # type: ignore[attr-defined]
                await self._errors.publish(HardwareError(
                    f"GoPro {name} {op_name} failed: {result}"))

    async def episode_start(self, episode_index: int, t_host_mono_ns: int) -> None:
        await self._fan_out(
            "episode_start",
            lambda r: r.start_episode(episode_index, t_host_mono_ns),
        )

    async def episode_stop(self, episode_index: int) -> None:
        await self._fan_out(
            "episode_stop",
            lambda r: r.stop_episode(episode_index),
        )

    async def commit_episode(self, episode_index: int) -> None:
        """Called from SessionManager.episode_save. For each sidecar matching
        episode_index: if staged, move to dataset; if pending_dl, flip to
        commit_pending so DLWorker handles it after staging completes.

        Each per-sidecar transaction is wrapped in queue.lock_for(job_id)
        to serialize against DLWorker's concurrent state-decision write
        (see DLQueue.lock_for docstring)."""
        if self._queue is None:
            return
        from mimicrec.gopro.ffmpeg_pass import update_info_json_codec
        import shutil as _sh
        jobs = await self._queue.find_jobs_for_episode(episode_index)
        for job in jobs:
            async with self._queue.lock_for(job.job_id):
                fresh = await self._queue.read_sidecar(job.job_id)
                if fresh is None:
                    continue  # already finalized
                if fresh.state == "staged" and fresh.staged_path:
                    src = Path(fresh.staged_path)
                    dest = self._paths.episode_video(fresh.chunk_index, fresh.cam_name, fresh.episode_index)
                    try:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        _sh.move(str(src), str(dest))
                        await update_info_json_codec(self._paths, fresh.cam_name)
                        await self._queue.mark_done(fresh.job_id)
                    except Exception as e:
                        await self._errors.publish(HardwareError(
                            f"commit_episode {fresh.episode_index} ({fresh.cam_name}) failed: {e}"))
                elif fresh.state == "pending_dl":
                    fresh.state = "commit_pending"
                    await self._queue.update_sidecar(fresh)
                # else (commit_pending / discard_pending / staged-but-no-path): skip

    async def discard_episode(self, episode_index: int) -> None:
        """Called from SessionManager.episode_discard. Symmetric to commit:
        delete staged files / flip pending_dl → discard_pending. Same
        per-sidecar locking discipline as commit_episode."""
        if self._queue is None:
            return
        jobs = await self._queue.find_jobs_for_episode(episode_index)
        for job in jobs:
            async with self._queue.lock_for(job.job_id):
                fresh = await self._queue.read_sidecar(job.job_id)
                if fresh is None:
                    continue
                if fresh.state == "staged" and fresh.staged_path:
                    Path(fresh.staged_path).unlink(missing_ok=True)
                    await self._queue.mark_done(fresh.job_id)
                elif fresh.state == "pending_dl":
                    fresh.state = "discard_pending"
                    await self._queue.update_sidecar(fresh)

    def preview_sources(self) -> dict[str, GoProPreviewSource]:
        return dict(self._previews)

    def gopro_specs(self) -> dict[str, GoProSpec]:
        return {d.name: d.get_spec() for d in self._devices}

    @property
    def pending_count(self) -> int:
        return self._queue.pending_count if self._queue is not None else 0

    @property
    def dl_in_flight_count(self) -> int:
        """Number of sidecars where the GoPro mp4 is NOT yet ready for
        commit, PLUS any recorders currently mid-``stop_episode``
        (shutter_off + media_list polling window — the sidecar has not
        appeared on disk yet but is imminent). Drives the
        episode_save / episode_start gates."""
        base = self._queue.dl_in_flight_count if self._queue is not None else 0
        for rec in self._recorders.values():
            if getattr(rec, "is_finishing", False):
                base += 1
        return base
