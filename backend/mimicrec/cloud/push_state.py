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
    """Per-process state for HF push tasks. Single-process / single-event-loop only.

    Memory: progress / save_locks dicts grow as datasets are pushed. Each entry
    is small (~200 bytes) and cleaned up via drop_dataset() on dataset deletion.
    For backends that push thousands of distinct datasets without deleting them,
    consider periodic cleanup of done/error entries older than N hours. v1
    accepts unbounded growth on the assumption that dataset count is bounded.
    """

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

    def try_reserve_delete(self, ds_name: str) -> bool:
        """Atomically reserve `ds_name` for deletion if no push is in flight.
        Returns True if successfully reserved (caller may proceed to delete),
        False if a push is in flight. Reservation prevents concurrent push.
        Caller must call drop_dataset(ds_name) when done."""
        with self._mu:
            if ds_name in self.in_flight:
                return False
            self.in_flight.add(ds_name)
            return True

    def drop_dataset(self, ds_name: str) -> None:
        """Cleanup all state for a deleted dataset."""
        with self._mu:
            self.in_flight.discard(ds_name)
            self.save_locks.pop(ds_name, None)
            self.progress.pop(ds_name, None)
