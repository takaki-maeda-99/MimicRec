import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mimicrec.api.deps import get_vla_dest_root


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
