from __future__ import annotations
import numpy as np

from mimicrec.kinematics.fk import KinematicsConfig


class IKService:
    """Inverse kinematics for SO-101-class arms.

    Wraps `lerobot.model.kinematics.RobotKinematics.inverse_kinematics`
    (the same class FKService wraps for FK). Joint values are in **degrees**.
    Returns `(q_solved, success)`. Because placo always returns *a*
    solution, success is computed by a FK round-trip: position error < 2 cm
    AND orientation error < 0.1 rad (≈6°). Failures don't raise — they are
    surfaced as `success=False` so the action decoder can hold the seed.
    """

    POS_TOL_M = 0.02
    ANG_TOL_RAD = 0.1
    MAX_ITER = 20

    def __init__(self, cfg: KinematicsConfig):
        from pathlib import Path
        from lerobot.model.kinematics import RobotKinematics

        self._cfg = cfg
        # Resolve relative URDF paths the same way FKService does (see kinematics/fk.py:35).
        urdf_path = str(Path(cfg.urdf_path).resolve())
        self._k = RobotKinematics(
            urdf_path=urdf_path,
            target_frame_name=cfg.target_frame,
            joint_names=cfg.joint_names,
        )

    def solve(self, T_target: np.ndarray, seed: np.ndarray) -> tuple[np.ndarray, bool]:
        """Solve IK for a 4x4 target pose. `seed` is in degrees.

        Iterates up to MAX_ITER times, feeding the previous solution back as
        the seed, until the FK round-trip error drops below tolerance. placo's
        solver takes a single step per call, so iteration is needed when
        starting from a fresh instance (no warm solver state).

        Returns (q_solved_degrees, success).
        """
        q = seed.astype(np.float64)
        T_target_f64 = T_target.astype(np.float64)
        # Tight inner tolerance ensures convergence before we accept the solution;
        # the final round-trip check uses POS_TOL_M / ANG_TOL_RAD.
        _INNER_POS_TOL = 1e-4
        try:
            for _ in range(self.MAX_ITER):
                q = np.asarray(
                    self._k.inverse_kinematics(
                        q, T_target_f64, position_weight=1.0, orientation_weight=1.0
                    ),
                    dtype=np.float64,
                )
                T_actual = self._k.forward_kinematics(q)
                pos_err = float(np.linalg.norm(T_target_f64[:3, 3] - T_actual[:3, 3]))
                if pos_err < _INNER_POS_TOL:
                    break
        except Exception:
            return seed.copy(), False

        # Final acceptance check
        T_actual = self._k.forward_kinematics(q)
        pos_err = float(np.linalg.norm(T_target_f64[:3, 3] - T_actual[:3, 3]))
        R_err = T_target_f64[:3, :3].T @ T_actual[:3, :3]
        cos_ang = (np.trace(R_err) - 1.0) / 2.0
        ang_err = float(np.arccos(np.clip(cos_ang, -1.0, 1.0)))
        ok = (pos_err < self.POS_TOL_M) and (ang_err < self.ANG_TOL_RAD)
        return q, ok
