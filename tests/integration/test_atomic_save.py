from __future__ import annotations
from pathlib import Path
import threading

import pyarrow.parquet as pq

from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.recording.metadata import append_episode


def test_concurrent_reader_never_sees_partial(tmp_path: Path):
    init_dataset(tmp_path / "ds", fps=30, joint_names=["j0"], camera_names=[])
    ds = tmp_path / "ds"
    eps_pq = ds / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    stop = threading.Event()
    errors: list[str] = []

    def writer():
        for i in range(50):
            if stop.is_set():
                return
            try:
                append_episode(ds / "meta", {"episode_index": i, "task": "t",
                                             "num_frames": 1, "duration_sec": 0.1, "cameras": []})
            except Exception as e:
                errors.append(f"writer: {e}")
                return

    def reader():
        for _ in range(200):
            if stop.is_set():
                return
            try:
                if eps_pq.exists():
                    pq.read_table(eps_pq)
            except Exception as e:
                errors.append(f"reader: {e}")
                return

    tw = threading.Thread(target=writer)
    tr = threading.Thread(target=reader)
    tw.start(); tr.start()
    tw.join(timeout=10); stop.set(); tr.join(timeout=2)
    assert not errors, errors


def test_concurrent_reader_no_partial_info_json(tmp_path: Path):
    import json
    init_dataset(tmp_path / "ds", fps=30, joint_names=["j0"], camera_names=[])
    ds = tmp_path / "ds"
    info_path = ds / "meta" / "info.json"
    stop = threading.Event()
    errors: list[str] = []

    def writer():
        for i in range(50):
            if stop.is_set():
                return
            try:
                append_episode(ds / "meta", {"episode_index": i, "task": "t",
                                             "num_frames": 1, "duration_sec": 0.1, "cameras": []})
            except Exception as e:
                errors.append(f"writer: {e}")
                return

    def reader():
        for _ in range(200):
            if stop.is_set():
                return
            try:
                if info_path.exists():
                    json.loads(info_path.read_text())
            except Exception as e:
                errors.append(f"reader: {e}")
                return

    tw = threading.Thread(target=writer)
    tr = threading.Thread(target=reader)
    tw.start(); tr.start()
    tw.join(timeout=10); stop.set(); tr.join(timeout=2)
    assert not errors, errors
