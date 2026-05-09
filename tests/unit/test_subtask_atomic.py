from __future__ import annotations
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicrec.annotator.subtask import save_annotations, SubtaskSegment


def _make_episode_parquet(tmp_path: Path) -> Path:
    ds = tmp_path / "ds"
    chunk = ds / "data" / "chunk-000"
    chunk.mkdir(parents=True)
    pq_path = chunk / "episode_000000.parquet"
    table = pa.table({
        "frame_index": list(range(10)),
        "episode_index": [0] * 10,
        "action": [[0.0]] * 10,
    })
    pq.write_table(table, pq_path)
    (ds / "meta" / "episodes" / "chunk-000").mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"episode_index": [0]}),
                   ds / "meta" / "episodes" / "chunk-000" / "file-000.parquet")
    return ds


def test_save_annotations_no_partial(tmp_path: Path, monkeypatch):
    ds = _make_episode_parquet(tmp_path)
    pq_path = ds / "data" / "chunk-000" / "episode_000000.parquet"
    original_bytes = pq_path.read_bytes()

    real_replace = __import__("os").replace
    def boom(src, target):
        if str(target).endswith("episode_000000.parquet"):
            raise RuntimeError("disk full")
        return real_replace(src, target)
    monkeypatch.setattr("os.replace", boom)

    segments = [SubtaskSegment(name="grasp", start_frame=0, end_frame=4, description="x")]
    with pytest.raises(RuntimeError):
        save_annotations(ds, episode_index=0, segments=segments)

    # 元 parquet が無傷
    assert pq_path.read_bytes() == original_bytes
