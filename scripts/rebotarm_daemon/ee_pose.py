"""End-effector pose helper using reBotArm's built-in kinematics.

Wraps Pinocchio FK on the reBotArm URDF that ships with
``reBotArm_control_py``. Returns ``(position, rotvec)`` in metres / rad,
both ``float32`` to match the protocol payloads.
"""
from __future__ import annotations

import numpy as np
import pinocchio as pin

from reBotArm_control_py.kinematics import load_robot_model


# Default end-effector frame name in the reBotArm URDF — confirmed in
# reBotArm_control_py/reBotArm_control_py/kinematics/robot_model.py
# (get_end_effector_frame_id uses "end_link") and example 10.
_DEFAULT_EE_FRAME = "end_link"


class EEPose:
    """Forward-kinematics helper bound to a single URDF model."""

    def __init__(self, ee_frame_name: str = _DEFAULT_EE_FRAME):
        self._model = load_robot_model()
        self._data = self._model.createData()
        self._frame_id = self._model.getFrameId(ee_frame_name)
        self._frame_name = ee_frame_name

    @property
    def ee_frame_name(self) -> str:
        return self._frame_name

    def pose(self, q_rad: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Compute (position_xyz_m, rotvec_rad) for joint config ``q_rad``.

        ``rotvec`` is the axis-angle ``log3`` of the rotation matrix —
        identical conventions to ``state_hub`` so downstream FK and the
        daemon EE pose agree to numerical precision.
        """
        q = np.asarray(q_rad, dtype=float)
        pin.forwardKinematics(self._model, self._data, q)
        pin.updateFramePlacements(self._model, self._data)
        T = self._data.oMf[self._frame_id]
        pos = np.asarray(T.translation, dtype=np.float32)
        rotvec = pin.log3(T.rotation).astype(np.float32)
        return pos, rotvec
