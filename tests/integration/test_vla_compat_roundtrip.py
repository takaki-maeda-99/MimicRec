from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from mimicrec.api.schemas import ExportFormat, DEFAULT_INSTRUCTION_TEMPLATE
from mimicrec.datasets.exporters.orchestrator import export_dataset_to_local
from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.recording.metadata import append_episode, upsert_task


def _seed(ds: Path):
    init_dataset(ds, fps=15,
                 joint_names=["j1","j2","j3","j4","j5","j6"], camera_names=["front"])
    p = dataset_paths(ds)
    upsert_task(p.meta_dir, "tape_on_bottle",
                "Pick up the tape and place it on the bottle")
    rows = []
    for f in range(8):
        rows.append({
            "timestamp": f / 15.0,
            "tick_t_mono_ns": 0,
            "observation.state.joint_pos": [0.1] * 6,
            "observation.state.joint_vel": [0.0] * 6,
            "observation.state.joint_effort": [0.0] * 6,
            "observation.state.t_mono_ns": 0,
            "observation.state.gripper_pos": 0.5,
            "action.joint_pos": [0.2] * 6,
            "action.t_mono_ns": 0,
            "action.gripper_pos": 0.7,
            "frame_index": f, "episode_index": 0, "index": f, "task_index": 0,
            "observation.images.front.video_frame_index": f,
            "observation.images.front.t_mono_ns": 0,
        })
    p.chunk_dir(0).mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), p.episode_parquet(0, 0))
    cam_dir = p.videos_dir / "observation.images.front" / "chunk-000"
    cam_dir.mkdir(parents=True, exist_ok=True)
    (cam_dir / "episode_000000.mp4").write_bytes(b"\x00")
    append_episode(p.meta_dir, {
        "episode_index": 0, "task": "tape_on_bottle",
        "num_frames": 8, "robot": "so101", "mode": "teleop",
        "cameras": ["front"],
    })


def test_vla_compat_export_produces_loadable_parquet_and_metadata(tmp_path: Path):
    ds = tmp_path / "ds"
    dest = tmp_path / "dest"
    _seed(ds)

    result = export_dataset_to_local(
        ds_root=ds, dest_root=dest,
        format=ExportFormat.VLA_COMPAT,
        instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
        force=False,
    )

    out = dest / "ds"
    pq_path = out / "data" / "chunk-000" / "episode_000000.parquet"
    table = pq.read_table(pq_path)

    # Schema invariants the VLA loader cares about.
    assert "action" in table.column_names
    assert "observation.state" in table.column_names
    assert "language_instruction" in table.column_names

    actions = np.array(table.column("action").to_pylist(), dtype=np.float32)
    states = np.array(table.column("observation.state").to_pylist(), dtype=np.float32)
    assert actions.shape == (8, 7)
    assert states.shape == (8, 7)

    # language_instruction expanded from template + tasks.parquet.instruction.
    li = table.column("language_instruction").to_pylist()
    assert all("Pick up the tape and place it on the bottle" in s for s in li)
    assert all(s.startswith("What action should the robot take to ") for s in li)

    # info.json reflects the new shapes.
    info = json.loads((out / "meta" / "info.json").read_text())
    assert info["features"]["action"]["shape"] == [7]
    assert info["features"]["observation.state"]["shape"] == [7]
    assert info["features"]["language_instruction"]["dtype"] == "string"

    # action_stats.json present and well-shaped.
    stats = json.loads((out / "meta" / "action_stats.json").read_text())
    assert len(stats["mean"]) == 7
    assert len(stats["std"]) == 7
    assert all(s > 0 for s in stats["std"])

    # Video copied verbatim.
    assert (out / "videos" / "observation.images.front" / "chunk-000" / "episode_000000.mp4").exists()

    # Tasks.parquet preserved.
    tasks_table = pq.read_table(out / "meta" / "tasks.parquet")
    assert "tape_on_bottle" in tasks_table.column("task").to_pylist()

    # Result fields.
    assert result.num_episodes == 1
    assert result.num_frames == 8
    assert result.warnings == []
