from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import sys

from so101_daemon.config import load_daemon_config
from so101_daemon.server import run_server


@contextmanager
def daemon_lock(path: str | None):
    if path is None:
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        path = str(Path(runtime_dir) / "mimicrec-so101-daemon.lock")
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("w")
    acquired = False
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            pass
        yield acquired
    finally:
        if acquired:
            fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="SO-101 safety daemon")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = load_daemon_config(args.config)
    with daemon_lock(config.lock_path) as acquired:
        if not acquired:
            print("SO-101 daemon is already running", file=sys.stderr)
            return 2
        run_server(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
