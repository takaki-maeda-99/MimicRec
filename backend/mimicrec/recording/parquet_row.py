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
    # Observation EE: prefer values already on RobotState (e.g. supplied by a
    # daemon-side FK). Fall back to local fk only when state has no EE.
    obs_ee_pos = state.ee_pos
    obs_ee_rotvec = state.ee_rotvec
    obs_gripper = state.gripper_pos
    if obs_ee_pos is None and fk is not None:
        n = fk.n_kin_joints
        obs_ee_pos, obs_ee_rotvec = fk.pose(state.joint_pos[:n])
        if state.joint_pos.shape[0] > n:
            obs_gripper = float(state.joint_pos[n])

    # Action EE: derived from commanded q. Action has no "ee_pos" field today,
    # so always use FK when fk is set; otherwise omit. Gripper comes from
    # ``bundle.action.gripper`` directly — RobotCommand carries the gripper
    # target in its own field rather than appended to ``q``.
    act_ee_pos = act_ee_rotvec = None
    act_gripper = bundle.action.gripper
    if fk is not None:
        n = fk.n_kin_joints
        act_ee_pos, act_ee_rotvec = fk.pose(bundle.action.q[:n])

    if obs_ee_pos is not None:
        row["observation.state.ee_pos"] = obs_ee_pos
        row["observation.state.ee_rotvec"] = obs_ee_rotvec
    if obs_gripper is not None:
        row["observation.state.gripper_pos"] = float(obs_gripper)
    if act_ee_pos is not None:
        row["action.ee_pos"] = act_ee_pos
        row["action.ee_rotvec"] = act_ee_rotvec
    if act_gripper is not None:
        row["action.gripper_pos"] = act_gripper
    for cam_name, frame_idx in video_frame_index.items():
        row[f"observation.images.{cam_name}.video_frame_index"] = frame_idx
        stamped = bundle.frames.get(cam_name)
        row[f"observation.images.{cam_name}.t_mono_ns"] = (
            stamped.t_mono_ns if stamped is not None else 0
        )
    return row
