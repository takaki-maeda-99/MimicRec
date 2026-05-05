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
                  task_name: str, instruction: str | None) -> None:
    init_dataset(
        ds_root, fps=15,
        joint_names=["j1", "j2", "j3", "j4", "j5", "j6"],
        camera_names=["front"],
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
        # Also create a tiny mp4 placeholder so the orchestrator can copy it.
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
    assert result.num_frames == 8
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
    _seed_dataset(ds, num_episodes=1, num_frames=1,
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

    def flaky(*, table, instruction_text):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("synthetic mid-loop failure")
        return real_convert(table=table, instruction_text=instruction_text)

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
