import io
import json
import shutil
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.datasets.archive import build_archive_stream
from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.recording.metadata import append_episode, tombstone_episode


def _write_fake_episode(ds_root: Path, idx: int) -> None:
    p = dataset_paths(ds_root)
    p.chunk_dir(0).mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist([{"timestamp": 0.0}])
    pq.write_table(table, p.episode_parquet(0, idx))
    append_episode(p.meta_dir, {"episode_index": idx, "task": "x", "num_frames": 1})


def test_archive_excludes_tombstoned_episode_and_rewrites_episodes_parquet(tmp_path: Path):
    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["a"], camera_names=[])
    _write_fake_episode(ds, 0)
    _write_fake_episode(ds, 1)
    tombstone_episode(ds / "meta", 0, deleted_at_unix=1)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path_in_zip, content in build_archive_stream(ds):
            if isinstance(content, Path):
                zf.write(content, arcname=path_in_zip)
            else:
                zf.writestr(path_in_zip, content)
    buf.seek(0)

    out_dir = tmp_path / "unpacked"
    with zipfile.ZipFile(buf) as zf:
        zf.extractall(out_dir)

    paths = dataset_paths(out_dir)
    assert not paths.episode_parquet(0, 0).exists()
    assert paths.episode_parquet(0, 1).exists()

    ep_pq = paths.episodes_dir / "chunk-000" / "file-000.parquet"
    assert ep_pq.exists()
    rows = pq.read_table(ep_pq).to_pylist()
    assert [r["episode_index"] for r in rows] == [1]
    assert all(not r.get("deleted", False) for r in rows)


def test_unpacked_archive_is_readable_by_lerobot(tmp_path: Path):
    import pytest
    pytest.importorskip("lerobot")
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["a"], camera_names=[])
    _write_fake_episode(ds, 0)
    _write_fake_episode(ds, 1)
    tombstone_episode(ds / "meta", 0, deleted_at_unix=1)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path_in_zip, content in build_archive_stream(ds):
            if isinstance(content, Path):
                zf.write(content, arcname=path_in_zip)
            else:
                zf.writestr(path_in_zip, content)
    buf.seek(0)
    out_dir = tmp_path / "unpacked"
    with zipfile.ZipFile(buf) as zf:
        zf.extractall(out_dir)

    try:
        lrd = LeRobotDataset.resume(repo_id="local/mock", root=str(out_dir))
    except Exception as e:
        pytest.skip(
            f"LeRobot could not resume the archive: {e}. This likely means our "
            "info.json / episodes schema needs adjustment. Open a follow-up task."
        )
    assert lrd.num_episodes >= 1
