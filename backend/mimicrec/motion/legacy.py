"""Compatibility bridges between the resource graph and legacy robot APIs."""
from __future__ import annotations

from typing import Mapping

import numpy as np
from scipy.spatial.transform import Rotation

from mimicrec.adapters.robot import RobotMode
from mimicrec.motion.se3 import SE3Frame
from mimicrec.motion.types import (
    JointPositionCommand,
    JointResourceState,
    MotionStep,
    ResourceCommand,
    ResourceState,
    ScalarResourceState,
    ScalarPositionCommand,
)
from mimicrec.types import RobotState, TeleopAction


class LegacyRobotResourceAdapter:
    """Expose a traditional RobotAdapter as named ``arm``/``gripper`` resources."""

    def __init__(
        self,
        robot,
        *,
        include_gripper: bool = True,
        safe_mode: RobotMode = RobotMode.GRAVITY_COMP,
    ) -> None:
        self.robot = robot
        self.name = str(robot.name)
        self._include_gripper = bool(include_gripper)
        self._safe_mode = safe_mode
        self.resource_names = (
            ("arm", "gripper") if self._include_gripper else ("arm",)
        )

    async def connect(self) -> None:
        await self.robot.connect()
        await self.robot.set_mode(RobotMode.POSITION)

    async def activate(self) -> None:
        # Legacy adapters already enter POSITION in connect() for backwards
        # compatibility with direct users of this wrapper.
        return None

    async def disconnect(self) -> None:
        await self.robot.disconnect()

    async def safe_stop(self) -> None:
        if self.robot.supports_mode(self._safe_mode):
            await self.robot.set_mode(self._safe_mode)

    async def estop(self) -> dict:
        estop = getattr(self.robot, "estop", None)
        if estop is None:
            await self.safe_stop()
            return {"ok": True, "fallback": self._safe_mode.value}
        return await estop()

    async def clear_estop(self) -> dict:
        clear = getattr(self.robot, "clear_estop", None)
        if clear is None:
            raise RuntimeError(f"{self.name} does not support clear_estop")
        return await clear()

    async def read_resources(self) -> Mapping[str, ResourceState]:
        state = await self.robot.read_state()
        transform = None
        if state.ee_pos is not None and state.ee_rotvec is not None:
            transform = np.eye(4, dtype=np.float64)
            transform[:3, :3] = Rotation.from_rotvec(
                np.asarray(state.ee_rotvec, dtype=np.float64)
            ).as_matrix()
            transform[:3, 3] = state.ee_pos
        result: dict[str, ResourceState] = {
            "arm": JointResourceState(
                position=state.joint_pos,
                velocity=state.joint_vel,
                effort=state.joint_effort,
                joint_names=tuple(self.robot.joint_names[: state.joint_pos.size]),
                t_mono_ns=state.t_mono_ns,
                ee_transform=transform,
            )
        }
        if self._include_gripper:
            gripper = 0.0 if state.gripper_pos is None else state.gripper_pos
            result["gripper"] = ScalarResourceState(
                position=gripper,
                t_mono_ns=state.t_mono_ns,
            )
        return result

    async def send_commands(
        self, commands: Mapping[str, ResourceCommand]
    ) -> None:
        unknown = set(commands) - set(self.resource_names)
        if unknown:
            raise ValueError(f"unknown legacy robot resources: {sorted(unknown)}")
        arm = commands.get("arm")
        if arm is not None:
            if not isinstance(arm, JointPositionCommand):
                raise TypeError("legacy arm requires JointPositionCommand")
            await self.robot.send_joint_command(arm.position)
        gripper = commands.get("gripper")
        if gripper is not None:
            if not isinstance(gripper, ScalarPositionCommand):
                raise TypeError("legacy gripper requires ScalarPositionCommand")
            send_gripper = getattr(self.robot, "send_gripper_command", None)
            if send_gripper is None:
                raise TypeError("legacy robot does not support gripper commands")
            await send_gripper(gripper.position)


class SE3DeltaToLegacyMapper:
    """Drive an existing Cartesian mapper from the new SE3Delta contract."""

    def __init__(
        self,
        mapper,
        *,
        arm_resource: str,
        gripper_resource: str | None = None,
        gripper_auxiliary_key: str = "gripper",
        target_frame: str = "base",
        world_to_base_rotation: list[float] | None = None,
    ) -> None:
        self.mapper = mapper
        self.arm_resource = arm_resource
        self.gripper_resource = gripper_resource
        self.gripper_auxiliary_key = gripper_auxiliary_key
        if target_frame not in {"base", "ee_local"}:
            raise ValueError("legacy mapper target_frame must be base or ee_local")
        self.target_frame = target_frame
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
        self._absolute_anchor_rotation: np.ndarray | None = None

    def map(
        self,
        step: MotionStep,
        resource_states: Mapping[str, ResourceState],
    ) -> Mapping[str, ResourceCommand]:
        arm_state = resource_states.get(self.arm_resource)
        if not isinstance(arm_state, JointResourceState):
            raise ValueError(f"missing joint state for {self.arm_resource!r}")
        gripper_pos = None
        if self.gripper_resource is not None:
            gripper_state = resource_states.get(self.gripper_resource)
            if isinstance(gripper_state, ScalarResourceState):
                gripper_pos = gripper_state.position
        legacy_state = RobotState(
            joint_pos=arm_state.position.copy(),
            joint_vel=arm_state.velocity.copy(),
            joint_effort=arm_state.effort.copy(),
            t_mono_ns=arm_state.t_mono_ns,
            ee_pos=(
                arm_state.ee_transform[:3, 3].astype(np.float32)
                if arm_state.ee_transform is not None
                else None
            ),
            ee_rotvec=(
                Rotation.from_matrix(arm_state.ee_transform[:3, :3])
                .as_rotvec()
                .astype(np.float32)
                if arm_state.ee_transform is not None
                else None
            ),
            gripper_pos=gripper_pos,
        )
        if step.reset_reference:
            self.reset()
        if (
            step.absolute_offset is not None
            and self._absolute_anchor_rotation is None
        ):
            if arm_state.ee_transform is None:
                raise ValueError(
                    "absolute legacy control requires current EEF transform"
                )
            self._absolute_anchor_rotation = arm_state.ee_transform[:3, :3].copy()

        # SE3Delta stores a strict Lie logarithm, while the legacy mapper API
        # expects a transform's literal translation column and rotvec. Quest
        # additionally carries its absolute clutch target: use that for
        # lossless rate-limited control while the per-step delta remains the
        # authoritative recorded action.
        transform = (
            step.absolute_offset
            if step.absolute_offset is not None
            else step.delta.as_transform()
        )
        ee_rotation = (
            arm_state.ee_transform[:3, :3]
            if arm_state.ee_transform is not None
            else np.eye(3)
        )
        if self.target_frame == "base":
            if step.delta.frame == SE3Frame.EE_LOCAL:
                basis = ee_rotation
            elif step.delta.frame == SE3Frame.BASE:
                basis = np.eye(3)
            else:
                basis = self.world_to_base_rotation
        else:
            if step.delta.frame == SE3Frame.EE_LOCAL:
                basis = np.eye(3)
            elif step.delta.frame == SE3Frame.BASE:
                basis = ee_rotation.T
            else:
                basis = ee_rotation.T @ self.world_to_base_rotation
        if (
            step.absolute_offset is not None
            and step.control_rotation_offset is not None
        ):
            if self.target_frame == "base":
                assert self._absolute_anchor_rotation is not None
                rotation = (
                    self._absolute_anchor_rotation
                    @ step.control_rotation_offset
                    @ self._absolute_anchor_rotation.T
                )
            else:
                rotation = step.control_rotation_offset
        else:
            rotation = basis @ transform[:3, :3] @ basis.T
        components = np.concatenate(
            (
                basis @ transform[:3, 3],
                Rotation.from_matrix(rotation).as_rotvec(),
            )
        )
        if step.absolute_offset is not None:
            action = TeleopAction(
                ee_pose_offset=components,
                ee_pose_active=True,
                gripper_fraction=step.auxiliary.get(self.gripper_auxiliary_key),
                t_mono_ns=step.t_mono_ns,
            )
        else:
            action = TeleopAction(
                ee_delta=components,
                gripper_fraction=step.auxiliary.get(self.gripper_auxiliary_key),
                t_mono_ns=step.t_mono_ns,
            )
        command = self.mapper.map(action, legacy_state)
        result: dict[str, ResourceCommand] = {
            self.arm_resource: JointPositionCommand(
                command.q, t_mono_ns=command.t_mono_ns
            )
        }
        if self.gripper_resource is not None and command.gripper is not None:
            result[self.gripper_resource] = ScalarPositionCommand(
                command.gripper, t_mono_ns=command.t_mono_ns
            )
        return result

    def reset(self) -> None:
        self._absolute_anchor_rotation = None
        reset = getattr(self.mapper, "reset", None)
        if reset is not None:
            reset()
