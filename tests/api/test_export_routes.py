from __future__ import annotations
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_export_vla_compat_writes_to_state_override(tmp_path: Path, app: FastAPI, monkeypatch):
    # Arrange dataset and dest paths via app state.
    import pyarrow as pa
    import pyarrow.parquet as pq
    from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
    from mimicrec.recording.metadata import append_episode, upsert_task
    ds_root = tmp_path / "datasets" / "ds7"
    init_dataset(ds_root, fps=15,
                 joint_names=["j1","j2","j3","j4","j5","j6"], camera_names=["front"])
    p = dataset_paths(ds_root)
    upsert_task(p.meta_dir, "pick cube", "pick the cube")
    chunk_dir = p.chunk_dir(0)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    rows = [{"timestamp": i/15, "tick_t_mono_ns": 0,
             "observation.state.joint_pos": [0.1]*6, "observation.state.joint_vel": [0.0]*6,
             "observation.state.joint_effort": [0.0]*6, "observation.state.t_mono_ns": 0,
             "observation.state.gripper_pos": 0.5, "observation.state.ee_pos": [0.1, 0.2, 0.3],
             "observation.state.ee_rotvec": [0.0, 0.0, 0.0], "action.joint_pos": [0.2]*6,
             "action.t_mono_ns": 0, "action.gripper_pos": 0.7,
             "frame_index": i, "episode_index": 0, "index": i, "task_index": 0,
             "observation.images.front.video_frame_index": i, "observation.images.front.t_mono_ns": 0}
            for i in range(2)]
    pq.write_table(pa.Table.from_pylist(rows), p.episode_parquet(0, 0))
    cam_dir = p.videos_dir / "observation.images.front" / "chunk-000"
    cam_dir.mkdir(parents=True, exist_ok=True)
    (cam_dir / "episode_000000.mp4").write_bytes(b"\x00fake\x00")
    append_episode(p.meta_dir, {"episode_index": 0, "task": "pick cube",
                                "num_frames": 2, "robot": "so101", "mode": "teleop",
                                "cameras": ["front"]})
    app.state.datasets_root = tmp_path / "datasets"
    app.state.vla_dest_root = tmp_path / "vla"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/datasets/ds7/export", json={
            "format": "vla_compat",
            "instruction_template": "What action should the robot take to {TASK}? A:",
            "force": False,
            "robot_type": "so101",
        })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["format"] == "vla_compat"
    assert Path(body["dest_path"]).is_absolute()
    assert (Path(body["dest_path"]) / "meta" / "info.json").exists()


@pytest.mark.asyncio
async def test_export_returns_404_when_dataset_missing(app: FastAPI, tmp_path: Path):
    app.state.datasets_root = tmp_path
    app.state.vla_dest_root = tmp_path / "vla"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/datasets/nope/export", json={"format": "vla_compat"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_export_returns_409_when_dest_exists_no_force(app: FastAPI, tmp_path: Path):
    from mimicrec.recording.dataset_layout import init_dataset
    ds_root = tmp_path / "datasets" / "ds_existing"
    init_dataset(ds_root, fps=15,
                 joint_names=["j1","j2","j3","j4","j5","j6"], camera_names=[])
    app.state.datasets_root = tmp_path / "datasets"
    app.state.vla_dest_root = tmp_path / "vla"
    (tmp_path / "vla" / "ds_existing").mkdir(parents=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/datasets/ds_existing/export", json={"format": "vla_compat"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_export_with_force_overwrites(app: FastAPI, tmp_path: Path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
    from mimicrec.recording.metadata import append_episode, upsert_task
    ds_root = tmp_path / "datasets" / "ds_force"
    init_dataset(ds_root, fps=15,
                 joint_names=["j1","j2","j3","j4","j5","j6"], camera_names=[])
    p = dataset_paths(ds_root)
    upsert_task(p.meta_dir, "pick cube", "pick the cube")
    chunk_dir = p.chunk_dir(0)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    rows = [{"timestamp": i/15, "tick_t_mono_ns": 0,
             "observation.state.joint_pos": [0.1]*6, "observation.state.joint_vel": [0.0]*6,
             "observation.state.joint_effort": [0.0]*6, "observation.state.t_mono_ns": 0,
             "observation.state.gripper_pos": 0.5, "observation.state.ee_pos": [0.1, 0.2, 0.3],
             "observation.state.ee_rotvec": [0.0, 0.0, 0.0], "action.joint_pos": [0.2]*6,
             "action.t_mono_ns": 0, "action.gripper_pos": 0.7,
             "frame_index": i, "episode_index": 0, "index": i, "task_index": 0}
            for i in range(2)]
    pq.write_table(pa.Table.from_pylist(rows), p.episode_parquet(0, 0))
    append_episode(p.meta_dir, {"episode_index": 0, "task": "pick cube",
                                "num_frames": 2, "robot": "so101", "mode": "teleop",
                                "cameras": []})
    app.state.datasets_root = tmp_path / "datasets"
    app.state.vla_dest_root = tmp_path / "vla"
    (tmp_path / "vla" / "ds_force").mkdir(parents=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/datasets/ds_force/export",
                          json={"format": "vla_compat", "force": True, "robot_type": "so101"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_export_route_accepts_robot_type_override(app: FastAPI, tmp_path: Path):
    """Legacy datasets (info.json robot_type=unknown) must export
    successfully when the request body carries robot_type='so101'."""
    import json
    import pyarrow as pa
    import pyarrow.parquet as pq
    from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
    from mimicrec.recording.metadata import append_episode, upsert_task
    from mimicrec.api.deps import get_vla_dest_root

    ds_name = "legacy_so101"
    ds_root = tmp_path / "datasets" / ds_name
    # robot_type not passed → info.json gets robot_type='unknown'
    init_dataset(ds_root, fps=15,
                 joint_names=["j1", "j2", "j3", "j4", "j5", "j6"], camera_names=["front"])
    p = dataset_paths(ds_root)
    upsert_task(p.meta_dir, "pick cube", "pick the cube")

    # Seed 2 frames so n_proprio can be derived
    chunk_dir = p.chunk_dir(0)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "timestamp": i * (1.0 / 15),
            "tick_t_mono_ns": 0,
            "observation.state.joint_pos": [0.1] * 6,
            "observation.state.joint_vel": [0.0] * 6,
            "observation.state.joint_effort": [0.0] * 6,
            "observation.state.t_mono_ns": 0,
            "observation.state.gripper_pos": 0.5,
            "observation.state.ee_pos": [0.1, 0.2, 0.3],
            "observation.state.ee_rotvec": [0.0, 0.0, 0.0],
            "action.joint_pos": [0.2] * 6,
            "action.t_mono_ns": 0,
            "action.gripper_pos": 0.7,
            "frame_index": i,
            "episode_index": 0,
            "index": i,
            "task_index": 0,
            "observation.images.front.video_frame_index": i,
            "observation.images.front.t_mono_ns": 0,
        }
        for i in range(2)
    ]
    pq.write_table(pa.Table.from_pylist(rows), p.episode_parquet(0, 0))
    cam_dir = p.videos_dir / "observation.images.front" / "chunk-000"
    cam_dir.mkdir(parents=True, exist_ok=True)
    (cam_dir / "episode_000000.mp4").write_bytes(b"\x00fake\x00")
    append_episode(p.meta_dir, {
        "episode_index": 0, "task": "pick cube",
        "num_frames": 2, "robot": "so101", "mode": "teleop",
        "cameras": ["front"],
    })

    app.state.datasets_root = tmp_path / "datasets"
    app.state.vla_dest_root = tmp_path / "vla"

    # Confirm pre-condition: robot_type is unknown before export
    info_before = json.loads((ds_root / "meta" / "info.json").read_text())
    assert info_before["robot_type"] == "unknown"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        resp = await ac.post(
            f"/api/datasets/{ds_name}/export",
            json={
                "format": "vla_compat",
                "instruction_template": "{task}",
                "force": True,
                "robot_type": "so101",
            },
        )
    assert resp.status_code == 200, resp.text

    dest_root = get_vla_dest_root(app)
    info = json.loads((dest_root / ds_name / "meta" / "info.json").read_text())
    assert info["robot_type"] == "SO101Adapter"


@pytest.mark.asyncio
async def test_archive_vla_compat_returns_zip_so101(app: FastAPI, tmp_path: Path):
    """GET /archive?format=vla_compat should stream a zip containing
    the converted VLA-compat tree. No tempdir or dest_path leaked."""
    import io
    import zipfile
    import pyarrow as pa
    import pyarrow.parquet as pq
    from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
    from mimicrec.recording.metadata import append_episode, upsert_task

    ds_name = "ds_zip_so101"
    ds_root = tmp_path / "datasets" / ds_name
    init_dataset(ds_root, fps=15,
                 joint_names=["j1", "j2", "j3", "j4", "j5", "j6"],
                 camera_names=["front"])
    p = dataset_paths(ds_root)
    upsert_task(p.meta_dir, "pick cube", "pick the cube")
    chunk_dir = p.chunk_dir(0)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    rows = [{
        "timestamp": i / 15, "tick_t_mono_ns": 0,
        "observation.state.joint_pos": [0.1] * 6,
        "observation.state.joint_vel": [0.0] * 6,
        "observation.state.joint_effort": [0.0] * 6,
        "observation.state.t_mono_ns": 0,
        "observation.state.gripper_pos": 0.5,
        "observation.state.ee_pos": [0.1, 0.2, 0.3],
        "observation.state.ee_rotvec": [0.0, 0.0, 0.0],
        "action.joint_pos": [0.2] * 6,
        "action.t_mono_ns": 0,
        "action.gripper_pos": 0.7,
        "frame_index": i, "episode_index": 0, "index": i, "task_index": 0,
        "observation.images.front.video_frame_index": i,
        "observation.images.front.t_mono_ns": 0,
    } for i in range(2)]
    pq.write_table(pa.Table.from_pylist(rows), p.episode_parquet(0, 0))
    cam_dir = p.videos_dir / "observation.images.front" / "chunk-000"
    cam_dir.mkdir(parents=True, exist_ok=True)
    (cam_dir / "episode_000000.mp4").write_bytes(b"\x00fake\x00")
    append_episode(p.meta_dir, {
        "episode_index": 0, "task": "pick cube",
        "num_frames": 2, "robot": "so101", "mode": "teleop",
        "cameras": ["front"],
    })
    app.state.datasets_root = tmp_path / "datasets"
    app.state.vla_dest_root = tmp_path / "vla"  # not used by archive path

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get(
            f"/api/datasets/{ds_name}/archive",
            params={"format": "vla_compat", "robot_type": "so101"},
        )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert f'filename="{ds_name}_vla.zip"' in r.headers.get("content-disposition", "")

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert "meta/info.json" in names
    assert any(n.startswith("data/chunk-000/episode_") and n.endswith(".parquet") for n in names)
    assert any(n.startswith("videos/observation.images.front/chunk-000/episode_")
               and n.endswith(".mp4") for n in names)

    # Tempdir must not have leaked into the configured vla_dest_root.
    # The archive route should never touch get_vla_dest_root — it converts
    # into its own tempfile.TemporaryDirectory and zips from there.
    assert not (tmp_path / "vla").exists()


@pytest.mark.asyncio
async def test_archive_vla_compat_with_rebot_override(app: FastAPI, tmp_path: Path):
    """robot_type=rebot override on a legacy 'unknown' dataset must
    produce a 7-dim proprio info.json inside the zip."""
    import io
    import json
    import zipfile
    import pyarrow as pa
    import pyarrow.parquet as pq
    from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
    from mimicrec.recording.metadata import append_episode, upsert_task

    ds_name = "legacy_rebot"
    ds_root = tmp_path / "datasets" / ds_name
    init_dataset(ds_root, fps=15,
                 joint_names=["j1", "j2", "j3", "j4", "j5", "j6"],
                 camera_names=["front"])
    p = dataset_paths(ds_root)
    upsert_task(p.meta_dir, "pick cube", "pick the cube")
    chunk_dir = p.chunk_dir(0)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    rows = [{
        "timestamp": i / 15, "tick_t_mono_ns": 0,
        "observation.state.joint_pos": [0.1] * 6,
        "observation.state.joint_vel": [0.0] * 6,
        "observation.state.joint_effort": [0.0] * 6,
        "observation.state.t_mono_ns": 0,
        "observation.state.gripper_pos": 0.5,
        "observation.state.ee_pos": [0.1, 0.2, 0.3],
        "observation.state.ee_rotvec": [0.0, 0.0, 0.0],
        "action.joint_pos": [0.2] * 6,
        "action.t_mono_ns": 0,
        "action.gripper_pos": 0.7,
        "frame_index": i, "episode_index": 0, "index": i, "task_index": 0,
        "observation.images.front.video_frame_index": i,
        "observation.images.front.t_mono_ns": 0,
    } for i in range(2)]
    pq.write_table(pa.Table.from_pylist(rows), p.episode_parquet(0, 0))
    cam_dir = p.videos_dir / "observation.images.front" / "chunk-000"
    cam_dir.mkdir(parents=True, exist_ok=True)
    (cam_dir / "episode_000000.mp4").write_bytes(b"\x00fake\x00")
    append_episode(p.meta_dir, {
        "episode_index": 0, "task": "pick cube",
        "num_frames": 2, "robot": "rebot", "mode": "teleop",
        "cameras": ["front"],
    })
    app.state.datasets_root = tmp_path / "datasets"
    app.state.vla_dest_root = tmp_path / "vla"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get(
            f"/api/datasets/{ds_name}/archive",
            params={"format": "vla_compat", "robot_type": "rebot"},
        )
    assert r.status_code == 200, r.text
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    info = json.loads(zf.read("meta/info.json").decode())
    assert info["robot_type"] == "ReBotArmZmqAdapter"


@pytest.mark.asyncio
async def test_archive_vla_compat_rejects_invalid_robot_type(app: FastAPI, tmp_path: Path):
    """FastAPI Literal validation must reject robot_type values
    outside {so101, rebot} with 422 before any exporter code runs."""
    from mimicrec.recording.dataset_layout import init_dataset

    ds_name = "ds_validate"
    init_dataset(tmp_path / "datasets" / ds_name, fps=15,
                 joint_names=["j1", "j2", "j3", "j4", "j5", "j6"],
                 camera_names=[])
    app.state.datasets_root = tmp_path / "datasets"
    app.state.vla_dest_root = tmp_path / "vla"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get(
            f"/api/datasets/{ds_name}/archive",
            params={"format": "vla_compat", "robot_type": "totally_invalid"},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_archive_vla_compat_uses_default_instruction_template(app: FastAPI, tmp_path: Path):
    """Omitting instruction_template must apply the same default as
    POST /export (DEFAULT_INSTRUCTION_TEMPLATE), not 400."""
    import io
    import pyarrow as pa
    import pyarrow.parquet as pq
    import zipfile
    from mimicrec.recording.dataset_layout import init_dataset, dataset_paths
    from mimicrec.recording.metadata import append_episode, upsert_task

    ds_name = "ds_default_template"
    ds_root = tmp_path / "datasets" / ds_name
    init_dataset(ds_root, fps=15,
                 joint_names=["j1", "j2", "j3", "j4", "j5", "j6"],
                 camera_names=["front"])
    p = dataset_paths(ds_root)
    upsert_task(p.meta_dir, "pick cube", "pick the cube")
    chunk_dir = p.chunk_dir(0)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    rows = [{
        "timestamp": i / 15, "tick_t_mono_ns": 0,
        "observation.state.joint_pos": [0.1] * 6,
        "observation.state.joint_vel": [0.0] * 6,
        "observation.state.joint_effort": [0.0] * 6,
        "observation.state.t_mono_ns": 0,
        "observation.state.gripper_pos": 0.5,
        "observation.state.ee_pos": [0.1, 0.2, 0.3],
        "observation.state.ee_rotvec": [0.0, 0.0, 0.0],
        "action.joint_pos": [0.2] * 6,
        "action.t_mono_ns": 0,
        "action.gripper_pos": 0.7,
        "frame_index": i, "episode_index": 0, "index": i, "task_index": 0,
        "observation.images.front.video_frame_index": i,
        "observation.images.front.t_mono_ns": 0,
    } for i in range(2)]
    pq.write_table(pa.Table.from_pylist(rows), p.episode_parquet(0, 0))
    cam_dir = p.videos_dir / "observation.images.front" / "chunk-000"
    cam_dir.mkdir(parents=True, exist_ok=True)
    (cam_dir / "episode_000000.mp4").write_bytes(b"\x00fake\x00")
    append_episode(p.meta_dir, {
        "episode_index": 0, "task": "pick cube",
        "num_frames": 2, "robot": "so101", "mode": "teleop",
        "cameras": ["front"],
    })
    app.state.datasets_root = tmp_path / "datasets"
    app.state.vla_dest_root = tmp_path / "vla"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        # Note: no instruction_template param.
        r = await ac.get(
            f"/api/datasets/{ds_name}/archive",
            params={"format": "vla_compat", "robot_type": "so101"},
        )
    assert r.status_code == 200, r.text
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert "meta/info.json" in zf.namelist()
