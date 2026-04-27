"""Configuration dataclasses for the reBotArm safety daemon."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

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
    # Per-joint MIT gains for pure-compliance hand-teaching. kp=0 leaves the
    # arm fully free; kd damps motion, with higher values on the proximal
    # 4340P joints (1-3) which carry more reflected inertia. Mirrors
    # reBotArm_control_py/data_collect/11_gravity_compensation_record.py.
    kp: List[float] = field(default_factory=lambda: [0.0] * 6)
    kd: List[float] = field(
        default_factory=lambda: [1.5, 1.5, 1.0, 0.6, 0.4, 0.2]
    )


@dataclass
class PositionParams:
    # Per-joint MIT gains for position-tracking (replay / teleop). The
    # daemon never switches the motors out of MIT — POSITION mode is just
    # MIT with strong kp + gravity FF, GRAVITY_COMP is MIT with kp=0 +
    # gravity FF. This avoids the ~200 ms torque dropout per motor that
    # mode_pos_vel() incurs, which used to drop the QDD arm under gravity
    # whenever replay flipped modes.
    #
    # Defaults mirror arm.yaml's MIT.kp/kd (120/8 for proximal 4340P,
    # 18/2 for distal 4310). Tune up for tighter tracking, down for
    # softer landing on commanded targets.
    kp: List[float] = field(
        default_factory=lambda: [120.0, 120.0, 120.0, 18.0, 18.0, 18.0]
    )
    kd: List[float] = field(default_factory=lambda: [8.0, 8.0, 8.0, 2.0, 2.0, 2.0])


@dataclass
class GripperParams:
    # Optional gripper running on the same bus as the arm. Mirrors the
    # compliance loop from reBotArm_control_py/data_collect/11_gravity_compensation_record.py:
    # kp=0 fully free, kd damps oscillation, and a small velocity-direction
    # friction-compensation torque overcomes static friction so the gripper
    # feels light to the operator. Set to ``None`` (omit the YAML section)
    # if the hardware has no gripper.
    cfg_path: str = "configs/rebotarm/gripper.yaml"
    kd: float = 0.0
    friction_tau_nm: float = 0.10
    vel_deadband_rad_s: float = 0.10
    control_rate_hz: int = 100


@dataclass
class DaemonConfig:
    arm_config: str = "configs/rebotarm/arm.yaml"
    zmq_address: str = "tcp://*:5558"
    control_rate_hz: int = 500
    safety: SafetyLimits = field(default_factory=SafetyLimits)
    gravity_comp: GravityCompParams = field(default_factory=GravityCompParams)
    position: PositionParams = field(default_factory=PositionParams)
    gripper: Optional[GripperParams] = None


def load_daemon_config(path: str | Path) -> DaemonConfig:
    """Load daemon config from YAML; missing sections fall back to dataclass defaults."""
    raw = yaml.safe_load(Path(path).read_text()) or {}
    safety_raw = raw.get("safety", {})
    grav_raw = raw.get("gravity_comp", {})
    pos_raw = raw.get("position", {})
    # Gripper is opt-in: omitting the ``gripper:`` section disables it.
    gripper_raw = raw.get("gripper")
    return DaemonConfig(
        arm_config=raw.get("arm_config", "configs/rebotarm/arm.yaml"),
        zmq_address=raw.get("zmq_address", "tcp://*:5558"),
        control_rate_hz=int(raw.get("control_rate_hz", 500)),
        safety=SafetyLimits(**safety_raw) if safety_raw else SafetyLimits(),
        gravity_comp=GravityCompParams(**grav_raw) if grav_raw else GravityCompParams(),
        position=PositionParams(**pos_raw) if pos_raw else PositionParams(),
        gripper=GripperParams(**gripper_raw) if gripper_raw else None,
    )
