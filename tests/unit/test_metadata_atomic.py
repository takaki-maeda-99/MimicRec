from __future__ import annotations
import json
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.recording.metadata import (
    append_episode, tombstone_episode, upsert_task, update_info_totals
)


def _init_meta(tmp_path: Path) -> Path:
    meta = tmp_path / "meta"
    meta.mkdir()
    info = {"total_episodes": 0, "total_frames": 0, "total_tasks": 0,
            "fps": 30, "splits": {"train": "0:0"}, "features": {}}
    (meta / "info.json").write_text(json.dumps(info))
    pq.write_table(pa.table({"task": [], "task_index": [], "instruction": []}),
                   meta / "tasks.parquet")
    return meta


def test_append_episode_no_partial_parquet(tmp_path: Path, monkeypatch):
    """append_episode のクラッシュで episodes.parquet が partial にならない."""
    meta = _init_meta(tmp_path)
    append_episode(meta, {"episode_index": 0, "task": "t", "num_frames": 5,
                          "duration_sec": 1.0, "cameras": []})

    # 既存の episodes.parquet を確認
    pq_path = meta / "episodes" / "chunk-000" / "file-000.parquet"
    assert pq_path.exists()

    # 2 回目の append を pq.write_table 直前で例外にする
    real_pq_write = pq.write_table
    call_count = {"n": 0}

    def boom(table, path, *a, **k):
        if "file-000" in str(path):
            call_count["n"] += 1
            if call_count["n"] >= 1:
                raise RuntimeError("simulated crash")
        return real_pq_write(table, path, *a, **k)

    monkeypatch.setattr(pq, "write_table", boom)
    try:
        append_episode(meta, {"episode_index": 1, "task": "t", "num_frames": 3,
                              "duration_sec": 0.5, "cameras": []})
    except RuntimeError:
        pass

    # 元の episodes.parquet が壊れていない（episode_index=0 だけ読める）
    rows = pq.read_table(pq_path).to_pylist()
    assert len(rows) == 1
    assert rows[0]["episode_index"] == 0


def test_update_info_totals_no_partial_json(tmp_path: Path, monkeypatch):
    meta = _init_meta(tmp_path)
    info_path = meta / "info.json"
    original = info_path.read_text()

    real_replace = __import__("os").replace
    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr("os.replace", boom)

    try:
        update_info_totals(meta)
    except RuntimeError:
        pass

    # 旧 info.json が無傷で残っている
    assert info_path.read_text() == original
    # tmp が dir に残っていない
    assert not any(p.name.endswith(".tmp") for p in meta.iterdir())
