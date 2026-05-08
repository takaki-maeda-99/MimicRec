from __future__ import annotations
import json
from pathlib import Path
import pytest

from mimicrec.cloud.snapshot import (
    cleanup_orphan_snapshots, recover_interrupted_push,
)
from mimicrec.cloud.hub_meta import HubMeta, read_hub_meta, write_hub_meta
from mimicrec.recording.dataset_layout import init_dataset


def test_orphan_snapshots_removed(tmp_path: Path):
    orphan = tmp_path / ".push-snapshot-stale-deadbeef"
    orphan.mkdir()
    (orphan / "junk").write_text("x")
    legit = tmp_path / "legit_dataset"
    legit.mkdir()

    n = cleanup_orphan_snapshots(tmp_path)
    assert n == 1
    assert not orphan.exists()
    assert legit.exists()


def test_recover_interrupted_marks_hub_error(tmp_path: Path):
    init_dataset(tmp_path / "ds", fps=30, joint_names=["j0"], camera_names=[])
    write_hub_meta(tmp_path / "ds", HubMeta(repo_id="u/d"))
    snap = tmp_path / ".push-snapshot-ds-deadbeef"
    snap.mkdir()

    interrupted = recover_interrupted_push(tmp_path)
    assert interrupted == ["ds"]

    meta = read_hub_meta(tmp_path / "ds")
    assert meta.last_push_error == "interrupted (process restarted during push)"


def test_recover_skips_when_no_orphan(tmp_path: Path):
    init_dataset(tmp_path / "ds", fps=30, joint_names=["j0"], camera_names=[])
    write_hub_meta(tmp_path / "ds", HubMeta(repo_id="u/d"))
    interrupted = recover_interrupted_push(tmp_path)
    assert interrupted == []
    meta = read_hub_meta(tmp_path / "ds")
    assert meta.last_push_error is None
