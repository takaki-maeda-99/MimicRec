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

    def __init__(self, device, queue: DLQueue, paths: DatasetPaths, errors: ErrorBus, slot: str) -> None:
        self._device = device
        self._slot = slot
        self._queue = queue
        self._paths = paths
        self._errors = errors
        self._known_files: set[str] = set()
        self._state: _EpisodeState | None = None
        # True between the start of ``stop_episode`` and the moment a
        # sidecar is on disk (or the no-new-file warning is published).
        # Surfaces in ``GoProDeviceRegistry.dl_in_flight_count`` so the
        # save gate stays armed during the shutter_off + media_list
        # polling window. Without this, the SessionManager flips state
        # to REVIEW before stop_episode runs and the operator can race
        # the sidecar by hitting Space the instant they see REVIEW.
        self._is_finishing: bool = False

    @property
    def is_finishing(self) -> bool:
        return self._is_finishing

    async def start_episode(self, episode_index: int, t_host_mono_ns: int) -> None:
        if getattr(self._device, "is_disabled", False):
            return
        # Snapshot known files BEFORE shutter so stop can compute the delta.
        try:
            files = await self._device.media_list()
            self._known_files |= {f.filename for f in files}
        except Exception as e:
            log.warning("media_list snapshot failed for %s: %s", self._device.name, e)

        # HERO11 occasionally returns transient HTTP 500 on set_shutter
        # (USB-CDC-NCM hiccup, mid-finalization of a previous mp4, or HTTP
        # queue contention with media_list/preview). shutter_off retries
        # below — keep the same discipline here so a single transient
        # error does not silently lose a whole episode of GoPro footage.
        for attempt in range(3):
            try:
                await self._device.shutter_on()
                break
            except Exception as e:
                if attempt == 2:
                    await self._errors.publish(HardwareError(
                        f"GoPro {self._device.name} shutter_on retries exhausted: {e}"))
                    self._state = None
                    return
                await asyncio.sleep(0.2)

        self._state = _EpisodeState(
            episode_index=episode_index,
            episode_start_mono_ns=time.monotonic_ns(),
        )

    async def stop_episode(self, episode_index: int) -> None:
        if getattr(self._device, "is_disabled", False):
            return
        self._is_finishing = True
        try:
            await self._stop_episode_inner(episode_index)
        finally:
            self._is_finishing = False

    async def _stop_episode_inner(self, episode_index: int) -> None:
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

        # The HERO11 takes a moment to flush moov + close the SD file
        # after shutter_off. Polling once gives the camera a 0-second budget
        # and races finalization for short clips, so media_list returns the
        # OLD list, we declare 'no new file detected', and never enqueue a
        # DL job. With no sidecar, Bug B's pending-count gate cannot block
        # the next shutter, so the operator triggers a new recording while
        # the previous mp4 is still being written. Poll a few times before
        # giving up — typical finalization for a 30s 1080p clip is under
        # 1s; the 0.3s × 8 = 2.4s budget covers slower cases without making
        # truly-empty stops feel sluggish.
        new_files: list = []
        for attempt in range(8):
            try:
                files = await self._device.media_list()
            except Exception:
                files = []
            new_files = [f for f in files if f.filename not in self._known_files]
            if new_files:
                break
            await asyncio.sleep(0.3)
        # Always remember every new filename so the next episode's diff
        # is clean even when we ignore non-video sidecars below.
        self._known_files |= {f.filename for f in new_files}
        if not new_files:
            await self._errors.publish(HardwareError(
                f"GoPro {self._device.name} ep {episode_index}: no new file detected — orphan or no recording"))
            return

        # Split into video chapters vs sidecar files. The GoPro can drop
        # a .JPG photo (accidental shutter / QuikCapture), .LRV proxy,
        # or .THM thumbnail into media_list alongside the chapter; if we
        # let one through, the group sort below picks it (the previous
        # ``("?", filename)`` fallback sorted before any quality letter
        # because ``"?" < "G"`` in ASCII), DLWorker downloads it as
        # ``..._raw.mp4``, and ffmpeg fails to demux a still image.
        video_chapters = []
        sidecars = []
        for f in new_files:
            try:
                parse_chapter_filename(f.filename)
                video_chapters.append(f)
            except ValueError:
                sidecars.append(f)

        if not video_chapters:
            await self._errors.publish(HardwareError(
                f"GoPro {self._device.name} ep {episode_index}: no video chapter in new files "
                f"(saw non-video: {[f.filename for f in sidecars]})"))
            return

        # Chapter detection: group video chapters by (quality, id).
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for f in video_chapters:
            q, ch, eid = parse_chapter_filename(f.filename)
            groups[(q, eid)].append((ch, f))

        # Pick the first chapter (lowest ch) of the first group.
        first_group_key = sorted(groups.keys())[0]
        items = sorted(groups[first_group_key], key=lambda t: t[0])
        chosen = items[0][1]

        if sidecars:
            await self._errors.publish(HardwareError(
                f"GoPro {self._device.name} ep {episode_index}: ignored non-video sidecar files "
                f"{[f.filename for f in sidecars]} (chapter {chosen.filename} downloaded)"))
        if len(video_chapters) > 1:
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
            cam_name=self._slot,
            episode_start_mono_ns=state.episode_start_mono_ns,
            episode_stop_mono_ns=time.monotonic_ns(),
        )
        await self._queue.enqueue(job)
