from __future__ import annotations
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MIMICREC_CONFIGS_ROOT", str(REPO_ROOT / "configs"))
    monkeypatch.setenv("MIMICREC_DATASETS_ROOT", str(tmp_path / "datasets"))
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_camera_roles_endpoint_returns_yaml_roles(client: TestClient):
    r = client.get("/api/configs/camera_roles")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "roles" in body
    assert {"front", "wrist", "top", "side"}.issubset(set(body["roles"]))
