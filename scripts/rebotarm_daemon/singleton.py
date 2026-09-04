"""Process-level exclusion for every real reBotArm daemon launch path."""
from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def default_lock_path() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / "mimicrec-rebotarm.lock"
    return Path("/tmp") / f"mimicrec-rebotarm-{os.getuid()}.lock"


@contextmanager
def daemon_lock(path: Path | None = None) -> Iterator[bool]:
    """Yield whether this process exclusively owns the daemon lock."""
    lock_path = path or default_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock_path, flags, 0o600)
    os.fchmod(fd, 0o600)
    handle = os.fdopen(fd, "r+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()}\n")
        handle.flush()
        yield True
    finally:
        handle.close()
