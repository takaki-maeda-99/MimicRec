"""Robot-specific Cartesian mapper for the reBotArm.

The mapper owns the kinematic part of Cartesian teleoperation: it integrates
small EE deltas, solves IK, validates the solution, and emits the joint target
understood by :class:`ReBotArmZmqAdapter`.  The daemon deliberately remains a
joint-space, high-rate safety controller.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Sequence

import numpy as np

from mimicrec.types import RobotCommand, RobotState, TeleopAction

logger = logging.getLogger(__name__)


def _ensure_ros_package_path(dirs: Sequence[str]) -> None:
    existing = os.environ.get("ROS_PACKAGE_PATH", "")
    parts = [str(d) for d in dirs if d] + ([existing] if existing else [])
    os.environ["ROS_PACKAGE_PATH"] = os.pathsep.join(parts)


def _rotvec_to_matrix(rotvec: np.ndarray) -> np.ndarray:
    """Rodrigues conversion without adding a scipy dependency."""
    theta = float(np.linalg.norm(rotvec))
    if theta < 1e-12:
        return np.eye(3, dtype=np.float64)
    axis = rotvec / theta
    x, y, z = axis
    K = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    return np.eye(3) + np.sin(theta) * K + (1.0 - np.cos(theta)) * (K @ K)


def _rotation_error_rad(actual: np.ndarray, desired: np.ndarray) -> float:
    relative = actual @ desired.T
    cos_angle = float(np.clip((np.trace(relative) - 1.0) * 0.5, -1.0, 1.0))
    return float(np.arccos(cos_angle))


def _matrix_to_rotvec(matrix: np.ndarray) -> np.ndarray:
    """SO(3) logarithm used to smooth rotations without Euler angles."""
    cos_angle = float(np.clip((np.trace(matrix) - 1.0) * 0.5, -1.0, 1.0))
    skew = np.array(
        [
            matrix[2, 1] - matrix[1, 2],
            matrix[0, 2] - matrix[2, 0],
            matrix[1, 0] - matrix[0, 1],
        ],
        dtype=np.float64,
    )
    sin_angle = float(np.linalg.norm(skew) * 0.5)
    angle = float(np.arctan2(sin_angle, cos_angle))
    if angle < 1e-12:
        return np.zeros(3, dtype=np.float64)
    if sin_angle > 1e-8:
        return skew * (angle / (2.0 * sin_angle))

    # At pi the skew part vanishes. The principal eigenvector of R + I is
    # the rotation axis; either sign represents the same pi rotation.
    eigenvalues, eigenvectors = np.linalg.eigh(matrix + np.eye(3))
    axis = eigenvectors[:, int(np.argmax(eigenvalues))]
    return axis * angle


class DeltaEEToReBotArmMapper:
    """Convert Cartesian teleop actions into safe reBotArm joint targets.

    ``ee_delta`` is ``[dx, dy, dz, rx, ry, rz]``. Translation is metres and
    rotation is an axis-angle rotation vector in radians. In ``base`` frame
    both are expressed in the robot base frame; in ``ee_local`` frame they are
    expressed in the current target EE frame. ``ee_pose_offset`` uses the same
    units but is absolute relative to the EE pose captured at clutch start.
    """

    def __init__(
        self,
        rebotarm_urdf_path: str,
        rebotarm_ee_frame: str = "end_link",
        rebotarm_arm_joints: Sequence[str] = (
            "joint1",
            "joint2",
            "join3",
            "joint4",
            "joint5",
            "joint6",
        ),
        rebotarm_package_dirs: Sequence[str] = ("third_party/reBotArm_control_py/urdf",),
        delta_frame: str = "base",
        translation_scale: float | Sequence[float] = 1.0,
        rotation_scale: float = 1.0,
        ik_position_weight: float = 1.0,
        ik_orientation_weight: float = 0.05,
        max_linear_delta_m: float = 0.02,
        max_angular_delta_rad: float = 0.15,
        max_pose_linear_offset_m: float = 0.5,
        max_pose_angular_offset_rad: float = np.pi,
        max_pose_linear_step_m: float = 0.0,
        max_pose_angular_step_rad: float = 0.0,
        pose_smoothing_time_constant_sec: float = 0.0,
        pose_smoothing_max_dt_sec: float = 0.05,
        workspace_radius_m: float = 0.65,
        workspace_z_min_m: float = -0.2,
        workspace_z_max_m: float = 0.8,
        max_joint_step_deg: float = 5.0,
        max_ik_backtracking_steps: int = 0,
        ik_posture_weight: float = 0.0,
        ik_velocity_limit_deg_s: float = 0.0,
        ik_control_rate_hz: float = 60.0,
        ik_hard_position_constraint: bool = False,
        joint_pos_min_deg: Sequence[float] | None = None,
        joint_pos_max_deg: Sequence[float] | None = None,
        max_ik_position_error_m: float = 0.03,
        max_ik_orientation_error_rad: float = 0.5,
        seed_from_last_command: bool = False,
        seed_from_last_ik: bool = True,
        lock_joints_at_init: Sequence[int] = (),
        floor_plane_normal: Sequence[float] = (0.0, 0.0, 1.0),
        floor_plane_offset_m: float = 0.0,
        floor_clearance_m: float = 0.0,
        floor_collision_frames: Sequence[str] = (),
        floor_path_samples: int = 5,
        gripper_min_rad: float | None = None,
        gripper_max_rad: float | None = None,
        gripper_open_rad: float | None = None,
        gripper_closed_rad: float | None = None,
        gripper_smoothing_time_constant_sec: float = 0.05,
    ):
        from lerobot.model.kinematics import RobotKinematics

        if delta_frame not in {"base", "ee_local"}:
            raise ValueError("delta_frame must be 'base' or 'ee_local'")
        _ensure_ros_package_path(rebotarm_package_dirs)

        self._rebotarm_arm_joints = list(rebotarm_arm_joints)
        self._dof = len(self._rebotarm_arm_joints)
        self._rebotarm_ik = RobotKinematics(
            urdf_path=rebotarm_urdf_path,
            target_frame_name=rebotarm_ee_frame,
            joint_names=self._rebotarm_arm_joints,
        )
        scale = np.asarray(translation_scale, dtype=np.float64)
        if scale.shape == ():
            scale = np.full(3, float(scale))
        if scale.shape != (3,):
            raise ValueError(
                f"translation_scale must be scalar or 3-vector, got {scale.shape}"
            )
        self._translation_scale = scale
        self._rotation_scale = float(rotation_scale)
        self._delta_frame = delta_frame
        self._ik_pos_w = float(ik_position_weight)
        self._ik_ori_w = float(ik_orientation_weight)
        self._max_linear_delta = float(max_linear_delta_m)
        self._max_angular_delta = float(max_angular_delta_rad)
        self._max_pose_linear_offset = float(max_pose_linear_offset_m)
        self._max_pose_angular_offset = float(max_pose_angular_offset_rad)
        self._max_pose_linear_step = float(max_pose_linear_step_m)
        self._max_pose_angular_step = float(max_pose_angular_step_rad)
        if self._max_pose_linear_step < 0.0:
            raise ValueError("max_pose_linear_step_m must be >= 0")
        if self._max_pose_angular_step < 0.0:
            raise ValueError("max_pose_angular_step_rad must be >= 0")
        self._pose_smoothing_tau = float(pose_smoothing_time_constant_sec)
        self._pose_smoothing_max_dt = float(pose_smoothing_max_dt_sec)
        if self._pose_smoothing_tau < 0.0:
            raise ValueError("pose_smoothing_time_constant_sec must be >= 0")
        if self._pose_smoothing_max_dt < 0.0:
            raise ValueError("pose_smoothing_max_dt_sec must be >= 0")
        self._monotonic = time.monotonic
        self._workspace_radius = float(workspace_radius_m)
        self._workspace_z_min = float(workspace_z_min_m)
        self._workspace_z_max = float(workspace_z_max_m)
        self._max_joint_step_deg = float(max_joint_step_deg)
        self._max_ik_backtracking_steps = int(max_ik_backtracking_steps)
        if self._max_ik_backtracking_steps < 0:
            raise ValueError("max_ik_backtracking_steps must be >= 0")
        self._ik_posture_weight = float(ik_posture_weight)
        if self._ik_posture_weight < 0.0:
            raise ValueError("ik_posture_weight must be >= 0")
        self._ik_velocity_limit_deg_s = float(ik_velocity_limit_deg_s)
        self._ik_control_rate_hz = float(ik_control_rate_hz)
        self._ik_hard_position_constraint = bool(ik_hard_position_constraint)
        if self._ik_velocity_limit_deg_s < 0.0:
            raise ValueError("ik_velocity_limit_deg_s must be >= 0")
        if self._ik_control_rate_hz <= 0.0:
            raise ValueError("ik_control_rate_hz must be > 0")
        self._max_ik_position_error = float(max_ik_position_error_m)
        self._max_ik_orientation_error = float(max_ik_orientation_error_rad)
        self._seed_from_last_command = bool(seed_from_last_command)
        self._seed_from_last_ik = bool(seed_from_last_ik)
        self._joint_min = self._optional_joint_vector(
            joint_pos_min_deg, "joint_pos_min_deg"
        )
        self._joint_max = self._optional_joint_vector(
            joint_pos_max_deg, "joint_pos_max_deg"
        )
        if self._joint_min is not None and self._joint_max is not None:
            if np.any(self._joint_min >= self._joint_max):
                raise ValueError(
                    "joint_pos_min_deg must be lower than joint_pos_max_deg"
                )

        self._ik_posture_task = None
        if self._ik_posture_weight > 0.0:
            self._ik_posture_task = self._rebotarm_ik.solver.add_joints_task()
            self._ik_posture_task.configure(
                "teleop_posture", "soft", self._ik_posture_weight
            )
        if self._ik_velocity_limit_deg_s > 0.0:
            velocity_rad_s = np.deg2rad(self._ik_velocity_limit_deg_s)
            for joint_name in self._rebotarm_arm_joints:
                self._rebotarm_ik.robot.set_velocity_limit(
                    joint_name, velocity_rad_s
                )
            self._rebotarm_ik.solver.dt = 1.0 / self._ik_control_rate_hz
            self._rebotarm_ik.solver.enable_velocity_limits(True)

        self._lock_joint_indices = tuple(int(i) for i in lock_joints_at_init)
        for i in self._lock_joint_indices:
            if not 0 <= i < self._dof:
                raise ValueError(
                    f"lock_joints_at_init index {i} out of range [0, {self._dof})"
                )
        self._locked_joint_values_deg: dict[int, float] = {}

        floor_normal = np.asarray(floor_plane_normal, dtype=np.float64)
        if floor_normal.shape != (3,) or not np.isfinite(floor_normal).all():
            raise ValueError("floor_plane_normal must contain 3 finite values")
        floor_normal_norm = float(np.linalg.norm(floor_normal))
        if floor_normal_norm < 1e-9:
            raise ValueError("floor_plane_normal must be non-zero")
        self._floor_plane_normal = floor_normal / floor_normal_norm
        self._floor_plane_offset = float(floor_plane_offset_m)
        self._floor_clearance = float(floor_clearance_m)
        if self._floor_clearance < 0.0:
            raise ValueError("floor_clearance_m must be >= 0")
        self._floor_path_samples = int(floor_path_samples)
        if self._floor_path_samples < 2:
            raise ValueError("floor_path_samples must be >= 2")
        self._floor_geometries = self._build_floor_geometries(
            tuple(str(name) for name in floor_collision_frames)
        )
        self._gripper_min = gripper_min_rad
        self._gripper_max = gripper_max_rad
        self._gripper_open = gripper_open_rad
        self._gripper_closed = gripper_closed_rad
        self._gripper_smoothing_tau = float(gripper_smoothing_time_constant_sec)
        if self._gripper_smoothing_tau < 0.0:
            raise ValueError("gripper_smoothing_time_constant_sec must be >= 0")
        if (self._gripper_open is None) != (self._gripper_closed is None):
            raise ValueError(
                "gripper_open_rad and gripper_closed_rad must be set together"
            )
        if (
            self._gripper_open is not None
            and self._gripper_closed is not None
            and self._gripper_open == self._gripper_closed
        ):
            raise ValueError("gripper open and closed positions must differ")
        self._gripper_target: float | None = None
        self._gripper_filter_last_at: float | None = None

        self._target_pos: np.ndarray | None = None
        self._target_R: np.ndarray | None = None
        self._pose_anchor_pos: np.ndarray | None = None
        self._pose_anchor_R: np.ndarray | None = None
        self._desired_pose_pos: np.ndarray | None = None
        self._desired_pose_R: np.ndarray | None = None
        self._filtered_pose_translation: np.ndarray | None = None
        self._filtered_pose_R: np.ndarray | None = None
        self._pose_filter_last_at: float | None = None
        self._pose_mode_active = False
        self._last_ik_output_deg: np.ndarray | None = None
        self._last_command: RobotCommand | None = None
        self._last_ik_position_error: float | None = None
        self._last_ik_orientation_error: float | None = None
        self._joint_step_limited = False
        self._ik_backtrack_count = 0
        self._floor_clearance_last_m: float | None = None
        self._last_rejection_reason = ""

    def _optional_joint_vector(
        self, value: Sequence[float] | None, name: str
    ) -> np.ndarray | None:
        if value is None:
            return None
        arr = np.asarray(value, dtype=np.float64)
        if arr.shape != (self._dof,):
            raise ValueError(f"{name} must have {self._dof} values, got {arr.shape}")
        return arr

    def _build_floor_geometries(
        self, frame_names: tuple[str, ...]
    ) -> list[tuple[str, np.ndarray, np.ndarray]]:
        """Cache conservative local AABB corners for selected URDF meshes."""
        if not frame_names or self._floor_clearance <= 0.0:
            return []
        requested = set(frame_names)
        result: list[tuple[str, np.ndarray, np.ndarray]] = []
        robot = self._rebotarm_ik.robot
        for geometry_object in robot.collision_model.geometryObjects:
            frame_name = str(robot.model.frames[geometry_object.parentFrame].name)
            if frame_name not in requested:
                continue
            geometry_object.geometry.computeLocalAABB()
            lower = np.asarray(
                geometry_object.geometry.aabb_local.min_, dtype=np.float64
            )
            upper = np.asarray(
                geometry_object.geometry.aabb_local.max_, dtype=np.float64
            )
            corners = np.array(
                [
                    [x, y, z]
                    for x in (lower[0], upper[0])
                    for y in (lower[1], upper[1])
                    for z in (lower[2], upper[2])
                ],
                dtype=np.float64,
            )
            frame_to_geometry = np.asarray(
                geometry_object.placement.homogeneous, dtype=np.float64
            )
            result.append((frame_name, frame_to_geometry, corners))
        missing = requested - {item[0] for item in result}
        if missing:
            raise ValueError(
                "floor_collision_frames missing from URDF collision model: "
                + ", ".join(sorted(missing))
            )
        return result

    def map(self, action: TeleopAction, robot_state: RobotState) -> RobotCommand:
        self._joint_step_limited = False
        self._ik_backtrack_count = 0
        self._last_rejection_reason = ""
        gripper = self._map_gripper(
            action.gripper_fraction, action.gripper_delta, robot_state
        )

        if action.ee_pose_active is False and self._pose_mode_active:
            self._release_pose_reference()

        if action.ee_pose_offset is not None and action.ee_pose_active is not False:
            offset = np.asarray(action.ee_pose_offset, dtype=np.float64)
            if offset.shape != (6,) or not np.isfinite(offset).all():
                return self._fallback_command(
                    robot_state, f"invalid ee_pose_offset shape/value: {offset}"
                )
            return self._map_pose_offset(offset, robot_state, gripper)

        if action.ee_delta is None:
            if action.ee_pose_active is False:
                return self._hold_without_warning(robot_state, gripper)
            return self._fallback_command(robot_state, "action.ee_delta is None")
        delta = np.asarray(action.ee_delta, dtype=np.float64)
        if delta.shape != (6,) or not np.isfinite(delta).all():
            return self._fallback_command(
                robot_state, f"invalid ee_delta shape/value: {delta}"
            )

        if self._target_pos is None or self._target_R is None:
            self._initialize_target(robot_state)
            return self._stay_at_seed(robot_state, gripper)

        dp = (
            self._limit_norm(delta[:3], self._max_linear_delta)
            * self._translation_scale
        )
        drot = (
            self._limit_norm(delta[3:], self._max_angular_delta) * self._rotation_scale
        )
        return self._map_transform_delta(
            dp, _rotvec_to_matrix(drot), robot_state, gripper
        )

    def _map_pose_offset(
        self,
        offset: np.ndarray,
        robot_state: RobotState,
        gripper: float | None,
    ) -> RobotCommand:
        if not self._pose_mode_active:
            self._pose_mode_active = True
            self._target_pos = None
            self._target_R = None
            self._last_ik_output_deg = None
            self._filtered_pose_translation = np.zeros(3, dtype=np.float64)
            self._filtered_pose_R = np.eye(3, dtype=np.float64)
            self._pose_filter_last_at = self._monotonic()

        if self._pose_anchor_pos is None or self._pose_anchor_R is None:
            self._initialize_target(robot_state)
            assert self._target_pos is not None and self._target_R is not None
            self._pose_anchor_pos = self._target_pos.copy()
            self._pose_anchor_R = self._target_R.copy()

        desired_dp = (
            self._limit_norm(offset[:3], self._max_pose_linear_offset)
            * self._translation_scale
        )
        desired_drot = (
            self._limit_norm(offset[3:], self._max_pose_angular_offset)
            * self._rotation_scale
        )
        dp, dR = self._smooth_pose_offset(desired_dp, _rotvec_to_matrix(desired_drot))
        if self._delta_frame == "ee_local":
            desired_target_pos = self._pose_anchor_pos + self._pose_anchor_R @ dp
            desired_target_R = self._pose_anchor_R @ dR
        else:
            desired_target_pos = self._pose_anchor_pos + dp
            desired_target_R = dR @ self._pose_anchor_R
        self._desired_pose_pos = desired_target_pos.copy()
        self._desired_pose_R = desired_target_R.copy()
        new_target_pos, new_target_R = self._slew_pose_target(
            desired_target_pos, desired_target_R, robot_state
        )
        return self._map_target(new_target_pos, new_target_R, robot_state, gripper)

    def _slew_pose_target(
        self,
        desired_pos: np.ndarray,
        desired_R: np.ndarray,
        robot_state: RobotState,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Take one bounded SE(3) step toward an absolute controller target.

        This is deliberately a rate/step limiter rather than a low-pass
        filter: repeating the same absolute target reaches it exactly, while
        a fast controller gesture cannot become one large local-IK jump.
        """
        assert self._target_pos is not None and self._target_R is not None
        if (
            self._max_pose_linear_step <= 0.0
            and self._max_pose_angular_step <= 0.0
        ):
            return desired_pos, desired_R

        # A joint-step-limited command may lag the last valid IK target. Start
        # the next Cartesian step from the command actually sent so the local
        # solver never sees that lag accumulate over several fast input ticks.
        start_pos = self._target_pos
        start_R = self._target_R
        if self._seed_from_last_command:
            try:
                if self._last_command is not None:
                    sent_deg = np.rad2deg(
                        np.asarray(self._last_command.q, dtype=np.float64)[
                            : self._dof
                        ]
                    )
                else:
                    sent_deg = self._state_deg(robot_state)
                sent_pose = self._rebotarm_ik.forward_kinematics(
                    sent_deg
                )
                start_pos = np.asarray(sent_pose[:3, 3], dtype=np.float64)
                start_R = np.asarray(sent_pose[:3, :3], dtype=np.float64)
            except Exception:
                logger.debug(
                    "Failed to compute sent-command pose for target slew",
                    exc_info=True,
                )
        position_step = self._limit_norm(
            desired_pos - start_pos, self._max_pose_linear_step
        )
        rotation_error = _matrix_to_rotvec(desired_R @ start_R.T)
        rotation_step = self._limit_norm(
            rotation_error, self._max_pose_angular_step
        )
        return (
            start_pos + position_step,
            _rotvec_to_matrix(rotation_step) @ start_R,
        )

    def _smooth_pose_offset(
        self, desired_translation: np.ndarray, desired_R: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        assert self._filtered_pose_translation is not None
        assert self._filtered_pose_R is not None
        if self._pose_smoothing_tau <= 0.0:
            self._filtered_pose_translation = desired_translation.copy()
            self._filtered_pose_R = desired_R.copy()
            self._pose_filter_last_at = self._monotonic()
            return desired_translation, desired_R

        now = self._monotonic()
        previous_at = self._pose_filter_last_at
        self._pose_filter_last_at = now
        dt = 0.0 if previous_at is None else max(0.0, now - previous_at)
        if self._pose_smoothing_max_dt > 0.0:
            dt = min(dt, self._pose_smoothing_max_dt)
        alpha = 1.0 - np.exp(-dt / self._pose_smoothing_tau)

        self._filtered_pose_translation += alpha * (
            desired_translation - self._filtered_pose_translation
        )
        rotation_error = _matrix_to_rotvec(
            desired_R @ self._filtered_pose_R.T
        )
        self._filtered_pose_R = (
            _rotvec_to_matrix(alpha * rotation_error) @ self._filtered_pose_R
        )
        return self._filtered_pose_translation.copy(), self._filtered_pose_R.copy()

    def _release_pose_reference(self) -> None:
        self._pose_mode_active = False
        self._pose_anchor_pos = None
        self._pose_anchor_R = None
        self._desired_pose_pos = None
        self._desired_pose_R = None
        self._filtered_pose_translation = None
        self._filtered_pose_R = None
        self._pose_filter_last_at = None
        # A new clutch must anchor from measured robot state, not from a target
        # left behind by the previous clutch gesture.
        self._target_pos = None
        self._target_R = None
        self._last_ik_output_deg = None

    def reset(self) -> None:
        """Discard all Cartesian/clutch state after an external home move."""
        self._release_pose_reference()
        self._last_command = None
        self._gripper_target = None
        self._gripper_filter_last_at = None
        self._locked_joint_values_deg.clear()
        self._last_ik_position_error = None
        self._last_ik_orientation_error = None
        self._joint_step_limited = False
        self._ik_backtrack_count = 0
        self._floor_clearance_last_m = None
        self._last_rejection_reason = ""

    @staticmethod
    def _limit_norm(value: np.ndarray, maximum: float) -> np.ndarray:
        norm = float(np.linalg.norm(value))
        if maximum > 0.0 and norm > maximum:
            return value * (maximum / norm)
        return value

    def _map_transform_delta(
        self,
        dp: np.ndarray,
        dR: np.ndarray,
        robot_state: RobotState,
        gripper: float | None,
    ) -> RobotCommand:
        assert self._target_pos is not None and self._target_R is not None
        if self._delta_frame == "ee_local":
            new_target_pos = self._target_pos + self._target_R @ dp
            new_target_R = self._target_R @ dR
        else:
            new_target_pos = self._target_pos + dp
            new_target_R = dR @ self._target_R

        return self._map_target(new_target_pos, new_target_R, robot_state, gripper)

    def _map_target(
        self,
        new_target_pos: np.ndarray,
        new_target_R: np.ndarray,
        robot_state: RobotState,
        gripper: float | None,
    ) -> RobotCommand:
        command_reference = self._command_reference_deg(robot_state)
        try:
            start_pose = self._rebotarm_ik.forward_kinematics(command_reference)
        except Exception as exc:
            return self._hold_command(
                robot_state, gripper, f"IK seed FK error: {exc}"
            )
        start_pos = np.asarray(start_pose[:3, 3], dtype=np.float64)
        start_R = np.asarray(start_pose[:3, :3], dtype=np.float64)
        total_rotation = _matrix_to_rotvec(new_target_R @ start_R.T)
        last_reason = "IK candidate rejected"

        for attempt in range(self._max_ik_backtracking_steps + 1):
            fraction = 0.5**attempt
            candidate_pos = start_pos + fraction * (new_target_pos - start_pos)
            candidate_R = _rotvec_to_matrix(fraction * total_rotation) @ start_R
            q_candidate, reason = self._solve_ik_candidate(
                candidate_pos,
                candidate_R,
                command_reference,
            )
            if q_candidate is None:
                last_reason = reason
                if "joint discontinuity" in reason:
                    self._joint_step_limited = True
                continue

            floor_clearances = self._path_floor_clearance(
                command_reference, q_candidate
            )
            if floor_clearances is not None:
                minimum_clearance, start_clearance, end_clearance = floor_clearances
                if start_clearance >= self._floor_clearance:
                    floor_safe = minimum_clearance >= self._floor_clearance
                else:
                    # If calibration starts below the configured plane, do
                    # not trap the arm there: only a monotonic non-worsening
                    # step with a strictly higher endpoint may escape.
                    floor_safe = (
                        minimum_clearance >= start_clearance - 1e-6
                        and end_clearance > start_clearance + 1e-6
                    )
                if not floor_safe:
                    last_reason = (
                        "predicted collision mesh floor clearance "
                        f"{minimum_clearance:.4f} m"
                    )
                    continue

            self._ik_backtrack_count = attempt
            self._target_pos = candidate_pos
            self._target_R = candidate_R
            self._last_ik_output_deg = q_candidate.copy()
            command = RobotCommand(
                q=np.deg2rad(q_candidate).astype(np.float32),
                gripper=gripper,
            )
            self._last_command = command
            return command

        self._ik_backtrack_count = self._max_ik_backtracking_steps + 1
        self._last_rejection_reason = last_reason
        return self._hold_command(robot_state, gripper, last_reason)

    def _solve_ik_candidate(
        self,
        target_pos: np.ndarray,
        target_R: np.ndarray,
        command_reference: np.ndarray,
    ) -> tuple[np.ndarray | None, str]:
        """Solve and validate one Cartesian candidate without joint clipping."""
        if (
            self._workspace_radius > 0.0
            and np.linalg.norm(target_pos) > self._workspace_radius
        ):
            return None, "target outside workspace radius"
        if not self._workspace_z_min <= float(target_pos[2]) <= self._workspace_z_max:
            return None, "target outside workspace Z bounds"

        if self._ik_posture_task is not None:
            self._ik_posture_task.set_joints(
                {
                    name: float(np.deg2rad(command_reference[index]))
                    for index, name in enumerate(self._rebotarm_arm_joints)
                }
            )
        T_target = np.eye(4)
        T_target[:3, :3] = target_R
        T_target[:3, 3] = target_pos
        try:
            q_deg = self._inverse_kinematics(command_reference, T_target)
        except Exception as exc:
            return None, f"IK error: {type(exc).__name__}: {exc}"

        q_candidate = np.asarray(q_deg[: self._dof], dtype=np.float64)
        if q_candidate.shape != (self._dof,) or not np.isfinite(q_candidate).all():
            return None, "non-finite IK output"
        if self._locked_joint_values_deg:
            q_candidate = q_candidate.copy()
            for idx, value in self._locked_joint_values_deg.items():
                q_candidate[idx] = value
        if self._joint_min is not None and np.any(q_candidate < self._joint_min):
            return None, "IK output below joint limits"
        if self._joint_max is not None and np.any(q_candidate > self._joint_max):
            return None, "IK output above joint limits"
        if self._max_joint_step_deg > 0.0:
            largest_step = float(np.max(np.abs(q_candidate - command_reference)))
            if largest_step > self._max_joint_step_deg + 1e-9:
                return (
                    None,
                    "IK joint discontinuity "
                    f"{largest_step:.3f} deg > {self._max_joint_step_deg:.3f} deg",
                )

        try:
            achieved = self._rebotarm_ik.forward_kinematics(q_candidate)
            pos_error = float(np.linalg.norm(achieved[:3, 3] - target_pos))
            ori_error = _rotation_error_rad(achieved[:3, :3], target_R)
        except Exception as exc:
            return None, f"IK validation FK error: {exc}"
        self._last_ik_position_error = pos_error
        self._last_ik_orientation_error = ori_error
        if (
            self._max_ik_position_error > 0.0
            and pos_error > self._max_ik_position_error
        ):
            return None, f"IK position residual {pos_error:.4f} m"
        if (
            self._max_ik_orientation_error > 0.0
            and ori_error > self._max_ik_orientation_error
        ):
            return None, f"IK orientation residual {ori_error:.3f} rad"
        return q_candidate, ""

    def _inverse_kinematics(
        self, command_reference: np.ndarray, T_target: np.ndarray
    ) -> np.ndarray:
        if not self._ik_hard_position_constraint:
            return np.asarray(
                self._rebotarm_ik.inverse_kinematics(
                    command_reference,
                    T_target,
                    position_weight=self._ik_pos_w,
                    orientation_weight=self._ik_ori_w,
                ),
                dtype=np.float64,
            )

        # The LeRobot wrapper configures both components as soft tasks. For
        # pivot rotations that allows orientation progress to trade away EEF
        # position and produces the observed downward arc. Keep translation
        # hard and let only orientation lag when velocity/limits make the full
        # step infeasible.
        robot = self._rebotarm_ik.robot
        for index, joint_name in enumerate(self._rebotarm_arm_joints):
            robot.set_joint(joint_name, float(np.deg2rad(command_reference[index])))
        robot.update_kinematics()
        tip_frame = self._rebotarm_ik.tip_frame
        tip_frame.T_world_frame = T_target
        tip_frame.position().configure(
            "teleop_position", "hard", self._ik_pos_w
        )
        tip_frame.orientation().configure(
            "teleop_orientation", "soft", self._ik_ori_w
        )
        self._rebotarm_ik.solver.solve(True)
        robot.update_kinematics()
        return np.rad2deg(
            np.array(
                [robot.get_joint(name) for name in self._rebotarm_arm_joints],
                dtype=np.float64,
            )
        )

    def _command_reference_deg(self, state: RobotState) -> np.ndarray:
        if self._last_command is not None:
            command_q = np.asarray(self._last_command.q, dtype=np.float64)
            if command_q.shape[0] >= self._dof and np.isfinite(
                command_q[: self._dof]
            ).all():
                return np.rad2deg(command_q[: self._dof])
        return self._state_deg(state)

    def _path_floor_clearance(
        self, start_deg: np.ndarray, end_deg: np.ndarray
    ) -> tuple[float, float, float] | None:
        if not self._floor_geometries:
            self._floor_clearance_last_m = None
            return None
        path_clearances: list[float] = []
        for fraction in np.linspace(0.0, 1.0, self._floor_path_samples):
            q_deg = start_deg + fraction * (end_deg - start_deg)
            self._rebotarm_ik.forward_kinematics(q_deg)
            robot = self._rebotarm_ik.robot
            sample_minimum = float("inf")
            for frame_name, frame_to_geometry, corners in self._floor_geometries:
                world_to_frame = np.asarray(
                    robot.get_T_world_frame(frame_name), dtype=np.float64
                )
                world_to_geometry = world_to_frame @ frame_to_geometry
                world_corners = (
                    corners @ world_to_geometry[:3, :3].T
                    + world_to_geometry[:3, 3]
                )
                distances = (
                    world_corners @ self._floor_plane_normal
                    - self._floor_plane_offset
                )
                sample_minimum = min(sample_minimum, float(np.min(distances)))
            path_clearances.append(sample_minimum)
        minimum = min(path_clearances)
        self._floor_clearance_last_m = minimum
        return minimum, path_clearances[0], path_clearances[-1]

    def _initialize_target(self, state: RobotState) -> None:
        seed = self._state_deg(state)
        T = self._rebotarm_ik.forward_kinematics(seed)
        self._target_pos = np.asarray(T[:3, 3], dtype=np.float64).copy()
        self._target_R = np.asarray(T[:3, :3], dtype=np.float64).copy()
        for idx in self._lock_joint_indices:
            self._locked_joint_values_deg[idx] = float(seed[idx])

    def _state_deg(self, state: RobotState) -> np.ndarray:
        q = np.asarray(state.joint_pos, dtype=np.float64)
        if q.shape[0] < self._dof:
            return np.zeros(self._dof, dtype=np.float64)
        return np.rad2deg(q[: self._dof])

    def _seed_from_state(self, state: RobotState) -> np.ndarray:
        if self._seed_from_last_command and self._last_command is not None:
            command_q = np.asarray(self._last_command.q, dtype=np.float64)
            if command_q.shape[0] >= self._dof and np.isfinite(
                command_q[: self._dof]
            ).all():
                seed = np.rad2deg(command_q[: self._dof])
            else:
                seed = self._state_deg(state)
        elif self._seed_from_last_ik and self._last_ik_output_deg is not None:
            seed = self._last_ik_output_deg.copy()
        else:
            seed = self._state_deg(state)
        for idx, value in self._locked_joint_values_deg.items():
            seed[idx] = value
        return seed

    def telemetry(
        self, state: RobotState, command: RobotCommand
    ) -> dict[str, float]:
        """Return target/command/measured Cartesian errors for tuning."""
        if self._target_pos is None or self._target_R is None:
            return {}
        values: dict[str, float] = {
            "teleop_joint_step_limited": float(self._joint_step_limited),
            "teleop_ik_backtrack_count": float(self._ik_backtrack_count),
            "teleop_ik_rejected": float(bool(self._last_rejection_reason)),
        }
        if self._floor_clearance_last_m is not None:
            values["teleop_floor_clearance_m"] = self._floor_clearance_last_m
        if self._last_ik_position_error is not None:
            values["teleop_ik_position_residual_m"] = self._last_ik_position_error
        if self._last_ik_orientation_error is not None:
            values[
                "teleop_ik_orientation_residual_rad"
            ] = self._last_ik_orientation_error
        if self._desired_pose_pos is not None and self._desired_pose_R is not None:
            desired_position_gap = float(
                np.linalg.norm(self._desired_pose_pos - self._target_pos)
            )
            desired_orientation_gap = _rotation_error_rad(
                self._desired_pose_R, self._target_R
            )
            values["teleop_desired_position_gap_m"] = desired_position_gap
            values[
                "teleop_desired_orientation_gap_rad"
            ] = desired_orientation_gap
            values["teleop_pose_slew_active"] = float(
                desired_position_gap > 1e-9 or desired_orientation_gap > 1e-9
            )
        try:
            measured = self._rebotarm_ik.forward_kinematics(self._state_deg(state))
            values["teleop_measured_position_error_m"] = float(
                np.linalg.norm(measured[:3, 3] - self._target_pos)
            )
            values["teleop_measured_orientation_error_rad"] = _rotation_error_rad(
                measured[:3, :3], self._target_R
            )

            command_deg = np.rad2deg(
                np.asarray(command.q, dtype=np.float64)[: self._dof]
            )
            measured_deg = self._state_deg(state)
            for index, error_deg in enumerate(command_deg - measured_deg, start=1):
                values[f"teleop_joint_{index}_command_error_deg"] = float(
                    error_deg
                )
            daemon_target = state.daemon_target_joint_pos
            if daemon_target is not None:
                daemon_target_rad = np.asarray(daemon_target, dtype=np.float64)
                if (
                    daemon_target_rad.shape[0] >= self._dof
                    and np.isfinite(daemon_target_rad[: self._dof]).all()
                ):
                    daemon_target_deg = np.rad2deg(
                        daemon_target_rad[: self._dof]
                    )
                    for index in range(self._dof):
                        joint_number = index + 1
                        values[
                            f"teleop_joint_{joint_number}_daemon_ramp_error_deg"
                        ] = float(command_deg[index] - daemon_target_deg[index])
                        values[
                            f"teleop_joint_{joint_number}_motor_tracking_error_deg"
                        ] = float(daemon_target_deg[index] - measured_deg[index])
            commanded = self._rebotarm_ik.forward_kinematics(command_deg)
            values["teleop_command_position_error_m"] = float(
                np.linalg.norm(commanded[:3, 3] - self._target_pos)
            )
            values["teleop_command_orientation_error_rad"] = _rotation_error_rad(
                commanded[:3, :3], self._target_R
            )
        except Exception:
            logger.debug("Failed to compute teleop Cartesian telemetry", exc_info=True)
        return values

    def _map_gripper(
        self,
        fraction: float | None,
        delta: float | None,
        state: RobotState,
    ) -> float | None:
        if fraction is not None:
            if not np.isfinite(fraction):
                return self._gripper_target
            if self._gripper_open is None or self._gripper_closed is None:
                logger.warning(
                    "Ignoring absolute gripper input: open/closed positions unset"
                )
                return self._gripper_target
            normalized = float(np.clip(fraction, 0.0, 1.0))
            desired = float(
                self._gripper_open
                + normalized * (self._gripper_closed - self._gripper_open)
            )
            now = self._monotonic()
            if self._gripper_target is None:
                self._gripper_target = (
                    float(state.gripper_pos)
                    if state.gripper_pos is not None
                    and np.isfinite(state.gripper_pos)
                    else desired
                )
                self._gripper_filter_last_at = now
            previous_at = self._gripper_filter_last_at
            self._gripper_filter_last_at = now
            dt = 0.0 if previous_at is None else max(0.0, now - previous_at)
            dt = min(dt, 0.05)
            alpha = (
                1.0
                if self._gripper_smoothing_tau <= 0.0
                else 1.0 - np.exp(-dt / self._gripper_smoothing_tau)
            )
            self._gripper_target += alpha * (desired - self._gripper_target)
            return self._clamp_gripper(self._gripper_target)

        if delta is None:
            return self._gripper_target
        if self._gripper_target is None:
            self._gripper_target = state.gripper_pos
        if self._gripper_target is None:
            return None
        self._gripper_target += float(delta)
        return self._clamp_gripper(self._gripper_target)

    def _clamp_gripper(self, value: float) -> float:
        self._gripper_target = float(value)
        if self._gripper_min is not None:
            self._gripper_target = max(float(self._gripper_min), self._gripper_target)
        if self._gripper_max is not None:
            self._gripper_target = min(float(self._gripper_max), self._gripper_target)
        return self._gripper_target

    def _fallback_command(self, state: RobotState, reason: str) -> RobotCommand:
        logger.warning("DeltaEEToReBotArmMapper falling back: %s", reason)
        if self._last_command is not None:
            return self._last_command
        return RobotCommand(q=np.deg2rad(self._state_deg(state)).astype(np.float32))

    def _stay_at_seed(self, state: RobotState, gripper: float | None) -> RobotCommand:
        command = RobotCommand(
            q=np.deg2rad(self._state_deg(state)).astype(np.float32), gripper=gripper
        )
        self._last_command = command
        return command

    def _hold_command(
        self,
        state: RobotState,
        gripper: float | None,
        reason: str = "constraint rejected delta",
    ) -> RobotCommand:
        logger.warning("DeltaEEToReBotArmMapper holding: %s", reason)
        if self._last_command is not None:
            return RobotCommand(q=self._last_command.q.copy(), gripper=gripper)
        return self._stay_at_seed(state, gripper)

    def _hold_without_warning(
        self, state: RobotState, gripper: float | None
    ) -> RobotCommand:
        if self._last_command is not None:
            return RobotCommand(q=self._last_command.q.copy(), gripper=gripper)
        return self._stay_at_seed(state, gripper)
