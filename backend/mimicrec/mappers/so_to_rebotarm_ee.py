"""Cross-arm EE-space teleop mapper: SO-101 leader → reBotArm follower.

Operates in **delta mode**: each tick computes how far / which way the
SO-101 EE moved since the last tick and applies that (scaled) to a
running reBotArm EE target. The reBotArm target is initialized from
the live ``state.joint_pos`` on the first tick, so the follower starts
wherever it physically is and SO-101 motion just nudges it from there.

Why delta mode (vs absolute coordinate mapping):

- No need to align SO-101 and reBotArm base frames or sizes. The
  follower starts wherever it is and offsets from there.
- ``placo``'s single-step IK stays well-conditioned because each tick's
  IK target is "current target plus a tiny delta" — the IK seed is
  always close to the solution.
- Tick-to-tick stability: when the leader is still, the delta is zero
  and the follower stops. No oscillation around an attractor.
- Generalizes: any teleop input that produces a stream of EE poses
  (or velocities) can drive this mapper with no math changes.

Orientation is forwarded in full — ΔR_world is applied to ``target_R``
on the left, so SO-101 wrist motions AND shoulder_pan rotations both
propagate to the reBotArm gripper orientation.

Both FK and IK use ``lerobot.model.kinematics.RobotKinematics`` (placo
backend) so the backend venv only needs placo — pinocchio stays in the
daemon venv.
"""
from __future__ import annotations

import logging
import os
from typing import Sequence

import numpy as np

from mimicrec.types import RobotCommand, RobotState, TeleopAction

logger = logging.getLogger(__name__)


def _ensure_ros_package_path(dirs: Sequence[str]) -> None:
    """Prepend ``dirs`` to the ROS_PACKAGE_PATH env var.

    Placo's URDF loader resolves ``package://<name>/...`` mesh URIs by
    walking ROS_PACKAGE_PATH for a directory whose ``package.xml`` has
    a matching ``<name>``. We set this here so callers don't have to
    remember to set it before importing the mapper.
    """
    existing = os.environ.get("ROS_PACKAGE_PATH", "")
    parts = [str(d) for d in dirs if d] + ([existing] if existing else [])
    os.environ["ROS_PACKAGE_PATH"] = os.pathsep.join(parts)


class SOToReBotArmEEMapper:
    """Map SO-101 leader joint actions to reBotArm joint commands via EE deltas.

    Per-tick flow:

    1. SO-101 joints (deg) → placo FK → SO-101 EE (pos, R) in world.
    2. **First tick:** initialize the running reBotArm EE target from
       the live ``state.joint_pos`` (so the follower stays put).
    3. **Subsequent ticks:** compute Δp and ΔR_world from the previous
       SO-101 EE pose. Update target:
       ``target_p += xyz_scale * Δp``,
       ``target_R = ΔR_world @ target_R``.
    4. If the leader's per-tick Δp magnitude exceeds ``max_ee_step_m``,
       treat as a discontinuity (skip the delta — operator probably
       repositioned the leader).
    5. If the new target falls outside the configured workspace box,
       reject the delta (don't update target this tick).
    6. Run placo IK on the reBotArm URDF; cache the unclamped output
       as next tick's IK seed for temporal coherence.
    7. Clamp each joint's per-tick command delta to
       ``max_joint_step_deg`` (gentle drift instead of branch-flip
       jumps).
    8. Linearly map the SO-101 gripper to the reBotArm gripper.
    """

    def __init__(
        self,
        so101_urdf_path: str,
        rebotarm_urdf_path: str,
        so101_ee_frame: str = "gripper_frame_link",
        rebotarm_ee_frame: str = "end_link",
        so101_arm_joints: Sequence[str] = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"),
        # NOTE: The reBotArm URDF has joint3 named "join3" (typo
        # carried over from upstream — also present in
        # joint_names_*.yaml). Match the URDF exactly here.
        rebotarm_arm_joints: Sequence[str] = ("joint1", "joint2", "join3", "joint4", "joint5", "joint6"),
        rebotarm_package_dirs: Sequence[str] = ("reBotArm_control_py/urdf",),
        # Position scale: reBotArm Δp = xyz_scale * SO-101 Δp.
        xyz_scale: float | Sequence[float] = 1.5,
        # Gripper linear map: SO-101 deg → reBotArm rad.
        gripper_in_min_deg: float = 0.0,
        gripper_in_max_deg: float = 100.0,
        gripper_out_min_rad: float = 0.0,
        gripper_out_max_rad: float = 1.0,
        gripper_invert: bool = False,
        # IK weights (placo soft-constraint). Orientation is small
        # because the SO-101 gripper at rest points nearly vertical
        # and reBotArm's reachable orientations there are restrictive;
        # prioritise position.
        ik_position_weight: float = 1.0,
        ik_orientation_weight: float = 0.05,
        # Leader-jump discontinuity filter: if the SO-101 EE moves
        # more than this in one tick, skip the delta (operator likely
        # repositioned the leader). Set 0 to disable.
        max_ee_step_m: float = 0.05,
        # Workspace box on the absolute reBotArm target. Targets that
        # would step outside are rejected (the running target stays
        # put for that tick).
        workspace_radius_m: float = 0.65,
        workspace_z_min_m: float = -0.2,
        workspace_z_max_m: float = 0.8,
        # Joint-space velocity clamp. Limits per-tick command delta
        # per joint, measured from the IK seed.
        max_joint_step_deg: float = 5.0,
        # IK seed strategy. When True (default), the seed is the
        # previous tick's unclamped IK output, giving placo's
        # single-step solver temporal coherence. When False, always
        # uses ``state.joint_pos``.
        seed_from_last_ik: bool = True,
        # Joint indices (0-based) to freeze at their value from the
        # first tick's IK seed. Useful for locking a wrist twist
        # joint that the orientation-IK would otherwise yank around
        # to satisfy soft-constraint orientation targets at the cost
        # of natural-looking wrist motion. The lock applies after
        # the IK and joint-step clamp, so the IK is free to do its
        # thing on the unlocked joints.
        lock_joints_at_init: Sequence[int] = (),
    ):
        from lerobot.model.kinematics import RobotKinematics

        # placo resolves package:// mesh URIs via ROS_PACKAGE_PATH; the
        # reBotArm URDF references a package by name, not a relative
        # path, so this must be set before constructing RobotWrapper.
        _ensure_ros_package_path(rebotarm_package_dirs)

        self._so101_arm_joints = list(so101_arm_joints)
        self._rebotarm_arm_joints = list(rebotarm_arm_joints)
        self._so101_fk = RobotKinematics(
            urdf_path=so101_urdf_path,
            target_frame_name=so101_ee_frame,
            joint_names=self._so101_arm_joints,
        )
        self._rebotarm_ik = RobotKinematics(
            urdf_path=rebotarm_urdf_path,
            target_frame_name=rebotarm_ee_frame,
            joint_names=self._rebotarm_arm_joints,
        )

        scale = np.asarray(xyz_scale, dtype=np.float64)
        if scale.shape == ():
            scale = np.full(3, float(scale))
        if scale.shape != (3,):
            raise ValueError(f"xyz_scale must be scalar or 3-vector, got shape {scale.shape}")
        self._xyz_scale = scale

        self._gripper_in_min = float(gripper_in_min_deg)
        self._gripper_in_max = float(gripper_in_max_deg)
        self._gripper_out_min = float(gripper_out_min_rad)
        self._gripper_out_max = float(gripper_out_max_rad)
        self._gripper_invert = bool(gripper_invert)

        self._ik_pos_w = float(ik_position_weight)
        self._ik_ori_w = float(ik_orientation_weight)
        self._max_ee_step = float(max_ee_step_m)
        self._workspace_radius = float(workspace_radius_m)
        self._workspace_z_min = float(workspace_z_min_m)
        self._workspace_z_max = float(workspace_z_max_m)
        self._max_joint_step_deg = float(max_joint_step_deg)
        self._seed_from_last_ik = bool(seed_from_last_ik)
        self._lock_joint_indices = tuple(int(i) for i in lock_joints_at_init)
        for i in self._lock_joint_indices:
            if not (0 <= i < len(self._rebotarm_arm_joints)):
                raise ValueError(
                    f"lock_joints_at_init index {i} out of range "
                    f"[0, {len(self._rebotarm_arm_joints)})"
                )
        # Filled on the first tick from the IK seed.
        self._locked_joint_values_deg: dict[int, float] = {}

        self._dof = len(self._rebotarm_arm_joints)

        # Running state: previous SO-101 EE pose, current reBotArm EE
        # target, last IK output (for stable seeding), last full
        # RobotCommand (for fallbacks). All None until the first tick
        # primes them.
        self._prev_so_pos: np.ndarray | None = None
        self._prev_so_R: np.ndarray | None = None
        self._target_pos: np.ndarray | None = None
        self._target_R: np.ndarray | None = None
        self._last_ik_output_deg: np.ndarray | None = None
        self._last_command: RobotCommand | None = None

    # -----------------------------------------------------------------
    # Public entry point
    # -----------------------------------------------------------------

    def map(self, action: TeleopAction, robot_state: RobotState) -> RobotCommand:
        if action.target_joint_pos is None:
            return self._fallback_command(robot_state, reason="action.target_joint_pos is None")

        so101 = np.asarray(action.target_joint_pos, dtype=np.float64)
        n_arm = len(self._so101_arm_joints)
        if so101.shape[0] < n_arm:
            return self._fallback_command(
                robot_state,
                reason=f"SO101 action has {so101.shape[0]} elems, need ≥{n_arm}",
            )

        try:
            T_so = self._so101_fk.forward_kinematics(so101[:n_arm])
        except Exception as e:
            return self._fallback_command(robot_state, reason=f"SO101 FK error: {type(e).__name__}: {e}")

        so_pos = np.asarray(T_so[:3, 3], dtype=np.float64)
        so_R = np.asarray(T_so[:3, :3], dtype=np.float64)

        gripper_rad = self._map_gripper(float(so101[n_arm])) if so101.shape[0] > n_arm else None

        # First-tick initialization: anchor reBotArm target at its
        # current FK pose; record SO-101 baseline. No motion this tick.
        if self._target_pos is None or self._target_R is None:
            self._initialize_target(robot_state)
            self._prev_so_pos = so_pos.copy()
            self._prev_so_R = so_R.copy()
            return self._stay_at_seed(robot_state, gripper_rad)

        # Compute SO-101 deltas in world frame.
        dp = so_pos - self._prev_so_pos
        # Right-multiplying by R_prev^T extracts the world-frame
        # rotation: R_now = ΔR_world @ R_prev → ΔR_world = R_now @ R_prev^T.
        dR_world = so_R @ self._prev_so_R.T

        # Discontinuity filter: leader jumped too far in one tick →
        # operator likely repositioned. Re-anchor the leader baseline,
        # leave the target untouched, hold the arm.
        if self._max_ee_step > 0.0:
            jump = float(np.linalg.norm(dp))
            if jump > self._max_ee_step:
                logger.warning(
                    "leader Δp=%.3f m exceeds max_ee_step_m=%.3f; treating as discontinuity",
                    jump, self._max_ee_step,
                )
                self._prev_so_pos = so_pos.copy()
                self._prev_so_R = so_R.copy()
                return self._hold_command(robot_state, gripper_rad)

        # Tentative new target. Validated against the workspace box
        # before being committed to instance state.
        new_target_pos = self._target_pos + self._xyz_scale * dp
        new_target_R = dR_world @ self._target_R

        if self._workspace_radius > 0.0:
            r = float(np.linalg.norm(new_target_pos))
            if r > self._workspace_radius:
                logger.warning(
                    "target r=%.3f m beyond workspace_radius=%.3f m; refusing delta this tick",
                    r, self._workspace_radius,
                )
                self._prev_so_pos = so_pos.copy()
                self._prev_so_R = so_R.copy()
                return self._hold_command(robot_state, gripper_rad)
        if not (self._workspace_z_min <= float(new_target_pos[2]) <= self._workspace_z_max):
            logger.warning(
                "target z=%.3f m outside [%.3f, %.3f]; refusing delta this tick",
                float(new_target_pos[2]), self._workspace_z_min, self._workspace_z_max,
            )
            self._prev_so_pos = so_pos.copy()
            self._prev_so_R = so_R.copy()
            return self._hold_command(robot_state, gripper_rad)

        # Commit target update.
        self._target_pos = new_target_pos
        self._target_R = new_target_R

        # Build IK target SE(3) and solve.
        T_target = np.eye(4)
        T_target[:3, :3] = self._target_R
        T_target[:3, 3] = self._target_pos

        seed_deg = self._seed_from_state(robot_state)
        try:
            q_deg = self._rebotarm_ik.inverse_kinematics(
                seed_deg,
                T_target,
                position_weight=self._ik_pos_w,
                orientation_weight=self._ik_ori_w,
            )
        except Exception as e:
            return self._fallback_command(robot_state, reason=f"reBotArm IK error: {type(e).__name__}: {e}")

        q_deg_raw = np.asarray(q_deg[: self._dof], dtype=np.float64)
        if not np.isfinite(q_deg_raw).all():
            return self._fallback_command(robot_state, reason="non-finite IK output")

        # Cache the unclamped IK output as next tick's seed.
        self._last_ik_output_deg = q_deg_raw.copy()

        # Joint-space velocity clamp.
        q_deg_send = q_deg_raw
        if self._max_joint_step_deg > 0.0:
            raw_delta = q_deg_raw - seed_deg
            worst = float(np.max(np.abs(raw_delta)))
            if worst > self._max_joint_step_deg:
                worst_idx = int(np.argmax(np.abs(raw_delta)))
                logger.info(
                    "joint %d wants %+.2f° this tick — clamping to ±%.2f°",
                    worst_idx, raw_delta[worst_idx], self._max_joint_step_deg,
                )
                clamped_delta = np.clip(
                    raw_delta, -self._max_joint_step_deg, self._max_joint_step_deg
                )
                q_deg_send = seed_deg + clamped_delta

        # Lock-joints override: forces specified joints back to their
        # init-tick values regardless of what the IK requested. Done
        # after the velocity clamp so the IK / clamp interaction on
        # the unlocked joints is preserved.
        if self._locked_joint_values_deg:
            q_deg_send = q_deg_send.copy()
            for idx, val in self._locked_joint_values_deg.items():
                q_deg_send[idx] = val

        q_rad = np.deg2rad(q_deg_send).astype(np.float32)

        # Roll the SO-101 baseline forward.
        self._prev_so_pos = so_pos.copy()
        self._prev_so_R = so_R.copy()

        cmd = RobotCommand(q=q_rad, gripper=gripper_rad)
        self._last_command = cmd
        return cmd

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _initialize_target(self, robot_state: RobotState) -> None:
        """Anchor the reBotArm EE target at the live robot pose and
        capture lock-joint values from the same seed.
        """
        q_rad = np.asarray(robot_state.joint_pos, dtype=np.float64)
        if q_rad.shape[0] >= self._dof:
            seed_deg = np.rad2deg(q_rad[: self._dof])
        else:
            seed_deg = np.zeros(self._dof, dtype=np.float64)
        try:
            T = self._rebotarm_ik.forward_kinematics(seed_deg)
        except Exception as e:
            logger.warning(
                "reBotArm FK at init failed (%s: %s); falling back to identity at base",
                type(e).__name__, e,
            )
            T = np.eye(4)
        self._target_pos = np.asarray(T[:3, 3], dtype=np.float64).copy()
        self._target_R = np.asarray(T[:3, :3], dtype=np.float64).copy()
        # Snapshot lock-joint values for later override.
        for i in self._lock_joint_indices:
            self._locked_joint_values_deg[i] = float(seed_deg[i])
        if self._lock_joint_indices:
            logger.info(
                "locking joints %s at init values (deg): %s",
                list(self._lock_joint_indices),
                {i: round(self._locked_joint_values_deg[i], 2)
                 for i in self._lock_joint_indices},
            )

    def _seed_from_state(self, state: RobotState) -> np.ndarray:
        """Build the IK seed in degrees (placo convention).

        When ``seed_from_last_ik`` is True (default), prefers the
        previous tick's unclamped IK output for temporal coherence;
        otherwise (and on the very first IK call) uses the live
        ``state.joint_pos``. Lock-joints are forced to their captured
        values so the IK doesn't waste degrees of freedom on joints
        we'll override anyway.
        """
        if self._seed_from_last_ik and self._last_ik_output_deg is not None:
            seed = self._last_ik_output_deg.copy()
        else:
            q_rad = np.asarray(state.joint_pos, dtype=np.float64)
            if q_rad.shape[0] >= self._dof:
                seed = np.rad2deg(q_rad[: self._dof])
            elif self._last_command is not None:
                seed = np.rad2deg(np.asarray(self._last_command.q, dtype=np.float64)[: self._dof])
            else:
                seed = np.zeros(self._dof, dtype=np.float64)
        for idx, val in self._locked_joint_values_deg.items():
            seed[idx] = val
        return seed

    def _map_gripper(self, value_deg: float) -> float:
        in_lo, in_hi = self._gripper_in_min, self._gripper_in_max
        out_lo, out_hi = self._gripper_out_min, self._gripper_out_max
        span = in_hi - in_lo
        if span == 0.0:
            return out_lo
        t = (value_deg - in_lo) / span
        t = float(np.clip(t, 0.0, 1.0))
        if self._gripper_invert:
            t = 1.0 - t
        return out_lo + t * (out_hi - out_lo)

    def _fallback_command(self, state: RobotState, reason: str) -> RobotCommand:
        """Catastrophic-fallback used when the input is malformed.

        Distinct from the workspace / discontinuity holds, which use
        ``_hold_command``: this one is for cases where we cannot
        compute *any* sensible mapping (None action, FK error, IK
        exception, NaN output).
        """
        logger.warning("SOToReBotArmEEMapper falling back: %s", reason)
        if self._last_command is not None:
            return self._last_command
        q = np.asarray(state.joint_pos, dtype=np.float32)[: self._dof].copy()
        if q.shape[0] < self._dof:
            q = np.zeros(self._dof, dtype=np.float32)
        return RobotCommand(q=q)

    def _stay_at_seed(self, robot_state: RobotState, gripper_rad: float | None) -> RobotCommand:
        """Send the current robot pose as the command (first tick).

        Distinct from ``_hold_command`` because there is no prior
        ``_last_command`` to copy.
        """
        q_rad = np.asarray(robot_state.joint_pos, dtype=np.float32)
        if q_rad.shape[0] >= self._dof:
            q = q_rad[: self._dof].copy()
        else:
            q = np.zeros(self._dof, dtype=np.float32)
        cmd = RobotCommand(q=q, gripper=gripper_rad)
        self._last_command = cmd
        return cmd

    def _hold_command(
        self,
        robot_state: RobotState,
        gripper_rad: float | None,
    ) -> RobotCommand:
        """Hold the previous arm command but let the gripper track."""
        if self._last_command is not None:
            return RobotCommand(
                q=self._last_command.q.copy(),
                gripper=gripper_rad,
            )
        return self._stay_at_seed(robot_state, gripper_rad)
