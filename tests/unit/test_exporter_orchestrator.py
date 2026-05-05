import json
from pathlib import Path
from unittest.mock import MagicMock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicrec.api.deps import get_vla_dest_root
from mimicrec.api.schemas import ExportFormat, DEFAULT_INSTRUCTION_TEMPLATE
from mimicrec.datasets.exporters.errors import DestinationExistsError
from mimicrec.datasets.exporters.orchestrator import export_dataset_to_local
from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.recording.metadata import append_episode, upsert_task


def _fake_app(state_value=None):
    app = MagicMock()
    app.state = MagicMock()
    app.state.vla_dest_root = state_value
    return app


def test_vla_dest_root_default(monkeypatch):
    monkeypatch.delenv("MIMICREC_VLA_DEST_ROOT", raising=False)
    app = _fake_app(state_value=None)
    assert get_vla_dest_root(app) == Path("~/vla-gemma-4/data/local").expanduser()


def test_vla_dest_root_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MIMICREC_VLA_DEST_ROOT", str(tmp_path))
    app = _fake_app(state_value=None)
    assert get_vla_dest_root(app) == tmp_path.expanduser()


def test_vla_dest_root_state_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MIMICREC_VLA_DEST_ROOT", "/should/be/ignored")
    app = _fake_app(state_value=tmp_path)
    assert get_vla_dest_root(app) == tmp_path


def _seed_dataset(ds_root: Path, *, num_episodes: int, num_frames: int,
                  task_name: str, instruction: str | None,
                  robot_type: str | None = "SO101Adapter") -> None:
    if robot_type == "SO101Adapter":
        gc_dict = {"closed_at": 0.0, "open_at": 100.0}
        pl_dict = {
            "columns": ["observation.state.joint_pos"],
            "output_names": ["shoulder_pan", "shoulder_lift", "elbow_flex",
                             "wrist_flex", "wrist_roll", "gripper"],
            "gripper_via_column": "observation.state.joint_pos",
            "gripper_index_in_column": 5,
        }
    else:
        gc_dict = None
        pl_dict = None
    init_dataset(
        ds_root, fps=15,
        joint_names=["j1", "j2", "j3", "j4", "j5", "j6"],
        camera_names=["front"],
        robot_type=robot_type,
        gripper_convention=gc_dict,
        proprio_layout=pl_dict,
    )
    p = dataset_paths(ds_root)
    upsert_task(p.meta_dir, task_name, instruction or "")
    for idx in range(num_episodes):
        chunk_dir = p.chunk_dir(0)
        chunk_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for f in range(num_frames):
            rows.append({
                "timestamp": f * (1.0 / 15),
                "tick_t_mono_ns": 0,
                "observation.state.joint_pos": [0.1] * 6,
                "observation.state.joint_vel": [0.0] * 6,
                "observation.state.joint_effort": [0.0] * 6,
                "observation.state.t_mono_ns": 0,
                "observation.state.gripper_pos": 0.5,
                "observation.state.ee_pos": [0.1 + 0.001 * f, 0.2, 0.3],
                "observation.state.ee_rotvec": [0.0, 0.0, 0.0],
                "action.joint_pos": [0.2] * 6,
                "action.t_mono_ns": 0,
                "action.gripper_pos": 0.7,
                "frame_index": f,
                "episode_index": idx,
                "index": idx * num_frames + f,
                "task_index": 0,
                "observation.images.front.video_frame_index": f,
                "observation.images.front.t_mono_ns": 0,
            })
        pq.write_table(pa.Table.from_pylist(rows), p.episode_parquet(0, idx))
        cam_dir = p.videos_dir / "observation.images.front" / "chunk-000"
        cam_dir.mkdir(parents=True, exist_ok=True)
        (cam_dir / f"episode_{idx:06d}.mp4").write_bytes(b"\x00fake\x00")
        append_episode(p.meta_dir, {
            "episode_index": idx, "task": task_name,
            "num_frames": num_frames, "robot": "so101", "mode": "teleop",
            "cameras": ["front"],
        })


def test_vla_compat_export_writes_full_tree(tmp_path: Path):
    ds = tmp_path / "ds_in"
    dest_root = tmp_path / "dest"
    _seed_dataset(ds, num_episodes=2, num_frames=4,
                  task_name="tape_on_bottle",
                  instruction="Pick up the tape and place it on the bottle")

    result = export_dataset_to_local(
        ds_root=ds,
        dest_root=dest_root,
        format=ExportFormat.VLA_COMPAT,
        instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
        force=False,
    )

    out = dest_root / "ds_in"
    assert (out / "meta" / "info.json").exists()
    assert (out / "meta" / "action_stats.json").exists()
    assert (out / "meta" / "tasks.parquet").exists()
    assert (out / "data" / "chunk-000" / "episode_000000.parquet").exists()
    assert (out / "data" / "chunk-000" / "episode_000001.parquet").exists()
    assert (out / "videos" / "observation.images.front" / "chunk-000" / "episode_000000.mp4").exists()

    info = json.loads((out / "meta" / "info.json").read_text())
    assert info["features"]["action"]["shape"] == [7]
    assert info["features"]["language_instruction"]["dtype"] == "string"

    stats = json.loads((out / "meta" / "action_stats.json").read_text())
    assert len(stats["mean"]) == 7 and len(stats["std"]) == 7

    table = pq.read_table(out / "data" / "chunk-000" / "episode_000000.parquet")
    assert "action" in table.column_names
    assert "language_instruction" in table.column_names
    li = table.column("language_instruction").to_pylist()
    assert all("Pick up the tape and place it on the bottle" in row for row in li)

    assert result.num_episodes == 2
    assert result.num_frames == 6  # convert_episode_table drops last frame: 4-1=3 rows × 2 eps
    assert result.dest_path == out
    assert result.warnings == []


def test_vla_compat_export_warns_when_instruction_missing(tmp_path: Path):
    ds = tmp_path / "ds_in"
    dest_root = tmp_path / "dest"
    _seed_dataset(ds, num_episodes=1, num_frames=2,
                  task_name="t1", instruction="")
    result = export_dataset_to_local(
        ds_root=ds, dest_root=dest_root,
        format=ExportFormat.VLA_COMPAT,
        instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
        force=False,
    )
    assert any("missing_instruction" in w for w in result.warnings)


def test_export_refuses_when_dest_exists_without_force(tmp_path: Path):
    ds = tmp_path / "ds_in"
    dest_root = tmp_path / "dest"
    _seed_dataset(ds, num_episodes=1, num_frames=1,
                  task_name="t1", instruction="i")
    (dest_root / "ds_in").mkdir(parents=True)
    with pytest.raises(DestinationExistsError):
        export_dataset_to_local(
            ds_root=ds, dest_root=dest_root,
            format=ExportFormat.VLA_COMPAT,
            instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
            force=False,
        )


def test_export_overwrites_when_force_true(tmp_path: Path):
    ds = tmp_path / "ds_in"
    dest_root = tmp_path / "dest"
    _seed_dataset(ds, num_episodes=1, num_frames=2,
                  task_name="t1", instruction="i")
    out = dest_root / "ds_in"
    out.mkdir(parents=True)
    (out / "leftover.txt").write_text("stale")

    export_dataset_to_local(
        ds_root=ds, dest_root=dest_root,
        format=ExportFormat.VLA_COMPAT,
        instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
        force=True,
    )
    assert not (out / "leftover.txt").exists()
    assert (out / "meta" / "info.json").exists()


def test_lerobot_v3_native_format_also_supported_via_local_path(tmp_path: Path):
    ds = tmp_path / "ds_in"
    dest_root = tmp_path / "dest"
    _seed_dataset(ds, num_episodes=1, num_frames=1,
                  task_name="t1", instruction="i")
    export_dataset_to_local(
        ds_root=ds, dest_root=dest_root,
        format=ExportFormat.LEROBOT_V3_NATIVE,
        instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
        force=False,
    )
    out = dest_root / "ds_in"
    assert (out / "meta" / "info.json").exists()
    assert (out / "data" / "chunk-000" / "episode_000000.parquet").exists()


def test_export_cleans_up_partial_on_mid_loop_failure(tmp_path: Path, monkeypatch):
    """If convert_episode_table raises on a later episode, no partial tree
    should survive at <dest>/<ds_name> nor at <dest>/<ds_name>.partial."""
    ds = tmp_path / "ds_in"
    dest_root = tmp_path / "dest"
    _seed_dataset(ds, num_episodes=3, num_frames=2,
                  task_name="t1", instruction="i")

    from mimicrec.datasets.exporters import orchestrator as orch_mod

    real_convert = orch_mod.convert_episode_table
    call_count = {"n": 0}

    def flaky(*, table, instruction_text, gripper_convention, proprio_layout):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("synthetic mid-loop failure")
        return real_convert(
            table=table, instruction_text=instruction_text,
            gripper_convention=gripper_convention, proprio_layout=proprio_layout,
        )

    monkeypatch.setattr(orch_mod, "convert_episode_table", flaky)

    with pytest.raises(RuntimeError, match="synthetic"):
        export_dataset_to_local(
            ds_root=ds, dest_root=dest_root,
            format=ExportFormat.VLA_COMPAT,
            instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
            force=False,
        )

    # No partial directory should remain after failure.
    assert not (dest_root / "ds_in").exists(), \
        "out_dir must not exist after mid-export failure"
    assert not (dest_root / "ds_in.partial").exists(), \
        "partial dir must be cleaned up on failure"


# === New tests for ee_delta refactor ===

from mimicrec.datasets.exporters.orchestrator import ExportOverride


def test_orchestrator_fails_when_robot_type_unknown_and_no_override(tmp_path):
    ds = tmp_path / "src"
    _seed_dataset(
        ds, num_episodes=1, num_frames=4,
        task_name="pick", instruction="pick up the bottle",
        robot_type=None,    # produces info.json with robot_type='unknown'
    )
    with pytest.raises(ValueError, match="robot_type='unknown'"):
        export_dataset_to_local(
            ds_root=ds, dest_root=tmp_path / "out",
            format=ExportFormat.VLA_COMPAT,
            instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
            force=True,
        )


def test_orchestrator_uses_override_when_provided(tmp_path):
    ds = tmp_path / "src"
    _seed_dataset(
        ds, num_episodes=1, num_frames=4,
        task_name="pick", instruction="pick up the bottle",
        robot_type=None,    # legacy unknown dataset
    )
    result = export_dataset_to_local(
        ds_root=ds, dest_root=tmp_path / "out",
        format=ExportFormat.VLA_COMPAT,
        instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
        force=True,
        override=ExportOverride(robot_type="so101"),
    )
    info = json.loads((result.dest_path / "meta" / "info.json").read_text())
    assert info["robot_type"] == "SO101Adapter"


def test_orchestrator_raises_on_inconsistent_proprio_dim_across_episodes(
    tmp_path, monkeypatch,
):
    """Force two synthetic episodes whose converted observation.state widths
    disagree by monkey-patching convert_episode_table to alternate per call."""
    ds = tmp_path / "src"
    _seed_dataset(
        ds, num_episodes=2, num_frames=4,
        task_name="pick", instruction="pick up the bottle",
    )

    import pyarrow as pa
    import itertools
    from mimicrec.datasets.exporters import orchestrator as orch_mod
    from mimicrec.datasets.exporters.vla_compat import ConvertedEpisode

    widths = itertools.cycle([6, 7])

    def fake_convert(*, table, instruction_text, gripper_convention, proprio_layout):
        n = max(table.num_rows - 1, 1)
        w = next(widths)
        out = pa.table({
            "action": pa.array([[0.0]*7]*n, type=pa.list_(pa.float32(), 7)),
            "observation.state": pa.array(
                [[0.0]*w]*n, type=pa.list_(pa.float32(), w),
            ),
            "language_instruction": pa.array([instruction_text]*n, type=pa.string()),
            "timestamp": pa.array([0.0]*n, type=pa.float32()),
            "frame_index": pa.array(list(range(n)), type=pa.int64()),
            "episode_index": pa.array([0]*n, type=pa.int64()),
            "index": pa.array(list(range(n)), type=pa.int64()),
            "task_index": pa.array([0]*n, type=pa.int64()),
        })
        return ConvertedEpisode(table=out)

    monkeypatch.setattr(orch_mod, "convert_episode_table", fake_convert)

    with pytest.raises(ValueError, match="observation.state dim"):
        export_dataset_to_local(
            ds_root=ds, dest_root=tmp_path / "out",
            format=ExportFormat.VLA_COMPAT,
            instruction_template=DEFAULT_INSTRUCTION_TEMPLATE,
            force=True,
            override=ExportOverride(robot_type="so101"),
        )
