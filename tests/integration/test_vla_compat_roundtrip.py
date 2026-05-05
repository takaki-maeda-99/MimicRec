"""End-to-end roundtrip for the VLA-compat exporter.

Builds tiny synthetic datasets in tmp_path for both SO-101-like and
reBot-like adapter shapes, runs export_dataset_to_local, and verifies
the output info.json + parquet schema + stats files match what the
spec promises (and what the future X-VLA loader will need).
"""
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicrec.api.schemas import ExportFormat
from mimicrec.datasets.exporters.orchestrator import (
    ExportOverride, export_dataset_to_local,
)
from mimicrec.recording.dataset_layout import init_dataset, dataset_paths


def _write_so101_episode(ds_root: Path, episode_index: int, n: int = 16):
    p = dataset_paths(ds_root)
    chunk_dir = p.data_dir / "chunk-000"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    table = pa.table({
        "timestamp": [i / 15.0 for i in range(n)],
        "tick_t_mono_ns": [1_000_000_000 + i for i in range(n)],
        "observation.state.joint_pos": [
            [float(i), 0.0, 0.0, 0.0, 0.0, 50.0] for i in range(n)
        ],
        "observation.state.gripper_pos": [50.0] * n,
        "observation.state.ee_pos": [
            [0.1 + 0.001 * i, 0.2, 0.3] for i in range(n)
        ],
        "observation.state.ee_rotvec": [[0.0, 0.0, 0.0]] * n,
        "frame_index": list(range(n)),
        "episode_index": [episode_index] * n,
        "index": list(range(n)),
        "task_index": [0] * n,
    })
    pq.write_table(
        table, chunk_dir / f"episode_{episode_index:06d}.parquet",
    )


def _write_rebot_episode(ds_root: Path, episode_index: int, n: int = 16):
    p = dataset_paths(ds_root)
    chunk_dir = p.data_dir / "chunk-000"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    table = pa.table({
        "timestamp": [i / 15.0 for i in range(n)],
        "tick_t_mono_ns": [1_000_000_000 + i for i in range(n)],
        "observation.state.joint_pos": [
            [0.1, 0.2, 0.3, 0.4, 0.5, 0.6] for _ in range(n)
        ],
        "observation.state.gripper_pos": [0.5] * n,
        "observation.state.ee_pos": [
            [0.1 + 0.001 * i, 0.2, 0.3] for i in range(n)
        ],
        "observation.state.ee_rotvec": [[0.0, 0.0, 0.0]] * n,
        "frame_index": list(range(n)),
        "episode_index": [episode_index] * n,
        "index": list(range(n)),
        "task_index": [0] * n,
    })
    pq.write_table(
        table, chunk_dir / f"episode_{episode_index:06d}.parquet",
    )


def _bootstrap_meta(ds_root: Path, *, robot_type: str | None = None,
                    gripper_convention: dict | None = None,
                    proprio_layout: dict | None = None):
    init_dataset(
        ds_root, fps=15, joint_names=[], camera_names=[],
        robot_type=robot_type,
        gripper_convention=gripper_convention,
        proprio_layout=proprio_layout,
    )
    # Minimal episodes.parquet so build_archive_stream doesn't blow up.
    p = dataset_paths(ds_root)
    p.episodes_dir.mkdir(parents=True, exist_ok=True)
    chunk0 = p.episodes_dir / "chunk-000"
    chunk0.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table({"episode_index": [0], "tasks": [["pick up"]]}),
        chunk0 / "file-000.parquet",
    )


def test_roundtrip_so101_with_proper_metadata(tmp_path):
    ds = tmp_path / "so101_ds"
    _bootstrap_meta(
        ds,
        robot_type="SO101Adapter",
        gripper_convention={"closed_at": 0.0, "open_at": 100.0},
        proprio_layout={
            "columns": ["observation.state.joint_pos"],
            "output_names": ["shoulder_pan", "shoulder_lift", "elbow_flex",
                             "wrist_flex", "wrist_roll", "gripper"],
            "gripper_via_column": "observation.state.joint_pos",
            "gripper_index_in_column": 5,
        },
    )
    _write_so101_episode(ds, episode_index=0, n=16)

    dest = tmp_path / "out"
    result = export_dataset_to_local(
        ds_root=ds, dest_root=dest, format=ExportFormat.VLA_COMPAT,
        instruction_template="pick up", force=True,
    )

    out_meta = result.dest_path / "meta"
    info = json.loads((out_meta / "info.json").read_text())
    assert info["features"]["action"]["shape"] == [7]
    assert info["features"]["observation.state"]["shape"] == [6]
    assert info["robot_type"] == "SO101Adapter"

    for fname in ("action_stats.json", "action_stats_q99.json",
                  "proprio_stats_q99.json"):
        assert (out_meta / fname).exists(), fname

    a_stats = json.loads((out_meta / "action_stats.json").read_text())
    assert a_stats["convention"] == "q99_derived_midpoint_halfrange"
    assert len(a_stats["mean"]) == 7

    p_q99 = json.loads((out_meta / "proprio_stats_q99.json").read_text())
    assert len(p_q99["q01"]) == 6


def test_roundtrip_rebot_via_override_on_unknown_dataset(tmp_path):
    ds = tmp_path / "rebot_ds"
    _bootstrap_meta(ds)    # robot_type=unknown, no convention/layout
    _write_rebot_episode(ds, episode_index=0, n=16)

    dest = tmp_path / "out"
    result = export_dataset_to_local(
        ds_root=ds, dest_root=dest, format=ExportFormat.VLA_COMPAT,
        instruction_template="pick up", force=True,
        override=ExportOverride(robot_type="rebot"),
    )

    out_meta = result.dest_path / "meta"
    info = json.loads((out_meta / "info.json").read_text())
    assert info["robot_type"] == "ReBotArmZmqAdapter"
    assert info["features"]["observation.state"]["shape"] == [7]


def test_roundtrip_short_episode_n_equals_action_chunk_len(tmp_path):
    """Boundary: an n=8 input episode (matching X-VLA's action_chunk_len=8)
    exports out_n=7 rows successfully. The exporter is loader-agnostic;
    the future X-VLA loader is responsible for filtering exported episodes
    too short for a complete chunk (documented in spec §Goals item 6)."""
    ds = tmp_path / "short_ds"
    _bootstrap_meta(
        ds,
        robot_type="SO101Adapter",
        gripper_convention={"closed_at": 0.0, "open_at": 100.0},
        proprio_layout={
            "columns": ["observation.state.joint_pos"],
            "output_names": ["shoulder_pan", "shoulder_lift", "elbow_flex",
                             "wrist_flex", "wrist_roll", "gripper"],
            "gripper_via_column": "observation.state.joint_pos",
            "gripper_index_in_column": 5,
        },
    )
    _write_so101_episode(ds, episode_index=0, n=8)

    dest = tmp_path / "out"
    result = export_dataset_to_local(
        ds_root=ds, dest_root=dest, format=ExportFormat.VLA_COMPAT,
        instruction_template="pick up", force=True,
    )
    out_pq = result.dest_path / "data" / "chunk-000" / "episode_000000.parquet"
    table = pq.read_table(out_pq)
    assert table.num_rows == 7
