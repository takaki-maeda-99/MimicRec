"""Namespaced parquet rows for multi-resource MotionRuntime recordings."""
from __future__ import annotations

from mimicrec.motion.types import (
    JointPositionCommand,
    JointResourceState,
    MotionSampleBundle,
    PlanarResourceState,
    PlanarVelocityCommand,
    ScalarPositionCommand,
    ScalarResourceState,
)


def motion_bundle_to_row(
    bundle: MotionSampleBundle,
    episode_start_t_mono_ns: int,
    *,
    frame_index: int = 0,
    episode_index: int = 0,
    global_index: int = 0,
    task_index: int = 0,
) -> dict:
    row: dict = {
        "timestamp": (
            bundle.tick_t_mono_ns - episode_start_t_mono_ns
        ) / 1e9,
        "tick_t_mono_ns": bundle.tick_t_mono_ns,
        "frame_index": frame_index,
        "episode_index": episode_index,
        "index": global_index,
        "task_index": task_index,
    }
    for resource, state in bundle.states.items():
        prefix = f"observation.state.{resource}"
        if isinstance(state, JointResourceState):
            row[f"{prefix}.joint_pos"] = state.position
            row[f"{prefix}.joint_vel"] = state.velocity
            row[f"{prefix}.joint_effort"] = state.effort
            row[f"{prefix}.t_mono_ns"] = state.t_mono_ns
            if state.ee_transform is not None:
                row[f"{prefix}.ee_transform"] = state.ee_transform.reshape(-1)
        elif isinstance(state, PlanarResourceState):
            row[f"{prefix}.pose_xy_yaw"] = state.pose_xy_yaw
            row[f"{prefix}.velocity_xy_yaw"] = state.velocity_xy_yaw
            row[f"{prefix}.t_mono_ns"] = state.t_mono_ns
        elif isinstance(state, ScalarResourceState):
            row[f"{prefix}.position"] = state.position
            row[f"{prefix}.velocity"] = state.velocity
            row[f"{prefix}.effort"] = state.effort
            row[f"{prefix}.t_mono_ns"] = state.t_mono_ns

    for resource, command in bundle.commands.items():
        prefix = f"action.resource.{resource}"
        if isinstance(command, JointPositionCommand):
            row[f"{prefix}.joint_pos"] = command.position
            row[f"{prefix}.t_mono_ns"] = command.t_mono_ns
        elif isinstance(command, ScalarPositionCommand):
            row[f"{prefix}.position"] = command.position
            row[f"{prefix}.t_mono_ns"] = command.t_mono_ns
        elif isinstance(command, PlanarVelocityCommand):
            row[f"{prefix}.velocity_xy_yaw"] = command.velocity_xy_yaw
            row[f"{prefix}.t_mono_ns"] = command.t_mono_ns

    for group, step in bundle.motion_steps.items():
        prefix = f"action.motion.{group}"
        row[f"{prefix}.se3_delta"] = step.delta.tangent
        row[f"{prefix}.duration_sec"] = step.delta.duration_sec
        row[f"{prefix}.active_mask"] = step.delta.active_mask
        row[f"{prefix}.frame"] = step.delta.frame.value
        row[f"{prefix}.t_mono_ns"] = step.t_mono_ns
        for key, value in step.auxiliary.items():
            row[f"{prefix}.aux.{key}"] = value

    for group, values in bundle.mapper_telemetry.items():
        for key, value in values.items():
            row[f"diagnostic.motion.{group}.{key}"] = float(value)

    for camera_name, stamped in bundle.frames.items():
        row[f"observation.images.{camera_name}.t_mono_ns"] = (
            stamped.t_mono_ns if stamped is not None else 0
        )
    return row
