"""Tests for the optional gravity_in_base field on DaemonConfig.

Covers:
- Omitting gravity_in_base falls back to the flat-mount default.
- Explicit gravity_in_base in YAML round-trips through load_daemon_config.
- Length != 3 raises ValueError at construction time.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

# scripts/ is not pip-installed; add it to the import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from rebotarm_daemon.config import DaemonConfig, load_daemon_config


def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "daemon.yaml"
    p.write_text(body)
    return p


def test_gravity_in_base_default_is_flat_mount(tmp_path: Path) -> None:
    """Omitting gravity_in_base must keep the prior flat-mount behavior."""
    cfg_path = _write_yaml(tmp_path, "arm_config: configs/rebotarm/arm.yaml\n")
    cfg = load_daemon_config(cfg_path)
    assert cfg.gravity_in_base == [0.0, 0.0, -9.81]


def test_gravity_in_base_explicit_round_trips(tmp_path: Path) -> None:
    """A right-45° tilt vector in YAML lands verbatim on the dataclass."""
    cfg_path = _write_yaml(
        tmp_path,
        "arm_config: configs/rebotarm/arm.yaml\n"
        "gravity_in_base: [0.0, -6.937, -6.937]\n",
    )
    cfg = load_daemon_config(cfg_path)
    assert cfg.gravity_in_base == [0.0, -6.937, -6.937]


def test_gravity_in_base_wrong_length_raises(tmp_path: Path) -> None:
    """Guard against typos like a 2-element vector silently being accepted."""
    cfg_path = _write_yaml(
        tmp_path,
        "arm_config: configs/rebotarm/arm.yaml\n"
        "gravity_in_base: [0.0, 0.0]\n",
    )
    with pytest.raises(ValueError, match="gravity_in_base"):
        load_daemon_config(cfg_path)


def test_gravity_in_base_default_dataclass() -> None:
    """Constructing DaemonConfig() directly also defaults to flat mount."""
    cfg = DaemonConfig()
    assert cfg.gravity_in_base == [0.0, 0.0, -9.81]
