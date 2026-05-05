import pytest
from pathlib import Path
import json
import numpy as np
import pyarrow.parquet as pq

from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
from mimicrec.recording.pending import PendingEpisode
from mimicrec.recording.metadata import read_episodes


def _make_row(i: int, episode_index: int = 0, global_index: int = 0) -> dict:
    return {
        "timestamp": float(i) * 0.033,
        "tick_t_mono_ns": 1_000_000_000 + int(i * 33_000_000),
        "observation.state.joint_pos": np.array([0.0, 0.0], dtype=np.float32),
        "observation.state.joint_vel": np.array([0.0, 0.0], dtype=np.float32),
        "observation.state.joint_effort": np.array([0.0, 0.0], dtype=np.float32),
        "observation.state.t_mono_ns": 1_000_000_000 + int(i * 33_000_000),
        "action.joint_pos": np.array([0.0, 0.0], dtype=np.float32),
        "action.t_mono_ns": 1_000_000_000 + int(i * 33_000_000),
        "frame_index": i,
        "episode_index": episode_index,
        "index": global_index + i,
        "task_index": 0,
    }


def test_save_places_files_in_dataset(tmp_path: Path):
    ds = tmp_path / "datasets" / "mock"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=[])

    pe = PendingEpisode.open(ds, episode_index=0)
    for i in range(5):
        pe.append_row(_make_row(i))
    pe.finalize()
    pe.save(
        metadata_extra={
            "episode_index": 0,
            "task": "pick",
            "instruction": "pick the block",
            "robot": "mock", "teleop": "mock_leader", "mapper": "identity",
            "cameras": [], "mode": "teleop", "fps": 30,
            "success": None, "comment": None,
            "start_t_mono_ns": 1_000_000_000, "end_t_mono_ns": 1_132_000_000,
            "duration_sec": 0.132, "num_frames": 5,
            "session_boot_t_unix": 1700000000, "session_boot_t_mono_ns": 1_000_000_000,
            "resolved_config": {},
        }
    )

    paths = dataset_paths(ds)
    assert (paths.data_dir / "chunk-000" / "episode_000000.parquet").exists()
    assert not (ds / ".pending").exists() or not any((ds / ".pending").iterdir())
    rows = list(read_episodes(paths.meta_dir))
    assert rows[0]["episode_index"] == 0
    table = pq.read_table(paths.data_dir / "chunk-000" / "episode_000000.parquet")
    assert table.num_rows == 5


def test_info_video_path_uses_file_index_placeholder(tmp_path: Path):
    """LeRobot calls video_path.format(video_key=..., chunk_index=..., file_index=...).
    {episode_index} placeholder raises KeyError on load; use {file_index} instead."""
    import json

    ds = tmp_path / "ds"
    init_dataset(ds, fps=30, joint_names=["j1"], camera_names=["front"])
    info = json.loads((ds / "meta" / "info.json").read_text())
    rendered = info["video_path"].format(video_key="observation.images.front",
                                         chunk_index=0, file_index=0)
    assert rendered == "videos/observation.images.front/chunk-000/episode_000000.mp4"


def test_saved_video_layout_matches_lerobot_v3_spec(tmp_path: Path):
    """LeRobot v3 spec: videos/{video_key}/chunk-XXX/episode_XXXXXX.mp4
    (not videos/chunk-XXX/{video_key}/...). info.json video_path placeholder
    uses {video_key}/{chunk_index}/{file_index}, so on-disk must match."""
    ds = tmp_path / "datasets" / "mock"
    init_dataset(ds, fps=30, joint_names=["j1"], camera_names=["front"])

    pe = PendingEpisode.open(ds, episode_index=0)
    pe.open_video_writers(fps=30, cameras={"front": (64, 48)})
    # Write one black frame so the mp4 file exists.
    pe._video_writers["front"].write_frame(np.zeros((48, 64, 3), dtype=np.uint8))
    pe.append_row(_make_row(0))
    pe.finalize()
    pe.save(metadata_extra={
        "episode_index": 0, "task": "pick", "instruction": "pick", "robot": "mock",
        "teleop": "mock_leader", "mapper": "identity", "cameras": ["front"], "mode": "teleop",
        "fps": 30, "success": None, "comment": None,
        "start_t_mono_ns": 0, "end_t_mono_ns": 0, "duration_sec": 1 / 30, "num_frames": 1,
        "session_boot_t_unix": 0, "session_boot_t_mono_ns": 0, "resolved_config": {},
    })

    spec_path = ds / "videos" / "observation.images.front" / "chunk-000" / "episode_000000.mp4"
    legacy_path = ds / "videos" / "chunk-000" / "observation.images.front" / "episode_000000.mp4"
    assert spec_path.exists(), f"expected mp4 at {spec_path}"
    assert not legacy_path.exists()


def test_saved_parquet_has_idealized_timestamp(tmp_path: Path):
    """LeRobot v3 / decode_video_frames require timestamp = frame_index / fps
    so parquet rows align with constant-fps mp4 frames (tolerance 0.0001 s).
    Wall-clock timestamps cause FrameTimestampError on load."""
    import pyarrow as pa

    ds = tmp_path / "datasets" / "mock"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=[])

    pe = PendingEpisode.open(ds, episode_index=0)
    for i in range(5):
        pe.append_row(_make_row(i))
    pe.finalize()
    pe.save(metadata_extra={
        "episode_index": 0, "task": "pick", "instruction": "pick", "robot": "mock",
        "teleop": "mock_leader", "mapper": "identity", "cameras": [], "mode": "teleop",
        "fps": 30, "success": None, "comment": None,
        "start_t_mono_ns": 0, "end_t_mono_ns": 0, "duration_sec": 5 / 30, "num_frames": 5,
        "session_boot_t_unix": 0, "session_boot_t_mono_ns": 0, "resolved_config": {},
    })

    paths = dataset_paths(ds)
    table = pq.read_table(paths.data_dir / "chunk-000" / "episode_000000.parquet")
    timestamps = table.column("timestamp").to_pylist()
    expected = [i / 30 for i in range(5)]
    assert timestamps == pytest.approx(expected, abs=1e-6)
    assert table.schema.field("timestamp").type == pa.float32()


def test_saved_parquet_index_is_dataset_absolute(tmp_path: Path):
    """LeRobot v3 spec: index = dataset_from_index + frame_index (cumulative
    across episodes). Currently writer hardcodes index=0 for all rows;
    delta_timestamps chunk fetching breaks (KeyError) without this."""
    ds = tmp_path / "datasets" / "mock"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=[])

    common_meta = {
        "task": "pick", "instruction": "pick", "robot": "mock",
        "teleop": "mock_leader", "mapper": "identity", "cameras": [], "mode": "teleop",
        "fps": 30, "success": None, "comment": None,
        "start_t_mono_ns": 0, "end_t_mono_ns": 0, "session_boot_t_unix": 0,
        "session_boot_t_mono_ns": 0, "resolved_config": {},
    }

    # Episode 0: 4 frames
    pe = PendingEpisode.open(ds, episode_index=0)
    for i in range(4):
        pe.append_row(_make_row(i, episode_index=0))
    pe.finalize()
    pe.save(metadata_extra={**common_meta, "episode_index": 0,
                            "duration_sec": 4 / 30, "num_frames": 4})

    # Episode 1: 3 frames; should be indexed 4..6
    pe = PendingEpisode.open(ds, episode_index=1)
    for i in range(3):
        pe.append_row(_make_row(i, episode_index=1))
    pe.finalize()
    pe.save(metadata_extra={**common_meta, "episode_index": 1,
                            "duration_sec": 3 / 30, "num_frames": 3})

    paths = dataset_paths(ds)
    table0 = pq.read_table(paths.data_dir / "chunk-000" / "episode_000000.parquet")
    table1 = pq.read_table(paths.data_dir / "chunk-000" / "episode_000001.parquet")
    assert table0.column("index").to_pylist() == [0, 1, 2, 3]
    assert table1.column("index").to_pylist() == [4, 5, 6]


def test_finalize_writes_timestamp_as_float32(tmp_path: Path):
    """LeRobot v3 spec / our info.json declare timestamp as float32. The default
    pa.Table.from_pylist infers float64 from Python floats, so finalize() must
    cast explicitly. Mismatch causes LeRobotDataset.load_hf_dataset CastError."""
    import pyarrow as pa

    ds = tmp_path / "datasets" / "mock"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=[])

    pe = PendingEpisode.open(ds, episode_index=0)
    for i in range(3):
        pe.append_row(_make_row(i))
    pe.finalize()

    stage_pq = pe.stage_dir / "episode_000000.parquet"
    table = pq.read_table(stage_pq)
    assert table.schema.field("timestamp").type == pa.float32()


def test_discard_removes_pending_and_does_not_touch_dataset(tmp_path: Path):
    ds = tmp_path / "datasets" / "mock"
    init_dataset(ds, fps=30, joint_names=["j1", "j2"], camera_names=[])

    pe = PendingEpisode.open(ds, episode_index=0)
    pe.append_row(_make_row(0))
    pe.finalize()
    pe.discard()

    paths = dataset_paths(ds)
    assert not (paths.data_dir / "chunk-000" / "episode_000000.parquet").exists()
    assert list(read_episodes(paths.meta_dir)) == []


def test_saved_dataset_is_readable_by_lerobot(tmp_path: Path):
    """Spike decision: our raw parquet + metadata output is LeRobot-compatible."""
    pytest.importorskip("lerobot")

    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    ds_root = tmp_path / "datasets" / "mock"
    init_dataset(ds_root, fps=30, joint_names=["j1", "j2"], camera_names=[])
    pe = PendingEpisode.open(ds_root, episode_index=0)
    for i in range(5):
        pe.append_row(_make_row(i))
    pe.finalize()
    pe.save(metadata_extra={
        "episode_index": 0, "task": "pick", "instruction": "pick", "robot": "mock",
        "teleop": "mock_leader", "mapper": "identity", "cameras": [], "mode": "teleop",
        "fps": 30, "success": None, "comment": None,
        "start_t_mono_ns": 0, "end_t_mono_ns": 0, "duration_sec": 0.0, "num_frames": 5,
        "session_boot_t_unix": 0, "session_boot_t_mono_ns": 0, "resolved_config": {},
    })

    ds = LeRobotDataset.resume(repo_id="local/mock", root=str(ds_root))
    assert ds.num_episodes >= 1
