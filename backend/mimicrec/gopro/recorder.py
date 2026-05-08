from __future__ import annotations
import asyncio
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass

from mimicrec.errors import HardwareError
from mimicrec.gopro.dl_queue import DLQueue, GoProDLJob
from mimicrec.gopro.ffmpeg_pass import parse_chapter_filename
from mimicrec.recording.dataset_layout import DatasetPaths, resolve_chunk
from mimicrec.util.error_bus import ErrorBus

log = logging.getLogger(__name__)


@dataclass
class _EpisodeState:
    episode_index: int
    episode_start_mono_ns: int


class GoProRecorder:
    """Control-plane view over a single GoProDevice."""

    def __init__(self, device, queue: DLQueue, paths: DatasetPaths, errors: ErrorBus) -> None:
        self._device = device
        self._queue = queue
        self._paths = paths
        self._errors = errors
        self._known_files: set[str] = set()
        self._state: _EpisodeState | None = None

    async def start_episode(self, episode_index: int, t_host_mono_ns: int) -> None:
        if getattr(self._device, "is_disabled", False):
            return
        # Snapshot known files BEFORE shutter so stop can compute the delta.
        try:
            files = await self._device.media_list()
            self._known_files |= {f.filename for f in files}
        except Exception as e:
            log.warning("media_list snapshot failed for %s: %s", self._device.name, e)

        try:
            await self._device.shutter_on()
        except Exception as e:
            await self._errors.publish(HardwareError(f"GoPro {self._device.name} shutter_on failed: {e}"))
            self._state = None
            return

        self._state = _EpisodeState(
            episode_index=episode_index,
            episode_start_mono_ns=time.monotonic_ns(),
        )

    async def stop_episode(self, episode_index: int) -> None:
        if getattr(self._device, "is_disabled", False):
            return
        state = self._state
        self._state = None

        for attempt in range(3):
            try:
                await self._device.shutter_off()
                break
            except Exception as e:
                if attempt == 2:
                    await self._errors.publish(HardwareError(
                        f"GoPro {self._device.name} shutter_off retries exhausted: {e}"))
                    return
                await asyncio.sleep(0.2)

        if state is None or state.episode_index != episode_index:
            return

        try:
            files = await self._device.media_list()
        except Exception:
            files = []
        new_files = [f for f in files if f.filename not in self._known_files]
        if not new_files:
            await self._errors.publish(HardwareError(
                f"GoPro {self._device.name} ep {episode_index}: no new file detected — orphan or no recording"))
            return

        # Chapter detection: group new files by (quality, id).
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for f in new_files:
            try:
                q, ch, eid = parse_chapter_filename(f.filename)
            except ValueError:
                # Unknown filename pattern — treat as its own group.
                groups[("?", f.filename)].append((99, f))
                continue
            groups[(q, eid)].append((ch, f))

        # Pick the first chapter (lowest ch) of the first group.
        first_group_key = sorted(groups.keys())[0]
        items = sorted(groups[first_group_key], key=lambda t: t[0])
        chosen = items[0][1]

        # All other new files are orphan; remember them.
        all_new_filenames = {f.filename for f in new_files}
        self._known_files |= all_new_filenames
        if len(all_new_filenames) > 1:
            await self._errors.publish(HardwareError(
                f"GoPro {self._device.name} ep {episode_index}: chapter split detected — "
                f"only first chapter saved ({chosen.filename}), rest left on SD"))

        chunk_index = resolve_chunk(episode_index)
        job = GoProDLJob(
            job_id=str(uuid.uuid4()),
            gopro_serial=self._device.usb_serial,
            sd_filename=chosen.filename,
            episode_index=episode_index,
            chunk_index=chunk_index,
            cam_name=self._device.name,
            episode_start_mono_ns=state.episode_start_mono_ns,
            episode_stop_mono_ns=time.monotonic_ns(),
        )
        await self._queue.enqueue(job)
