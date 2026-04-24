from __future__ import annotations
from dataclasses import dataclass
import numpy as np

from mimicrec.errors import ReplaySafetyError


@dataclass
class ReplaySafetyConfig:
    ramp_duration_sec: float
    max_joint_velocity: float
    max_joint_acceleration: float
    max_joint_position_jump: float
    command_timeout_sec: float
    watchdog_hz: int
    dof: int
    dt_sec: float

    @classmethod
    def from_robot_cfg(cls, robot_cfg, dof: int, dt_sec: float) -> "ReplaySafetyConfig":
        r = robot_cfg.replay
        return cls(
            ramp_duration_sec=float(r.ramp_duration_sec),
            max_joint_velocity=float(r.max_joint_velocity),
            max_joint_acceleration=float(r.max_joint_acceleration),
            max_joint_position_jump=float(r.max_joint_position_jump),
            command_timeout_sec=float(r.command_timeout_sec),
            watchdog_hz=int(r.watchdog_hz),
            dof=dof,
            dt_sec=dt_sec,
        )


class ReplayWatchdog:
    def __init__(self, cfg: ReplaySafetyConfig):
        self._cfg = cfg
        self._last_command_t_mono_ns: int | None = None

    def note_command_sent(self, t_mono_ns: int) -> None:
        self._last_command_t_mono_ns = t_mono_ns

    def assert_fresh(self, now_t_mono_ns: int) -> None:
        if self._last_command_t_mono_ns is None:
            return
        age_sec = (now_t_mono_ns - self._last_command_t_mono_ns) / 1e9
        if age_sec > self._cfg.command_timeout_sec:
            raise ReplaySafetyError(
                f"command_timeout exceeded: {age_sec:.3f}s > {self._cfg.command_timeout_sec}s"
            )

    def check(
        self,
        target: np.ndarray,
        prev_target: np.ndarray | None,
        prev_prev_target: np.ndarray | None,
        measured: np.ndarray,
    ) -> None:
        if np.max(np.abs(target - measured)) > self._cfg.max_joint_position_jump:
            raise ReplaySafetyError(
                f"joint_position_jump exceeded: "
                f"max={float(np.max(np.abs(target - measured))):.3f} > "
                f"{self._cfg.max_joint_position_jump}"
            )
        if prev_target is not None:
            velocity = np.abs((target - prev_target) / self._cfg.dt_sec)
            if float(np.max(velocity)) > self._cfg.max_joint_velocity:
                raise ReplaySafetyError(
                    f"joint_velocity exceeded: max={float(np.max(velocity)):.3f} > "
                    f"{self._cfg.max_joint_velocity}"
                )
        if prev_target is not None and prev_prev_target is not None:
            accel = np.abs((target - 2 * prev_target + prev_prev_target) / (self._cfg.dt_sec ** 2))
            if float(np.max(accel)) > self._cfg.max_joint_acceleration:
                raise ReplaySafetyError(
                    f"joint_acceleration exceeded: max={float(np.max(accel)):.3f} > "
                    f"{self._cfg.max_joint_acceleration}"
                )
