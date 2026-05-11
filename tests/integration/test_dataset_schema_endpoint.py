from __future__ import annotations
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicrec.api.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("MIMICREC_CONFIGS_ROOT", str(repo_root / "configs"))
    monkeypatch.setenv("MIMICREC_DATASETS_ROOT", str(tmp_path / "datasets"))
    app = create_app()
    with TestClient(app) as c:
        yield c


def _seed_info_json(datasets_root: Path, ds: str, image_keys: list[str]) -> None:
    meta_dir = datasets_root / ds / "meta"
    meta_dir.mkdir(parents=True)
    features = {f"observation.images.{k}": {"info": {}} for k in image_keys}
    features["action"] = {}  # non-image feature — must be ignored
    info = {"features": features}
    (meta_dir / "info.json").write_text(json.dumps(info))


def test_schema_endpoint_returns_image_keys(client: TestClient, tmp_path: Path):
    _seed_info_json(tmp_path / "datasets", "ds1", ["front", "wrist"])
    r = client.get("/api/datasets/ds1/schema")
    assert r.status_code == 200, r.text
    assert sorted(r.json()["image_keys"]) == ["front", "wrist"]


def test_schema_endpoint_works_for_zero_episode_dataset(client: TestClient, tmp_path: Path):
    _seed_info_json(tmp_path / "datasets", "ds_empty", ["front"])
    r = client.get("/api/datasets/ds_empty/schema")
    assert r.status_code == 200
    assert r.json()["image_keys"] == ["front"]


def test_schema_endpoint_404_for_unknown_dataset(client: TestClient):
    r = client.get("/api/datasets/does_not_exist/schema")
    assert r.status_code == 404
