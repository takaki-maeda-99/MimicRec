from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from rebotarm_daemon.singleton import daemon_lock


def test_daemon_lock_rejects_second_owner(tmp_path):
    path = tmp_path / "daemon.lock"
    with daemon_lock(path) as first:
        with daemon_lock(path) as second:
            assert first is True
            assert second is False
    with daemon_lock(path) as after_release:
        assert after_release is True
