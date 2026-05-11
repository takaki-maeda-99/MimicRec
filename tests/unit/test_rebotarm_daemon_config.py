import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import pytest
from rebotarm_daemon.config import (
    DaemonConfig, SafetyLimits, GravityCompParams, GripperParams,
    EnableSwitchParams, clamp_gripper_target, load_daemon_config,
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


def test_gripper_position_limits_default_to_none():
    """Backwards compatibility: unset limits = no clamp."""
    g = GripperParams()
    assert g.position_min_rad is None
    assert g.position_max_rad is None


def test_clamp_gripper_target_disabled_when_both_none():
    g = GripperParams()
    assert clamp_gripper_target(-100.0, g) == -100.0
    assert clamp_gripper_target(100.0, g) == 100.0


def test_clamp_gripper_target_lower_bound():
    g = GripperParams(position_min_rad=-3.0)
    assert clamp_gripper_target(-5.0, g) == -3.0
    assert clamp_gripper_target(-3.0, g) == -3.0  # boundary passes
    assert clamp_gripper_target(0.0, g) == 0.0
    assert clamp_gripper_target(100.0, g) == 100.0  # upper still free


def test_clamp_gripper_target_upper_bound():
    g = GripperParams(position_max_rad=1.0)
    assert clamp_gripper_target(5.0, g) == 1.0
    assert clamp_gripper_target(1.0, g) == 1.0  # boundary passes
    assert clamp_gripper_target(-100.0, g) == -100.0  # lower still free


def test_clamp_gripper_target_both_bounds():
    g = GripperParams(position_min_rad=-3.0, position_max_rad=1.0)
    assert clamp_gripper_target(-5.0, g) == -3.0
    assert clamp_gripper_target(0.0, g) == 0.0
    assert clamp_gripper_target(5.0, g) == 1.0


def test_loads_gripper_position_limits_from_yaml(tmp_path):
    p = tmp_path / "with_gripper_limits.yaml"
    p.write_text(
        "gripper:\n"
        "  cfg_path: configs/rebotarm/gripper.yaml\n"
        "  position_min_rad: -5.5\n"
        "  position_max_rad: 0.5\n"
    )
    cfg = load_daemon_config(p)
    assert cfg.gripper is not None
    assert cfg.gripper.position_min_rad == -5.5
    assert cfg.gripper.position_max_rad == 0.5


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
    # The enable-switch is opt-in: an empty YAML leaves it disabled so
    # the daemon comes up identically to before this feature landed.
    assert cfg.enable_switch is None


def test_enable_switch_omitted_is_none(tmp_path):
    p = tmp_path / "no_switch.yaml"
    p.write_text("arm_config: configs/rebotarm/arm.yaml\n")
    cfg = load_daemon_config(p)
    assert cfg.enable_switch is None


def test_enable_switch_loads_from_yaml(tmp_path):
    p = tmp_path / "switch.yaml"
    p.write_text(
        "enable_switch:\n"
        "  chip: gpiochip0\n"
        "  line: 17\n"
        "  bias: pull_up\n"
        "  active_state: high\n"
        "  poll_hz: 50\n"
        "  debounce_ms: 20\n"
    )
    cfg = load_daemon_config(p)
    assert cfg.enable_switch is not None
    assert cfg.enable_switch.chip == "gpiochip0"
    assert cfg.enable_switch.line == 17
    assert cfg.enable_switch.bias == "pull_up"
    assert cfg.enable_switch.active_state == "high"
    assert cfg.enable_switch.poll_hz == 50
    assert cfg.enable_switch.debounce_ms == 20


def test_enable_switch_accepts_string_line_name(tmp_path):
    """DTB line names (e.g., Jetson 'PR.04') round-trip as strings."""
    p = tmp_path / "switch_named.yaml"
    p.write_text(
        "enable_switch:\n"
        "  chip: gpiochip0\n"
        "  line: GPIO17\n"
    )
    cfg = load_daemon_config(p)
    assert cfg.enable_switch is not None
    assert cfg.enable_switch.line == "GPIO17"


def test_enable_switch_rejects_unknown_bias():
    with pytest.raises(ValueError, match="bias"):
        EnableSwitchParams(bias="bogus")


def test_enable_switch_rejects_unknown_active_state():
    with pytest.raises(ValueError, match="active_state"):
        EnableSwitchParams(active_state="middle")


def test_enable_switch_defaults_match_pi5_bcm17():
    """Bare construction should target the documented Pi 5 default
    (BCM17 with internal pull-up, locked when floating high).

    Locks the default to the one called out in the YAML example so
    operators can drop in ``enable_switch: {}`` and get a sensible
    Pi 5 wiring out of the box.
    """
    p = EnableSwitchParams()
    assert p.chip == "gpiochip0"
    assert p.line == 17
    assert p.bias == "pull_up"
    assert p.active_state == "high"


def test_reconnect_defaults_match_documented_2s_and_250_ticks():
    """The reconnect cadence and fault threshold are the user-facing
    contract for hot-unplug behaviour. Lock the defaults so a future
    edit doesn't accidentally make the daemon thrash (too short) or
    appear hung (too long).
    """
    cfg = DaemonConfig()
    assert cfg.reconnect_interval_s == 2.0
    assert cfg.disconnect_fault_threshold == 250


def test_reconnect_fields_load_from_yaml(tmp_path):
    p = tmp_path / "reconn.yaml"
    p.write_text(
        "reconnect_interval_s: 0.5\n"
        "disconnect_fault_threshold: 100\n"
    )
    cfg = load_daemon_config(p)
    assert cfg.reconnect_interval_s == 0.5
    assert cfg.disconnect_fault_threshold == 100
