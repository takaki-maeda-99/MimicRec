from __future__ import annotations
from pathlib import Path
import pytest
from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def app():
    a = create_app()
    a.state.configs_root = REPO_ROOT / "configs"
    a.state.datasets_root = None
    a.state.vla_dest_root = None
    return a
