import json

import pytest

from mimicrec.datasets.exporters.info_json import to_vla_info


def _make_input_info(joint_names: list[str]) -> dict:
    dof = len(joint_names)
    return {
        "codebase_version": "v3.0",
        "robot_type": "so101_follower",
        "total_episodes": 9,
        "total_frames": 1183,
        "total_tasks": 1,
        "chunks_size": 1000,
        "fps": 15,
        "splits": {"train": "0:9"},
        "data_path": "data/chunk-{chunk_index:03d}/episode_{episode_index:06d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/episode_{episode_index:06d}.mp4",
        "features": {
            "action": {"dtype": "float32", "shape": [dof], "names": joint_names},
            "observation.state": {"dtype": "float32", "shape": [dof], "names": joint_names},
            "timestamp": {"dtype": "float32", "shape": [1], "names": None},
            "frame_index": {"dtype": "int64", "shape": [1], "names": None},
            "episode_index": {"dtype": "int64", "shape": [1], "names": None},
            "index": {"dtype": "int64", "shape": [1], "names": None},
            "task_index": {"dtype": "int64", "shape": [1], "names": None},
            "observation.images.front": {
                "dtype": "video",
                "shape": [480, 640, 3],
                "names": ["height", "width", "channels"],
                "info": {"video.height": 480, "video.width": 640, "video.fps": 15},
            },
        },
    }


def test_action_and_observation_state_become_shape_7():
    info = _make_input_info(["j1", "j2", "j3", "j4", "j5", "j6"])
    out = to_vla_info(info)
    assert out["features"]["action"]["shape"] == [7]
    assert out["features"]["action"]["names"] == ["j1", "j2", "j3", "j4", "j5", "j6", "gripper"]
    assert out["features"]["observation.state"]["shape"] == [7]
    assert out["features"]["observation.state"]["names"] == ["j1", "j2", "j3", "j4", "j5", "j6", "gripper"]


def test_language_instruction_feature_added():
    info = _make_input_info(["j1", "j2", "j3", "j4", "j5", "j6"])
    out = to_vla_info(info)
    li = out["features"]["language_instruction"]
    assert li["dtype"] == "string"
    assert li["shape"] == [1]


def test_video_and_pass_through_keys_unchanged():
    info = _make_input_info(["j1", "j2", "j3", "j4", "j5", "j6"])
    out = to_vla_info(info)
    assert out["fps"] == 15
    assert out["splits"] == {"train": "0:9"}
    assert out["features"]["observation.images.front"] == \
        info["features"]["observation.images.front"]


def test_input_dict_is_not_mutated():
    info = _make_input_info(["j1", "j2", "j3", "j4", "j5", "j6"])
    original_action_shape = info["features"]["action"]["shape"]
    _ = to_vla_info(info)
    assert info["features"]["action"]["shape"] == original_action_shape


def test_works_when_input_action_already_has_extra_columns_definition():
    """info.json shipped by the SO-101 v3 collector declares action shape=[6]
    even though the parquet has been split. We accept either."""
    info = _make_input_info(["j1", "j2", "j3", "j4", "j5", "j6"])
    out = to_vla_info(info)
    assert out["features"]["action"]["shape"] == [7]
