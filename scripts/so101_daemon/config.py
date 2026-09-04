from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


ARM_JOINT_NAMES = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
)


@dataclass(frozen=True)
class SO101Limits:
    joint_pos_min_deg: list[float] = field(
        default_factory=lambda: [-180.0, -110.0, -110.0, -110.0, -180.0]
    )
    joint_pos_max_deg: list[float] = field(
        default_factory=lambda: [180.0, 110.0, 110.0, 110.0, 180.0]
    )
    max_joint_step_deg: float = 8.0
    gripper_min: float = 0.0
    gripper_max: float = 100.0

    def __post_init__(self) -> None:
        if len(self.joint_pos_min_deg) != 5 or len(self.joint_pos_max_deg) != 5:
            raise ValueError("SO-101 joint limits must contain five values")
        if any(
            lower >= upper
            for lower, upper in zip(
                self.joint_pos_min_deg, self.joint_pos_max_deg
            )
        ):
            raise ValueError("SO-101 minimum joint limits must be below maxima")
        if self.max_joint_step_deg <= 0.0:
            raise ValueError("max_joint_step_deg must be > 0")
        if self.gripper_min >= self.gripper_max:
            raise ValueError("gripper_min must be below gripper_max")


@dataclass(frozen=True)
class SO101DaemonConfig:
    port: str = "/dev/ttyACM0"
    arm_id: str = "my_arm"
    zmq_address: str = "tcp://*:5559"
    state_rate_hz: float = 50.0
    heartbeat_timeout_ms: int = 500
    arm_p_coefficient: int = 32
    arm_p_coefficients: dict[str, int] = field(default_factory=dict)
    arm_i_coefficient: int = 0
    gripper_p_coefficient: int = 16
    gripper_i_coefficient: int = 0
    gripper_d_coefficient: int = 32
    arm_acceleration: int = 254
    arm_goal_velocity: int = 0
    lock_path: str | None = None
    limits: SO101Limits = field(default_factory=SO101Limits)

    def __post_init__(self) -> None:
        if self.state_rate_hz <= 0.0:
            raise ValueError("state_rate_hz must be > 0")
        if self.heartbeat_timeout_ms <= 0:
            raise ValueError("heartbeat_timeout_ms must be > 0")
        if not 1 <= self.arm_p_coefficient <= 254:
            raise ValueError("arm_p_coefficient must be in [1, 254]")
        unknown = set(self.arm_p_coefficients) - set(ARM_JOINT_NAMES)
        if unknown:
            raise ValueError(
                f"unknown arm_p_coefficients joints: {sorted(unknown)}"
            )
        if any(
            not 1 <= int(value) <= 254
            for value in self.arm_p_coefficients.values()
        ):
            raise ValueError("arm_p_coefficients values must be in [1, 254]")
        if not 0 <= self.arm_i_coefficient <= 254:
            raise ValueError("arm_i_coefficient must be in [0, 254]")
        if not 1 <= self.gripper_p_coefficient <= 254:
            raise ValueError("gripper_p_coefficient must be in [1, 254]")
        if not 0 <= self.gripper_i_coefficient <= 254:
            raise ValueError("gripper_i_coefficient must be in [0, 254]")
        if not 0 <= self.gripper_d_coefficient <= 254:
            raise ValueError("gripper_d_coefficient must be in [0, 254]")
        if not 1 <= self.arm_acceleration <= 254:
            raise ValueError("arm_acceleration must be in [1, 254]")
        if not 0 <= self.arm_goal_velocity <= 4095:
            raise ValueError("arm_goal_velocity must be in [0, 4095]")


def load_daemon_config(path: str | Path) -> SO101DaemonConfig:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    limits = SO101Limits(**(raw.get("limits") or {}))
    return SO101DaemonConfig(
        port=str(raw.get("port", "/dev/ttyACM0")),
        arm_id=str(raw.get("arm_id", raw.get("id", "my_arm"))),
        zmq_address=str(raw.get("zmq_address", "tcp://*:5559")),
        state_rate_hz=float(raw.get("state_rate_hz", 50.0)),
        heartbeat_timeout_ms=int(raw.get("heartbeat_timeout_ms", 500)),
        arm_p_coefficient=int(raw.get("arm_p_coefficient", 32)),
        arm_p_coefficients={
            str(name): int(value)
            for name, value in (raw.get("arm_p_coefficients") or {}).items()
        },
        arm_i_coefficient=int(raw.get("arm_i_coefficient", 0)),
        gripper_p_coefficient=int(raw.get("gripper_p_coefficient", 16)),
        gripper_i_coefficient=int(raw.get("gripper_i_coefficient", 0)),
        gripper_d_coefficient=int(raw.get("gripper_d_coefficient", 32)),
        arm_acceleration=int(raw.get("arm_acceleration", 254)),
        arm_goal_velocity=int(raw.get("arm_goal_velocity", 0)),
        lock_path=(str(raw["lock_path"]) if raw.get("lock_path") else None),
        limits=limits,
    )
