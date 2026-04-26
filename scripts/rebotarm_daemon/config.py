"""Configuration dataclasses for the reBotArm safety daemon."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml


@dataclass
class SafetyLimits:
    joint_pos_min_rad: List[float] = field(default_factory=lambda: [-3.14] * 6)
    joint_pos_max_rad: List[float] = field(default_factory=lambda: [3.14] * 6)
    joint_vel_max_rad_s: float = 3.14
    joint_accel_max_rad_s2: float = 20.0
    torque_max_nm: List[float] = field(default_factory=lambda: [10.0] * 6)
    temperature_warn_c: float = 70.0
    temperature_fault_c: float = 80.0
    temperature_recover_c: float = 60.0
    heartbeat_timeout_ms: int = 500


@dataclass
class GravityCompParams:
    push_velocity_threshold_m_s: float = 0.02
    push_omega_threshold_rad_s: float = 0.3
    kp: List[float] = field(default_factory=lambda: [2.0] * 6)
    kd: List[float] = field(default_factory=lambda: [1.0] * 6)


@dataclass
class DaemonConfig:
    arm_config: str = "configs/rebotarm/arm.yaml"
    zmq_address: str = "tcp://*:5558"
    control_rate_hz: int = 500
    safety: SafetyLimits = field(default_factory=SafetyLimits)
    gravity_comp: GravityCompParams = field(default_factory=GravityCompParams)


def load_daemon_config(path: str | Path) -> DaemonConfig:
    """Load daemon config from YAML; missing sections fall back to dataclass defaults."""
    raw = yaml.safe_load(Path(path).read_text()) or {}
    safety_raw = raw.get("safety", {})
    grav_raw = raw.get("gravity_comp", {})
    return DaemonConfig(
        arm_config=raw.get("arm_config", "configs/rebotarm/arm.yaml"),
        zmq_address=raw.get("zmq_address", "tcp://*:5558"),
        control_rate_hz=int(raw.get("control_rate_hz", 500)),
        safety=SafetyLimits(**safety_raw) if safety_raw else SafetyLimits(),
        gravity_comp=GravityCompParams(**grav_raw) if grav_raw else GravityCompParams(),
    )
