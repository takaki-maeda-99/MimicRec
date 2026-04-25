from __future__ import annotations
from typing import TYPE_CHECKING

from mimicrec.types import SampleBundle

if TYPE_CHECKING:
    from mimicrec.kinematics import FKService


def sample_bundle_to_row(
    bundle: SampleBundle,
    episode_start_t_mono_ns: int,
    video_frame_index: dict[str, int],
    frame_index: int = 0,
    episode_index: int = 0,
    global_index: int = 0,
    task_index: int = 0,
    fk: "FKService | None" = None,
) -> dict:
    state = bundle.state.value
    row = {
        "timestamp": (bundle.tick_t_mono_ns - episode_start_t_mono_ns) / 1e9,
        "tick_t_mono_ns": bundle.tick_t_mono_ns,
        "observation.state.joint_pos": state.joint_pos,
        "observation.state.joint_vel": state.joint_vel,
        "observation.state.joint_effort": state.joint_effort,
        "observation.state.t_mono_ns": state.t_mono_ns,
        "action.joint_pos": bundle.action.q,
        "action.t_mono_ns": bundle.action.t_mono_ns,
        "frame_index": frame_index,
        "episode_index": episode_index,
        "index": global_index,
        "task_index": task_index,
    }
    if fk is not None:
        n = fk.n_kin_joints
        # Observation = current follower pose; Action = commanded follower pose.
        obs_pos, obs_rotvec = fk.pose(state.joint_pos[:n])
        act_pos, act_rotvec = fk.pose(bundle.action.q[:n])
        row["observation.state.ee_pos"] = obs_pos
        row["observation.state.ee_rotvec"] = obs_rotvec
        row["action.ee_pos"] = act_pos
        row["action.ee_rotvec"] = act_rotvec
        # Gripper is the joint after the kinematic chain; record it explicitly
        # so consumers don't have to slice joint_pos.
        if state.joint_pos.shape[0] > n:
            row["observation.state.gripper_pos"] = float(state.joint_pos[n])
        if bundle.action.q.shape[0] > n:
            row["action.gripper_pos"] = float(bundle.action.q[n])
    for cam_name, frame_idx in video_frame_index.items():
        row[f"observation.images.{cam_name}.video_frame_index"] = frame_idx
        stamped = bundle.frames.get(cam_name)
        row[f"observation.images.{cam_name}.t_mono_ns"] = (
            stamped.t_mono_ns if stamped is not None else 0
        )
    return row
