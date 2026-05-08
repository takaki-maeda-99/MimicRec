from __future__ import annotations
import json
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicrec.recording.atomic_io import _atomic_write_parquet, _atomic_write_text


def test_atomic_write_text_creates_file(tmp_path: Path):
    dst = tmp_path / "info.json"
    _atomic_write_text(dst, json.dumps({"k": 1}))
    assert dst.read_text() == json.dumps({"k": 1})


def test_atomic_write_text_overwrites(tmp_path: Path):
    dst = tmp_path / "info.json"
    dst.write_text("old")
    _atomic_write_text(dst, "new")
    assert dst.read_text() == "new"


def test_atomic_write_text_tmp_cleanup_on_error(tmp_path: Path, monkeypatch):
    dst = tmp_path / "info.json"

    real_replace = __import__("os").replace
    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr("os.replace", boom)

    with pytest.raises(RuntimeError):
        _atomic_write_text(dst, "new")
    # tmp file は cleanup されている
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())


def test_atomic_write_parquet_roundtrip(tmp_path: Path):
    dst = tmp_path / "data.parquet"
    table = pa.table({"a": [1, 2, 3]})
    _atomic_write_parquet(table, dst)
    got = pq.read_table(dst)
    assert got.to_pylist() == [{"a": 1}, {"a": 2}, {"a": 3}]


def test_atomic_write_no_partial_visible(tmp_path: Path, monkeypatch):
    """tmp に書き終わるまで dst は古い内容のまま見える"""
    dst = tmp_path / "info.json"
    dst.write_text("old")

    real_replace = __import__("os").replace
    captured_tmp = {}

    def slow_replace(src, target):
        captured_tmp["src"] = src
        # replace 直前に dst を読むと old が見える
        assert dst.read_text() == "old"
        return real_replace(src, target)

    monkeypatch.setattr("os.replace", slow_replace)
    _atomic_write_text(dst, "new")
    assert dst.read_text() == "new"
