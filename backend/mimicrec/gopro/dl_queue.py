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
        """User-visible pending = sidecar count (includes staged awaiting commit)."""
        return sum(1 for _ in self._dir.glob("*.json"))
