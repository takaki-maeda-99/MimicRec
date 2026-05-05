import json
from pathlib import Path

from mimicrec.recording.dataset_layout import init_dataset


def test_init_dataset_writes_robot_type_when_provided(tmp_path):
    init_dataset(
        tmp_path / "ds",
        fps=15,
        joint_names=["a", "b"],
        camera_names=["front"],
        robot_type="SO101Adapter",
    )
    info = json.loads((tmp_path / "ds" / "meta" / "info.json").read_text())
    assert info["robot_type"] == "SO101Adapter"


def test_init_dataset_falls_back_to_unknown(tmp_path):
    init_dataset(
        tmp_path / "ds",
        fps=15,
        joint_names=["a", "b"],
        camera_names=["front"],
    )
    info = json.loads((tmp_path / "ds" / "meta" / "info.json").read_text())
    assert info["robot_type"] == "unknown"


def test_init_dataset_writes_gripper_convention(tmp_path):
    init_dataset(
        tmp_path / "ds",
        fps=15,
        joint_names=["a", "b"],
        camera_names=["front"],
        robot_type="SO101Adapter",
        gripper_convention={"closed_at": 0.0, "open_at": 100.0},
    )
    info = json.loads((tmp_path / "ds" / "meta" / "info.json").read_text())
    assert info["gripper_convention"] == {"closed_at": 0.0, "open_at": 100.0}


def test_init_dataset_writes_proprio_layout(tmp_path):
    layout = {
        "columns": ["observation.state.joint_pos"],
        "output_names": ["shoulder_pan", "gripper"],
        "gripper_via_column": "observation.state.joint_pos",
        "gripper_index_in_column": 1,
    }
    init_dataset(
        tmp_path / "ds",
        fps=15,
        joint_names=["a", "b"],
        camera_names=["front"],
        robot_type="SO101Adapter",
        proprio_layout=layout,
    )
    info = json.loads((tmp_path / "ds" / "meta" / "info.json").read_text())
    assert info["proprio_layout"] == layout


def test_init_dataset_omits_optional_fields_when_not_supplied(tmp_path):
    init_dataset(
        tmp_path / "ds",
        fps=15,
        joint_names=["a", "b"],
        camera_names=["front"],
    )
    info = json.loads((tmp_path / "ds" / "meta" / "info.json").read_text())
    assert "gripper_convention" not in info
    assert "proprio_layout" not in info
