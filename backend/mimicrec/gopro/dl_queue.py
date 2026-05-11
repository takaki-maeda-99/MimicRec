from __future__ import annotations
import asyncio
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class GoProDLJob:
    """state machine: pending_dl → staged → (commit/discard pending) → terminal."""
    job_id: str
    gopro_serial: str
    sd_filename: str
    episode_index: int
    chunk_index: int
    cam_name: str
    episode_start_mono_ns: int
    episode_stop_mono_ns: int
    state: str = "pending_dl"            # "pending_dl" | "staged" | "commit_pending" | "discard_pending"
    staged_path: str | None = None       # set when state in {staged, commit_pending}

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> "GoProDLJob":
        # Backward compat: old sidecars without state default to pending_dl.
        d = dict(d)
        d.setdefault("state", "pending_dl")
        d.setdefault("staged_path", None)
        return cls(**d)


def _atomic_write_with_dir_fsync(path: Path, payload: str) -> None:
    """Write file, fsync file, atomic rename, fsync directory."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload)
    fd = os.open(str(tmp), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(path))
    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _delete_with_dir_fsync(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


class DLQueue:
    """Persistent FIFO queue. All file I/O via asyncio.to_thread."""

    def __init__(self, pending_dir: Path):
        self._dir = pending_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._q: asyncio.Queue[GoProDLJob] = asyncio.Queue()
        # Per-job lock guarding read-decide-write transactions on a sidecar.
        # Both DLWorker (post-ffmpeg state decision) and registry
        # (commit_episode/discard_episode) take this around their
        # read+write blocks; without it, DLQueue.update_sidecar runs in
        # asyncio.to_thread and can race at OS-level with another caller's
        # update_sidecar, losing the state transition (the staged mp4
        # ends up orphaned in pending_staged forever).
        self._sidecar_locks: dict[str, asyncio.Lock] = {}

    def lock_for(self, job_id: str) -> asyncio.Lock:
        """Async lock serializing all read-modify-write transactions on
        ``job_id``'s sidecar. Caller must wrap their entire
        ``read_sidecar → decide → update_sidecar/mark_done`` block in
        ``async with queue.lock_for(job_id):``.
        """
        lock = self._sidecar_locks.get(job_id)
        if lock is None:
            lock = asyncio.Lock()
            self._sidecar_locks[job_id] = lock
        return lock

    async def enqueue(self, job: GoProDLJob) -> None:
        path = self._dir / f"{job.job_id}.json"
        payload = json.dumps(job.to_json(), indent=2)
        await asyncio.to_thread(_atomic_write_with_dir_fsync, path, payload)
        await self._q.put(job)

    async def dequeue(self) -> GoProDLJob:
        return await self._q.get()

    async def mark_done(self, job_id: str) -> None:
        path = self._dir / f"{job_id}.json"
        await asyncio.to_thread(_delete_with_dir_fsync, path)

    async def update_sidecar(self, job: GoProDLJob) -> None:
        """Atomic rewrite of sidecar (state / staged_path 変更時)."""
        path = self._dir / f"{job.job_id}.json"
        payload = json.dumps(job.to_json(), indent=2)
        await asyncio.to_thread(_atomic_write_with_dir_fsync, path, payload)

    async def read_sidecar(self, job_id: str) -> GoProDLJob | None:
        """Read a single sidecar (returns None if missing/corrupt)."""
        path = self._dir / f"{job_id}.json"
        if not path.exists():
            return None
        try:
            return GoProDLJob.from_json(json.loads(path.read_text()))
        except Exception:
            return None

    async def find_jobs_for_episode(self, episode_index: int) -> list[GoProDLJob]:
        """Scan all sidecars; return jobs matching episode_index (any state)."""
        out: list[GoProDLJob] = []
        for sidecar in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(sidecar.read_text())
                job = GoProDLJob.from_json(data)
            except Exception:
                continue
            if job.episode_index == episode_index:
                out.append(job)
        return out

    @classmethod
    def restore(cls, pending_dir: Path) -> "DLQueue":
        q = cls(pending_dir)
        for sidecar in sorted(pending_dir.glob("*.json")):
            try:
                data = json.loads(sidecar.read_text())
                job = GoProDLJob.from_json(data)
            except Exception:
                continue
            # Skip already-staged jobs — DLWorker shouldn't re-process them.
            # registry.commit_episode/discard_episode will handle them.
            if job.state == "staged":
                continue
            q._q.put_nowait(job)
        return q

    @property
    def pending_count(self) -> int:
        """Raw sidecar count on disk (any state). Mostly useful for tests
        and restoration logic. Operational gates should prefer
        ``dl_in_flight_count`` so that already-staged jobs (DL done,
        awaiting a commit that save() will perform synchronously) do not
        block save."""
        return sum(1 for _ in self._dir.glob("*.json"))

    @property
    def dl_in_flight_count(self) -> int:
        """Sidecars where the GoPro mp4 is NOT yet ready for commit —
        i.e. state is ``pending_dl`` / ``commit_pending`` /
        ``discard_pending``. ``staged`` sidecars are excluded because
        their bytes are already on the host; ``commit_episode`` will
        move them to the dataset atomically inside ``episode_save``.
        Used as the gate for episode_save (block while DL still in
        flight) and episode_start (same metric — same intent)."""
        n = 0
        for sidecar in self._dir.glob("*.json"):
            try:
                data = json.loads(sidecar.read_text())
            except Exception:
                # Unparseable sidecar — count as in-flight to be safe so
                # operator notices something is wrong instead of saving
                # a broken episode silently.
                n += 1
                continue
            if data.get("state") != "staged":
                n += 1
        return n
