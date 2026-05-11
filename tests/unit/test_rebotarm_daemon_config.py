import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import pytest
from rebotarm_daemon.config import (
    DaemonConfig, SafetyLimits, GravityCompParams, load_daemon_config,
)


def test_safety_limits_defaults_present():
    s = SafetyLimits()
    assert s.heartbeat_timeout_ms > 0
    assert s.temperature_warn_c < s.temperature_fault_c
    assert s.temperature_recover_c < s.temperature_fault_c


def test_loads_yaml(tmp_path):
    fixture = Path(__file__).parent.parent / "fixtures" / "rebotarm_daemon_test.yaml"
    cfg = load_daemon_config(fixture)
    assert cfg.zmq_address == "tcp://*:5558"
    assert cfg.control_rate_hz == 500
    assert len(cfg.safety.joint_pos_min_rad) == 6
    assert cfg.safety.heartbeat_timeout_ms == 500
    assert cfg.gravity_comp.kp == [0.0] * 6
    assert cfg.gravity_comp.kd == [1.5, 1.5, 1.0, 0.6, 0.4, 0.2]
    assert cfg.gravity_comp.friction_vel_taper_rad_s == [1.5, 1.5, 1.5, 1.0, 1.0, 0.0]
    assert cfg.position.kp == [120.0, 120.0, 120.0, 18.0, 18.0, 18.0]
    assert cfg.position.kd == [8.0, 8.0, 8.0, 2.0, 2.0, 2.0]


def test_loads_empty_yaml_yields_full_defaults(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    cfg = load_daemon_config(p)
    assert cfg.zmq_address == "tcp://*:5558"
    assert cfg.safety.heartbeat_timeout_ms == 500
    assert cfg.gravity_comp.kp == [0.0] * 6
    assert cfg.gravity_comp.kd == [1.5, 1.5, 1.0, 0.6, 0.4, 0.2]
    # Default disables the taper on every joint so behavior stays
    # identical to the pre-taper controller for users who haven't
    # opted in via YAML.
    assert cfg.gravity_comp.friction_vel_taper_rad_s == [0.0] * 6
    assert cfg.position.kp == [120.0, 120.0, 120.0, 18.0, 18.0, 18.0]
    assert cfg.position.kd == [8.0, 8.0, 8.0, 2.0, 2.0, 2.0]
