"""Hierarchical differential mapper from canonical SE3Delta to SO-101."""
from __future__ import annotations

from pathlib import Path
import time
from typing import Mapping

import numpy as np
from scipy.optimize import lsq_linear
from scipy.spatial.transform import Rotation

from mimicrec.motion.se3 import SE3Frame
from mimicrec.motion.types import (
    JointPositionCommand,
    JointResourceState,
    MotionStep,
    ResourceCommand,
    ResourceState,
    ScalarPositionCommand,
)


class _SO101Kinematics:
    def __init__(self, urdf_path: str, target_frame: str, joint_names: list[str]):
        from lerobot.model.kinematics import RobotKinematics

        self._kinematics = RobotKinematics(
            urdf_path=str(Path(urdf_path).resolve()),
            target_frame_name=target_frame,
            joint_names=joint_names,
        )

    def forward(self, q_deg: np.ndarray) -> np.ndarray:
        return np.asarray(
            self._kinematics.forward_kinematics(
                np.asarray(q_deg, dtype=np.float64)
            ),
            dtype=np.float64,
        )


def _damped_pseudoinverse(matrix: np.ndarray, damping: float) -> np.ndarray:
    """Return a numerically stable Moore-Penrose inverse."""

    u, singular, vh = np.linalg.svd(matrix, full_matrices=False)
    gains = singular / (singular * singular + damping * damping)
    return (vh.T * gains) @ u.T


def _truncated_damped_pseudoinverse(
    matrix: np.ndarray, damping: float, minimum_singular_value: float
) -> tuple[np.ndarray, np.ndarray, int]:
    """Invert only physically meaningful task directions.

    Tiny secondary-task singular values are unreachable directions blurred by
    finite-difference/numerical error. Damped inversion alone can amplify one
    into a very large joint command, so discard it explicitly.
    """

    u, singular, vh = np.linalg.svd(matrix, full_matrices=False)
    keep = singular >= minimum_singular_value
    gains = np.zeros_like(singular)
    gains[keep] = singular[keep] / (
        singular[keep] * singular[keep] + damping * damping
    )
    return (vh.T * gains) @ u.T, singular, int(np.sum(keep))


class SE3DeltaToSO101Mapper:
    """Project a 6D step onto SO-101 without solving a global pose IK.

    Translation is the primary task. Orientation is solved only in the
    translation task's joint-space nullspace, so the arm cannot buy an
    impossible wrist rotation by moving the end effector. The unattainable
    rotational component is intentionally discarded on every step instead of
    being accumulated into a later jump.
    """

    def __init__(
        self,
        *,
        urdf_path: str,
        target_frame: str = "gripper_frame_link",
        joint_names: list[str] | None = None,
        arm_resource: str = "left_robot.arm",
        gripper_resource: str | None = "left_robot.gripper",
        world_to_base_rotation: list[float] | None = None,
        jacobian_epsilon_deg: float = 0.05,
        differential_damping: float = 0.002,
        rotation_singular_value_min: float = 0.05,
        rotation_projection_min_alignment: float = 0.0,
        max_backtracking_steps: int = 6,
        backtracking_refinement_steps: int = 6,
        pose_smoothing_time_constant_sec: float = 0.0,
        pose_smoothing_max_dt_sec: float = 0.05,
        max_position_error_m: float = 0.0005,
        max_uncommanded_position_error_m: float = 0.00015,
        max_joint_step_deg: float = 6.0,
        max_command_lead_deg: float | None = None,
        position_joint_weights: list[float] | None = None,
        joint_pos_min_deg: list[float] | None = None,
        joint_pos_max_deg: list[float] | None = None,
        gripper_open: float = 100.0,
        gripper_closed: float = 0.0,
        # Retained so older mapper YAML remains loadable. Global weighted IK
        # is deliberately no longer used.
        position_weight: float = 1.0,
        orientation_weight: float = 0.001,
        ik_iterations: int = 20,
        max_orientation_error_rad: float = 1.0,
        kinematics=None,
        monotonic=time.monotonic,
    ) -> None:
        del position_weight, orientation_weight, ik_iterations
        del max_orientation_error_rad
        self.joint_names = joint_names or [
            "shoulder_pan",
            "shoulder_lift",
            "elbow_flex",
            "wrist_flex",
            "wrist_roll",
        ]
        self.dof = len(self.joint_names)
        if self.dof != 5:
            raise ValueError("SO-101 Cartesian mapper requires five arm joints")
        self.arm_resource = arm_resource
        self.gripper_resource = gripper_resource
        self.jacobian_epsilon_deg = float(jacobian_epsilon_deg)
        self.differential_damping = float(differential_damping)
        self.rotation_singular_value_min = float(
            rotation_singular_value_min
        )
        self.rotation_projection_min_alignment = float(
            rotation_projection_min_alignment
        )
        self.max_backtracking_steps = int(max_backtracking_steps)
        self.backtracking_refinement_steps = int(
            backtracking_refinement_steps
        )
        self.pose_smoothing_time_constant_sec = float(
            pose_smoothing_time_constant_sec
        )
        self.pose_smoothing_max_dt_sec = float(pose_smoothing_max_dt_sec)
        self.max_position_error_m = float(max_position_error_m)
        self.max_uncommanded_position_error_m = float(
            max_uncommanded_position_error_m
        )
        self.max_joint_step_deg = float(max_joint_step_deg)
        self.max_command_lead_deg = float(
            max_joint_step_deg
            if max_command_lead_deg is None
            else max_command_lead_deg
        )
        # Translation has infinitely many joint-space solutions on a 5-DoF
        # arm. A plain minimum-norm solve spends wrist roll to gain a few
        # millimetres at the offset tool frame, which looks unrelated to the
        # controller gesture and leaves no wrist budget for actual rotation.
        # Prefer proximal joints for position and reserve the wrist joints for
        # orientation. These weights regularize only the redundant part; the
        # Cartesian position residual remains the primary objective.
        self.position_joint_weights = np.asarray(
            position_joint_weights or [1.0, 1.0, 1.0, 3.0, 30.0],
            dtype=np.float64,
        )
        self.joint_min = np.asarray(
            joint_pos_min_deg or [-110.0, -100.0, -96.83, -95.0, -157.21],
            dtype=np.float64,
        )
        self.joint_max = np.asarray(
            joint_pos_max_deg or [110.0, 100.0, 96.83, 95.0, 162.79],
            dtype=np.float64,
        )
        rotation = np.asarray(
            np.eye(3).reshape(-1)
            if world_to_base_rotation is None
            else world_to_base_rotation,
            dtype=np.float64,
        )
        if rotation.size != 9:
            raise ValueError("world_to_base_rotation must contain nine values")
        self.world_to_base_rotation = rotation.reshape(3, 3)
        if not np.allclose(
            self.world_to_base_rotation.T @ self.world_to_base_rotation,
            np.eye(3),
            atol=1e-6,
        ) or not np.isclose(
            np.linalg.det(self.world_to_base_rotation), 1.0, atol=1e-6
        ):
            raise ValueError("world_to_base_rotation must be a proper rotation")
        if self.joint_min.shape != (5,) or self.joint_max.shape != (5,):
            raise ValueError("SO-101 joint limits must each have five values")
        if (
            self.position_joint_weights.shape != (5,)
            or not np.isfinite(self.position_joint_weights).all()
            or np.any(self.position_joint_weights <= 0.0)
        ):
            raise ValueError(
                "position_joint_weights must contain five positive values"
            )
        if np.any(self.joint_min >= self.joint_max):
            raise ValueError("SO-101 joint minima must be below maxima")
        if self.jacobian_epsilon_deg <= 0.0:
            raise ValueError("jacobian_epsilon_deg must be > 0")
        if self.differential_damping <= 0.0:
            raise ValueError("differential_damping must be > 0")
        if self.rotation_singular_value_min <= 0.0:
            raise ValueError("rotation_singular_value_min must be > 0")
        if not 0.0 <= self.rotation_projection_min_alignment <= 1.0:
            raise ValueError(
                "rotation_projection_min_alignment must be in [0, 1]"
            )
        if self.max_backtracking_steps < 0:
            raise ValueError("max_backtracking_steps must be >= 0")
        if self.backtracking_refinement_steps < 0:
            raise ValueError("backtracking_refinement_steps must be >= 0")
        if self.pose_smoothing_time_constant_sec < 0.0:
            raise ValueError("pose_smoothing_time_constant_sec must be >= 0")
        if self.pose_smoothing_max_dt_sec < 0.0:
            raise ValueError("pose_smoothing_max_dt_sec must be >= 0")
        if self.max_joint_step_deg <= 0.0:
            raise ValueError("max_joint_step_deg must be > 0")
        if self.max_command_lead_deg <= 0.0:
            raise ValueError("max_command_lead_deg must be > 0")
        if self.max_position_error_m <= 0.0:
            raise ValueError("max_position_error_m must be > 0")
        if self.max_uncommanded_position_error_m <= 0.0:
            raise ValueError(
                "max_uncommanded_position_error_m must be > 0"
            )
        self.gripper_open = float(gripper_open)
        self.gripper_closed = float(gripper_closed)
        self._kinematics = kinematics or _SO101Kinematics(
            urdf_path, target_frame, self.joint_names
        )
        self._monotonic = monotonic
        self._last_command_deg: np.ndarray | None = None
        self._anchor_transform_base: np.ndarray | None = None
        self._filtered_pose_translation: np.ndarray | None = None
        self._filtered_pose_rotation: np.ndarray | None = None
        self._filtered_control_rotation: np.ndarray | None = None
        self._pose_filter_last_at: float | None = None
        self._last_position_error_m = 0.0
        self._last_orientation_error_rad = 0.0
        self._last_rotation_projection_residual_rad = 0.0
        self._last_backtracking_count = 0
        self._last_projection_scale = 1.0
        self._last_rejection_reason = ""
        self._last_position_error_limit_m = self.max_position_error_m
        self._last_uncommanded_position_error_m = 0.0
        self._last_position_jacobian_min_singular = 0.0
        self._last_reachable_rotation_rank = 0
        self._last_reachable_rotation_min_singular = 0.0
        self._last_orientation_joint_scale = 1.0
        self._last_rotation_projection_alignment = 1.0
        self._last_position_target_error_m = 0.0
        self._last_joint_step_deg = 0.0
        self._last_solve_time_ms = 0.0

    def reset(self) -> None:
        self._last_command_deg = None
        self._anchor_transform_base = None
        self._filtered_pose_translation = None
        self._filtered_pose_rotation = None
        self._filtered_control_rotation = None
        self._pose_filter_last_at = None
        self._last_rejection_reason = ""

    def map(
        self,
        step: MotionStep,
        resource_states: Mapping[str, ResourceState],
    ) -> Mapping[str, ResourceCommand]:
        state = resource_states.get(self.arm_resource)
        if not isinstance(state, JointResourceState):
            raise ValueError(f"missing SO-101 arm state {self.arm_resource!r}")
        measured = np.rad2deg(
            np.asarray(state.position[: self.dof], dtype=np.float64)
        )
        if measured.shape != (self.dof,) or not np.isfinite(measured).all():
            raise ValueError("invalid SO-101 measured joint state")
        if step.reset_reference:
            self.reset()
        # Keep absolute IK continuous in command space.  Seeding every solve
        # from the encoder feeds the STS3215's position quantization and small
        # servo errors back into the next command, making an otherwise smooth
        # controller trajectory visibly chatter.  A measured-state lead
        # envelope still prevents the command from running away from a stalled
        # physical arm.
        seed = measured.copy()
        if self._last_command_deg is not None:
            seed = self._last_command_deg.copy()
            if step.absolute_offset is not None:
                seed = np.clip(
                    seed,
                    measured - self.max_command_lead_deg,
                    measured + self.max_command_lead_deg,
                )
        solve_started = time.perf_counter()
        self._last_rejection_reason = ""
        try:
            current = self._kinematics.forward(seed)
            if current.shape != (4, 4) or not np.isfinite(current).all():
                raise ValueError("invalid SO-101 forward kinematics result")
            if step.absolute_offset is not None:
                if self._anchor_transform_base is None:
                    self._anchor_transform_base = current.copy()
                step = self._smooth_absolute_offset(step)
                requested_position, requested_rotation = (
                    self._absolute_error_in_base(step, current)
                )
            else:
                requested_position, requested_rotation = self._step_in_base(
                    step, current
                )
            self._last_position_target_error_m = float(
                np.linalg.norm(requested_position)
            )
            position_jacobian, rotation_jacobian = self._geometric_jacobian(
                seed, current
            )
            (
                position_step,
                position_step_target,
                position_scale,
            ) = self._bounded_position_step(
                position_jacobian, requested_position, seed
            )
            # Use the exact SVD nullspace, not I - J^+J from the damped
            # inverse. The latter leaks a small amount back into translation
            # and can make a five-DoF arm appear to have three secondary
            # rotational dimensions.
            _, singular, position_vh = np.linalg.svd(
                position_jacobian, full_matrices=True
            )
            position_rank = int(
                np.sum(singular > max(1e-8, singular[0] * 1e-6))
            )
            nullspace_basis = position_vh[position_rank:].T
            reachable_rotation = rotation_jacobian @ nullspace_basis
            remaining_rotation = (
                requested_rotation - rotation_jacobian @ position_step
            )
            if nullspace_basis.shape[1]:
                (
                    rotation_inverse,
                    rotation_singular,
                    rotation_rank,
                ) = _truncated_damped_pseudoinverse(
                    reachable_rotation,
                    self.differential_damping,
                    self.rotation_singular_value_min,
                )
                rotation_step = (
                    nullspace_basis @ rotation_inverse @ remaining_rotation
                )
                projected_rotation = rotation_jacobian @ rotation_step
                projected_norm = float(np.linalg.norm(projected_rotation))
                requested_norm = float(np.linalg.norm(remaining_rotation))
                if requested_norm < 1e-9:
                    alignment = 1.0
                elif projected_norm < 1e-9:
                    alignment = 0.0
                else:
                    alignment = float(
                        np.clip(
                            np.dot(projected_rotation, remaining_rotation)
                            / (projected_norm * requested_norm),
                            -1.0,
                            1.0,
                        )
                    )
                self._last_rotation_projection_alignment = alignment
                if alignment < self.rotation_projection_min_alignment:
                    rotation_step = np.zeros(self.dof)
            else:
                rotation_singular = np.zeros(0)
                rotation_rank = 0
                rotation_step = np.zeros(self.dof)
                self._last_rotation_projection_alignment = 0.0
            if not (
                np.isfinite(position_step).all()
                and np.isfinite(rotation_step).all()
            ):
                raise ValueError("non-finite differential IK result")

            self._last_position_jacobian_min_singular = float(singular[-1])
            self._last_reachable_rotation_rank = rotation_rank
            kept_rotation_singular = rotation_singular[
                rotation_singular >= self.rotation_singular_value_min
            ]
            self._last_reachable_rotation_min_singular = (
                float(kept_rotation_singular[-1])
                if kept_rotation_singular.size
                else 0.0
            )
            orientation_scale = self._orientation_joint_budget_scale(
                position_step, rotation_step, seed
            )
            self._last_orientation_joint_scale = orientation_scale
            joint_step = position_step + orientation_scale * rotation_step
            solved, accepted_scale = self._backtrack(
                seed,
                current,
                joint_step,
                position_step_target,
                requested_rotation,
            )
            self._last_projection_scale = position_scale * accepted_scale
        except Exception as exc:
            solved = seed
            requested_position = np.zeros(3)
            requested_rotation = np.zeros(3)
            self._last_rejection_reason = str(exc) or type(exc).__name__
            self._last_backtracking_count = self.max_backtracking_steps + 1
            self._last_projection_scale = 0.0
            self._last_position_error_m = float("inf")
            self._last_orientation_error_rad = float("inf")
            self._last_rotation_projection_residual_rad = float("inf")

        self._last_solve_time_ms = (time.perf_counter() - solve_started) * 1000.0
        solved = np.clip(solved, self.joint_min, self.joint_max)
        if step.absolute_offset is not None:
            solved = np.clip(
                solved,
                measured - self.max_command_lead_deg,
                measured + self.max_command_lead_deg,
            )
        self._last_joint_step_deg = float(np.max(np.abs(solved - seed)))
        self._last_command_deg = solved.copy()

        commands: dict[str, ResourceCommand] = {
            self.arm_resource: JointPositionCommand(
                np.deg2rad(solved).astype(np.float32),
                t_mono_ns=step.t_mono_ns,
            )
        }
        if self.gripper_resource is not None and "gripper" in step.auxiliary:
            fraction = float(np.clip(step.auxiliary["gripper"], 0.0, 1.0))
            gripper = self.gripper_open + fraction * (
                self.gripper_closed - self.gripper_open
            )
            commands[self.gripper_resource] = ScalarPositionCommand(
                gripper, t_mono_ns=step.t_mono_ns
            )
        return commands

    def _smooth_absolute_offset(self, step: MotionStep) -> MotionStep:
        """Low-pass a clutch-absolute SE(3) target before differential IK.

        The filter runs on the mapper's fixed-rate clock rather than packet
        timestamps. This absorbs producer/consumer phase jitter while still
        converging exactly to a held controller pose. Filtering in task space
        also avoids inventing a joint-space path between IK solutions.
        """

        assert step.absolute_offset is not None
        desired = step.absolute_offset
        desired_translation = desired[:3, 3]
        desired_rotation = desired[:3, :3]
        desired_control = (
            step.control_rotation_offset
            if step.control_rotation_offset is not None
            else desired_rotation
        )
        if self._filtered_pose_translation is None:
            self._filtered_pose_translation = np.zeros(3, dtype=np.float64)
            self._filtered_pose_rotation = np.eye(3, dtype=np.float64)
            self._filtered_control_rotation = np.eye(3, dtype=np.float64)
            self._pose_filter_last_at = self._monotonic()

        assert self._filtered_pose_rotation is not None
        assert self._filtered_control_rotation is not None
        now = self._monotonic()
        previous_at = self._pose_filter_last_at
        self._pose_filter_last_at = now
        if self.pose_smoothing_time_constant_sec <= 0.0:
            alpha = 1.0
        else:
            dt = 0.0 if previous_at is None else max(0.0, now - previous_at)
            if self.pose_smoothing_max_dt_sec > 0.0:
                dt = min(dt, self.pose_smoothing_max_dt_sec)
            alpha = 1.0 - np.exp(-dt / self.pose_smoothing_time_constant_sec)

        self._filtered_pose_translation += alpha * (
            desired_translation - self._filtered_pose_translation
        )
        pose_error = Rotation.from_matrix(
            desired_rotation @ self._filtered_pose_rotation.T
        ).as_rotvec()
        self._filtered_pose_rotation = (
            Rotation.from_rotvec(alpha * pose_error).as_matrix()
            @ self._filtered_pose_rotation
        )
        control_error = Rotation.from_matrix(
            desired_control @ self._filtered_control_rotation.T
        ).as_rotvec()
        self._filtered_control_rotation = (
            Rotation.from_rotvec(alpha * control_error).as_matrix()
            @ self._filtered_control_rotation
        )
        filtered = np.eye(4, dtype=np.float64)
        filtered[:3, :3] = self._filtered_pose_rotation
        filtered[:3, 3] = self._filtered_pose_translation
        return MotionStep(
            delta=step.delta,
            auxiliary=step.auxiliary,
            t_mono_ns=step.t_mono_ns,
            absolute_offset=filtered,
            control_rotation_offset=(
                self._filtered_control_rotation
                if step.control_rotation_offset is not None
                else None
            ),
            reset_reference=step.reset_reference,
        )

    def _step_in_base(
        self, step: MotionStep, current: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return literal EEF displacement and spatial rotation in base."""

        delta = step.delta.as_transform()
        position = delta[:3, 3]
        rotation = delta[:3, :3]
        if step.delta.frame == SE3Frame.EE_LOCAL:
            basis = current[:3, :3]
        elif step.delta.frame == SE3Frame.BASE:
            basis = np.eye(3)
        elif step.delta.frame == SE3Frame.WORLD:
            basis = self.world_to_base_rotation
        else:
            raise ValueError(f"unsupported SE3Delta frame {step.delta.frame}")
        position_base = basis @ position
        rotation_base = basis @ rotation @ basis.T
        return position_base, Rotation.from_matrix(rotation_base).as_rotvec()

    def _absolute_error_in_base(
        self, step: MotionStep, current: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return error to a clutch-absolute target without origin orbit."""

        assert step.absolute_offset is not None
        assert self._anchor_transform_base is not None
        offset = step.absolute_offset
        anchor = self._anchor_transform_base
        if step.delta.frame == SE3Frame.EE_LOCAL:
            desired_position = (
                anchor[:3, 3] + anchor[:3, :3] @ offset[:3, 3]
            )
        elif step.delta.frame == SE3Frame.BASE:
            desired_position = anchor[:3, 3] + offset[:3, 3]
        elif step.delta.frame == SE3Frame.WORLD:
            basis = self.world_to_base_rotation
            desired_position = anchor[:3, 3] + basis @ offset[:3, 3]
        else:
            raise ValueError(f"unsupported SE3Delta frame {step.delta.frame}")
        if step.control_rotation_offset is not None:
            # Rotation control is deliberately clutch-local: the controller
            # pose at grip engagement is the EEF orientation reference. This
            # makes a controller twist address SO-101 wrist roll even though
            # the controller and robot started with different WORLD poses.
            desired_rotation = (
                anchor[:3, :3] @ step.control_rotation_offset
            )
        elif step.delta.frame == SE3Frame.EE_LOCAL:
            desired_rotation = anchor[:3, :3] @ offset[:3, :3]
        elif step.delta.frame == SE3Frame.BASE:
            desired_rotation = offset[:3, :3] @ anchor[:3, :3]
        else:
            desired_rotation = (
                basis @ offset[:3, :3] @ basis.T @ anchor[:3, :3]
            )
        return (
            desired_position - current[:3, 3],
            Rotation.from_matrix(
                desired_rotation @ current[:3, :3].T
            ).as_rotvec(),
        )

    def _orientation_joint_budget_scale(
        self,
        position_step: np.ndarray,
        rotation_step: np.ndarray,
        seed_deg: np.ndarray,
    ) -> float:
        """Use only rate and absolute-limit budget left after position."""

        limit = np.deg2rad(self.max_joint_step_deg)
        lower = np.maximum(-limit, np.deg2rad(self.joint_min - seed_deg))
        upper = np.minimum(limit, np.deg2rad(self.joint_max - seed_deg))
        scale = 1.0
        for primary, secondary, minimum, maximum in zip(
            position_step, rotation_step, lower, upper
        ):
            if secondary > 0.0:
                scale = min(scale, (maximum - primary) / secondary)
            elif secondary < 0.0:
                scale = min(scale, (minimum - primary) / secondary)
        return float(np.clip(scale, 0.0, 1.0))

    def _geometric_jacobian(
        self, seed_deg: np.ndarray, current: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        position = np.empty((3, self.dof), dtype=np.float64)
        rotation = np.empty((3, self.dof), dtype=np.float64)
        epsilon_rad = np.deg2rad(self.jacobian_epsilon_deg)
        for index in range(self.dof):
            perturbed = seed_deg.copy()
            perturbed[index] += self.jacobian_epsilon_deg
            next_transform = self._kinematics.forward(perturbed)
            position[:, index] = (
                next_transform[:3, 3] - current[:3, 3]
            ) / epsilon_rad
            # Spatial angular velocity is expressed in the robot base frame.
            rotation[:, index] = Rotation.from_matrix(
                next_transform[:3, :3] @ current[:3, :3].T
            ).as_rotvec() / epsilon_rad
        return position, rotation

    def _bounded_position_step(
        self,
        jacobian: np.ndarray,
        requested_position: np.ndarray,
        seed_deg: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, float]:
        """Find the largest direction-preserving position step in bounds."""

        if float(np.linalg.norm(requested_position)) < 1e-12:
            return np.zeros(self.dof), np.zeros(3), 1.0
        step_limit = np.deg2rad(self.max_joint_step_deg)
        lower = np.maximum(
            -step_limit, np.deg2rad(self.joint_min - seed_deg)
        )
        upper = np.minimum(
            step_limit, np.deg2rad(self.joint_max - seed_deg)
        )
        if np.any(lower >= upper):
            return np.zeros(self.dof), np.zeros(3), 0.0
        augmented = np.vstack(
            (
                jacobian,
                self.differential_damping
                * np.diag(self.position_joint_weights),
            )
        )

        def solve(scale: float) -> tuple[np.ndarray, np.ndarray, bool]:
            target = requested_position * scale
            rhs = np.concatenate((target, np.zeros(self.dof)))
            result = lsq_linear(
                augmented,
                rhs,
                bounds=(lower, upper),
                tol=1e-8,
                lsmr_tol="auto",
                max_iter=50,
            )
            joint_step = np.asarray(result.x, dtype=np.float64)
            predicted = jacobian @ joint_step
            accepted, _, _ = self._position_error_acceptable(
                target, predicted
            )
            return joint_step, target, bool(result.success and accepted)

        infeasible = 1.0
        feasible = None
        scale = 1.0
        for _ in range(self.max_backtracking_steps + 1):
            joint_step, target, accepted = solve(scale)
            if accepted:
                feasible = (joint_step, target, scale)
                break
            infeasible = scale
            scale *= 0.5
        if feasible is None:
            return np.zeros(self.dof), np.zeros(3), 0.0

        # Recover most of the interval lost by power-of-two backtracking.
        low = feasible[2]
        high = infeasible if infeasible > low else low
        best = feasible
        for _ in range(5):
            if high - low < 1e-3:
                break
            middle = 0.5 * (low + high)
            joint_step, target, accepted = solve(middle)
            if accepted:
                low = middle
                best = (joint_step, target, middle)
            else:
                high = middle
        return best

    def _backtrack(
        self,
        seed: np.ndarray,
        current: np.ndarray,
        joint_step_rad: np.ndarray,
        requested_position: np.ndarray,
        requested_rotation: np.ndarray,
    ) -> tuple[np.ndarray, float]:
        def evaluate(scale: float):
            candidate = seed + np.rad2deg(joint_step_rad) * scale
            if np.any(candidate < self.joint_min) or np.any(
                candidate > self.joint_max
            ):
                return None
            actual = self._kinematics.forward(candidate)
            actual_position = actual[:3, 3] - current[:3, 3]
            actual_rotation = Rotation.from_matrix(
                actual[:3, :3] @ current[:3, :3].T
            ).as_rotvec()
            target_position = requested_position * scale
            accepted, position_error, uncommanded_error = (
                self._position_error_acceptable(
                    target_position, actual_position
                )
            )
            return (
                accepted,
                candidate,
                actual_rotation,
                position_error,
                uncommanded_error,
            )

        rejected_scale: float | None = None
        best = None
        for backtrack in range(self.max_backtracking_steps + 1):
            scale = 0.5**backtrack
            result = evaluate(scale)
            if result is not None and result[0]:
                best = (scale, result, backtrack)
                break
            rejected_scale = scale
        if best is not None:
            low = best[0]
            high = rejected_scale if rejected_scale is not None else low
            # Power-of-two probing finds a safe bracket quickly. Refine the
            # accepted edge so the command scale changes continuously instead
            # of snapping among 1, 1/2, 1/4, ... as FK error crosses a limit.
            for _ in range(self.backtracking_refinement_steps):
                if high - low < 1e-4:
                    break
                middle = 0.5 * (low + high)
                result = evaluate(middle)
                if result is not None and result[0]:
                    low = middle
                    best = (middle, result, best[2])
                else:
                    high = middle

            scale, result, backtrack = best
            _, candidate, actual_rotation, position_error, uncommanded_error = (
                result
            )
            # The absolute orientation target remains unchanged when a joint
            # or nonlinear backtrack slows this tick; it will be retried on
            # the next absolute controller sample. Unreachable components are
            # visible as projection residual but are never accumulated.
            self._last_position_error_m = position_error
            self._last_uncommanded_position_error_m = uncommanded_error
            orientation_error = float(
                np.linalg.norm(requested_rotation - actual_rotation)
            )
            self._last_orientation_error_rad = orientation_error
            self._last_rotation_projection_residual_rad = orientation_error
            self._last_position_error_limit_m = self.max_position_error_m
            self._last_backtracking_count = backtrack
            return candidate, scale
        self._last_rejection_reason = "no continuous differential-IK solution"
        self._last_backtracking_count = self.max_backtracking_steps + 1
        self._last_position_error_m = float(np.linalg.norm(requested_position))
        self._last_orientation_error_rad = float(np.linalg.norm(requested_rotation))
        self._last_rotation_projection_residual_rad = self._last_orientation_error_rad
        return seed.copy(), 0.0

    def _position_error_acceptable(
        self, target: np.ndarray, actual: np.ndarray
    ) -> tuple[bool, float, float]:
        """Check both total error and motion not requested by the operator."""

        error = float(np.linalg.norm(target - actual))
        target_norm = float(np.linalg.norm(target))
        if target_norm < 1e-12:
            uncommanded = float(np.linalg.norm(actual))
        else:
            direction = target / target_norm
            parallel = float(np.dot(actual, direction))
            uncommanded = float(
                np.linalg.norm(actual - parallel * direction)
            )
        return (
            error <= self.max_position_error_m
            and uncommanded <= self.max_uncommanded_position_error_m,
            error,
            uncommanded,
        )

    def forward_kinematics(self, position_rad: np.ndarray) -> np.ndarray:
        """Return the EEF transform for a canonical radian joint state."""

        return self._kinematics.forward(
            np.rad2deg(np.asarray(position_rad, dtype=np.float64))
        )

    def telemetry(self) -> dict[str, float]:
        return {
            "ik_position_error_m": self._last_position_error_m,
            "ik_orientation_error_rad": self._last_orientation_error_rad,
            "ik_rotation_projection_residual_rad": (
                self._last_rotation_projection_residual_rad
            ),
            "ik_backtracking_count": float(self._last_backtracking_count),
            "ik_projection_scale": self._last_projection_scale,
            "ik_rejected": float(bool(self._last_rejection_reason)),
            "ik_position_error_limit_m": self._last_position_error_limit_m,
            "ik_uncommanded_position_error_m": (
                self._last_uncommanded_position_error_m
            ),
            "ik_position_jacobian_min_singular": (
                self._last_position_jacobian_min_singular
            ),
            "ik_reachable_rotation_rank": float(
                self._last_reachable_rotation_rank
            ),
            "ik_reachable_rotation_min_singular": (
                self._last_reachable_rotation_min_singular
            ),
            "ik_orientation_joint_scale": self._last_orientation_joint_scale,
            "ik_rotation_projection_alignment": (
                self._last_rotation_projection_alignment
            ),
            "ik_position_target_error_m": self._last_position_target_error_m,
            "ik_joint_step_deg": self._last_joint_step_deg,
            "ik_solve_time_ms": self._last_solve_time_ms,
        }
