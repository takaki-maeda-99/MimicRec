from __future__ import annotations
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_export_vla_compat_writes_to_state_override(tmp_path: Path, app: FastAPI, monkeypatch):
    # Arrange dataset and dest paths via app state.
    from mimicrec.recording.dataset_layout import init_dataset
    ds_root = tmp_path / "datasets" / "ds7"
    init_dataset(ds_root, fps=15,
                 joint_names=["j1","j2","j3","j4","j5","j6"], camera_names=["front"])
    app.state.datasets_root = tmp_path / "datasets"
    app.state.vla_dest_root = tmp_path / "vla"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/datasets/ds7/export", json={
            "format": "vla_compat",
            "instruction_template": "What action should the robot take to {TASK}? A:",
            "force": False,
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
    from mimicrec.recording.dataset_layout import init_dataset
    ds_root = tmp_path / "datasets" / "ds_force"
    init_dataset(ds_root, fps=15,
                 joint_names=["j1","j2","j3","j4","j5","j6"], camera_names=[])
    app.state.datasets_root = tmp_path / "datasets"
    app.state.vla_dest_root = tmp_path / "vla"
    (tmp_path / "vla" / "ds_force").mkdir(parents=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post("/api/datasets/ds_force/export",
                          json={"format": "vla_compat", "force": True})
    assert r.status_code == 200
