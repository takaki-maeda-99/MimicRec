"""Lock-protected shared state container for the reBotArm daemon.

The 500 Hz control loop calls .set(...) every tick; ZMQ requests call
.snapshot() on demand. snapshot() copies arrays so callers can mutate
freely.
"""
from __future__ import annotations

import threading
from typing import Optional

import numpy as np


class SharedRobotState:
    def __init__(self, dof: int = 6):
        self._dof = dof
        self._lock = threading.Lock()
        self._joint_pos = np.zeros(dof, dtype=np.float32)
        self._joint_vel = np.zeros(dof, dtype=np.float32)
        self._joint_effort = np.zeros(dof, dtype=np.float32)
        self._ee_pos: Optional[np.ndarray] = None
        self._ee_rotvec: Optional[np.ndarray] = None
        self._gripper_pos: Optional[float] = None
        self._motor_temps_c = np.zeros(dof, dtype=np.float32)
        self._motor_torques_nm = np.zeros(dof, dtype=np.float32)

    def set(
        self,
        *,
        joint_pos: np.ndarray,
        joint_vel: np.ndarray,
        joint_effort: np.ndarray,
        ee_pos: Optional[np.ndarray] = None,
        ee_rotvec: Optional[np.ndarray] = None,
        gripper_pos: Optional[float] = None,
        motor_temps_c: Optional[np.ndarray] = None,
        motor_torques_nm: Optional[np.ndarray] = None,
    ) -> None:
        with self._lock:
            self._joint_pos = joint_pos.astype(np.float32, copy=True)
            self._joint_vel = joint_vel.astype(np.float32, copy=True)
            self._joint_effort = joint_effort.astype(np.float32, copy=True)
            if ee_pos is not None:
                self._ee_pos = ee_pos.astype(np.float32, copy=True)
            if ee_rotvec is not None:
                self._ee_rotvec = ee_rotvec.astype(np.float32, copy=True)
            if gripper_pos is not None:
                self._gripper_pos = float(gripper_pos)
            if motor_temps_c is not None:
                self._motor_temps_c = motor_temps_c.astype(np.float32, copy=True)
            if motor_torques_nm is not None:
                self._motor_torques_nm = motor_torques_nm.astype(np.float32, copy=True)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "joint_pos": self._joint_pos.copy(),
                "joint_vel": self._joint_vel.copy(),
                "joint_effort": self._joint_effort.copy(),
                "ee_pos": None if self._ee_pos is None else self._ee_pos.copy(),
                "ee_rotvec": None if self._ee_rotvec is None else self._ee_rotvec.copy(),
                "gripper_pos": self._gripper_pos,
                "motor_temps_c": self._motor_temps_c.copy(),
                "motor_torques_nm": self._motor_torques_nm.copy(),
            }
