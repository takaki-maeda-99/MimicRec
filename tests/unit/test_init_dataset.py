from __future__ import annotations
from pathlib import Path
import pyarrow.parquet as pq
import pytest

from mimicrec.recording.dataset_layout import init_dataset


def test_init_dataset_creates_atomic(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j0"], camera_names=[])
    assert (ds / "meta" / "info.json").exists()
    assert (ds / "meta" / "tasks.parquet").exists()
    # tmp ファイルが残っていない
    assert not any(p.name.endswith(".tmp") for p in (ds / "meta").iterdir())


def test_init_dataset_fails_when_root_exists(tmp_path: Path):
    ds = tmp_path / "ds"
    ds.mkdir()
    with pytest.raises(FileExistsError):
        init_dataset(ds, fps=30, joint_names=["j0"], camera_names=[])
