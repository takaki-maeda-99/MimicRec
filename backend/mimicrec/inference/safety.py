from __future__ import annotations
from dataclasses import dataclass
import numpy as np

from mimicrec.inference.types import StepAction
from mimicrec.types import RobotCommand


@dataclass
class InferenceSafety:
    max_delta: float
    joint_min: np.ndarray
    joint_max: np.ndarray
    slow_stop_ticks: int = 5

    _last_safe_q: np.ndarray | None = None
    _last_gripper_cmd: float | None = None
    _slow_stop_remaining: int = 0
    _clamps_in_current_chunk: int = 0
    _last_event: dict | None = None              # most recent safety event, for /state snapshot

    def filter(self, step: StepAction | None, q_curr: np.ndarray, tick_t_ns: int) -> RobotCommand:
        if step is None:
            return self._slow_stop(q_curr, tick_t_ns)
        delta = step.q - q_curr
        clamped = np.clip(delta, -self.max_delta, self.max_delta)
        if not np.array_equal(clamped, delta):
            self._clamps_in_current_chunk += 1
            self._last_event = {"kind": "delta_clamp"}
        q_safe = np.clip(q_curr + clamped, self.joint_min, self.joint_max)
        if not np.array_equal(q_safe, q_curr + clamped):
            self._last_event = {"kind": "joint_limit"}
        self._last_safe_q = q_safe
        gripper_cmd = step.gripper if step.gripper is not None else self._last_gripper_cmd
        if gripper_cmd is not None:
            self._last_gripper_cmd = gripper_cmd
        if step.ik_failed:
            self._last_event = {"kind": "ik_fail"}
        self._slow_stop_remaining = 0
        return RobotCommand(q=q_safe, gripper=gripper_cmd, t_mono_ns=tick_t_ns)

    def _slow_stop(self, q_curr: np.ndarray, tick_t_ns: int) -> RobotCommand:
        if self._last_safe_q is None:
            q = q_curr.copy()
        else:
            if self._slow_stop_remaining == 0:
                self._slow_stop_remaining = self.slow_stop_ticks
            n = self._slow_stop_remaining
            alpha = 1.0 - ((n - 1) / self.slow_stop_ticks)
            q = self._last_safe_q + (q_curr - self._last_safe_q) * alpha
            self._slow_stop_remaining = max(0, n - 1)
            if self._slow_stop_remaining == 0:
                self._last_safe_q = q
        self._last_event = {"kind": "slow_stop"}
        return RobotCommand(q=q, gripper=self._last_gripper_cmd, t_mono_ns=tick_t_ns)

    def on_new_chunk(self) -> None:
        self._clamps_in_current_chunk = 0

    def clamps_in_current_chunk(self) -> int:
        return self._clamps_in_current_chunk

    def last_event(self) -> dict | None:
        """Most recent safety event for the GET /session/inference/state snapshot.
        None if no event has fired since session start."""
        return self._last_event
