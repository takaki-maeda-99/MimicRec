from __future__ import annotations
from mimicrec.types import SampleBundle


def sample_bundle_to_row(
    bundle: SampleBundle,
    episode_start_t_mono_ns: int,
    video_frame_index: dict[str, int],
    frame_index: int = 0,
    episode_index: int = 0,
    global_index: int = 0,
    task_index: int = 0,
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
    for cam_name, frame_idx in video_frame_index.items():
        row[f"observation.images.{cam_name}.video_frame_index"] = frame_idx
        stamped = bundle.frames.get(cam_name)
        row[f"observation.images.{cam_name}.t_mono_ns"] = (
            stamped.t_mono_ns if stamped is not None else 0
        )
    return row
