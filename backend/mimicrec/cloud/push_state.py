from __future__ import annotations
import threading
from dataclasses import dataclass
from typing import Literal


@dataclass
class PushProgress:
    status: Literal["idle", "queued", "uploading", "done", "error"] = "idle"
    started_at: str | None = None
    ended_at: str | None = None
    error: str | None = None
    repo_id: str | None = None
    last_pushed_commit_sha: str | None = None


class PushCoordinator:
    """Per-process state for HF push tasks. Single-process / single-event-loop only."""

    def __init__(self) -> None:
        self._mu = threading.Lock()
        self.in_flight: set[str] = set()
        self.save_locks: dict[str, threading.RLock] = {}
        self.progress: dict[str, PushProgress] = {}

    def try_reserve(self, ds_name: str) -> bool:
        """Atomically check & reserve. Returns True if reserved, False if already in-flight."""
        with self._mu:
            if ds_name in self.in_flight:
                return False
            self.in_flight.add(ds_name)
            return True

    def release(self, ds_name: str) -> None:
        with self._mu:
            self.in_flight.discard(ds_name)

    def get_save_lock(self, ds_name: str) -> threading.RLock:
        """RLock so that nested writer calls (append_episode → update_info_totals)
        on the same thread don't deadlock."""
        with self._mu:
            existing = self.save_locks.get(ds_name)
            if existing is None:
                existing = threading.RLock()
                self.save_locks[ds_name] = existing
            return existing

    def drop_dataset(self, ds_name: str) -> None:
        """Cleanup all state for a deleted dataset."""
        with self._mu:
            self.in_flight.discard(ds_name)
            self.save_locks.pop(ds_name, None)
            self.progress.pop(ds_name, None)
