from __future__ import annotations
import threading
import time
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.cloud.push_state import PushCoordinator
from mimicrec.recording.metadata import append_episode, update_info_totals
from mimicrec.recording.dataset_layout import init_dataset


def test_append_episode_acquires_save_lock(tmp_path: Path):
    init_dataset(tmp_path / "ds", fps=30, joint_names=["j0"], camera_names=[])
    ds = tmp_path / "ds"
    coord = PushCoordinator()
    save_lock = coord.get_save_lock("ds")

    holder_released = threading.Event()
    started = threading.Event()
    completed = threading.Event()

    def hold():
        with save_lock:
            started.set()
            holder_released.wait(timeout=2.0)

    def caller():
        append_episode(
            ds / "meta",
            {"episode_index": 0, "task": "t", "num_frames": 1, "duration_sec": 0.1, "cameras": []},
            coordinator=coord, ds_name="ds",
        )
        completed.set()

    t1 = threading.Thread(target=hold)
    t1.start()
    started.wait(timeout=1.0)
    t2 = threading.Thread(target=caller)
    t2.start()
    assert not completed.wait(timeout=0.3)
    holder_released.set()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)
    assert completed.is_set()


def test_append_episode_without_coordinator_works(tmp_path: Path):
    """後方互換: coordinator/ds_name を渡さなくても動く"""
    init_dataset(tmp_path / "ds", fps=30, joint_names=["j0"], camera_names=[])
    ds = tmp_path / "ds"
    append_episode(
        ds / "meta",
        {"episode_index": 0, "task": "t", "num_frames": 1, "duration_sec": 0.1, "cameras": []},
    )
    rows = pq.read_table(ds / "meta" / "episodes" / "chunk-000" / "file-000.parquet").to_pylist()
    assert len(rows) == 1


def test_nested_call_under_rlock_no_deadlock(tmp_path: Path):
    """append_episode が内部で update_info_totals を呼んでも RLock で deadlock しない"""
    init_dataset(tmp_path / "ds", fps=30, joint_names=["j0"], camera_names=[])
    ds = tmp_path / "ds"
    coord = PushCoordinator()
    append_episode(
        ds / "meta",
        {"episode_index": 0, "task": "t", "num_frames": 1, "duration_sec": 0.1, "cameras": []},
        coordinator=coord, ds_name="ds",
    )
