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


def test_init_dataset_writes_per_camera_resolution(tmp_path):
    init_dataset(
        tmp_path / "ds",
        fps=30,
        joint_names=["a", "b"],
        camera_names=["wrist", "front"],
        camera_resolutions={"wrist": (1920, 1080), "front": (640, 480)},
    )
    info = json.loads((tmp_path / "ds" / "meta" / "info.json").read_text())
    wrist = info["features"]["observation.images.wrist"]
    front = info["features"]["observation.images.front"]
    assert wrist["shape"] == [1080, 1920, 3]  # [height, width, channels]
    assert wrist["info"]["video.height"] == 1080
    assert wrist["info"]["video.width"] == 1920
    assert front["shape"] == [480, 640, 3]
    assert front["info"]["video.height"] == 480
    assert front["info"]["video.width"] == 640


def test_init_dataset_falls_back_to_default_resolution(tmp_path):
    # When camera_resolutions is not provided, the legacy 640x480 default applies.
    init_dataset(
        tmp_path / "ds",
        fps=30,
        joint_names=["a"],
        camera_names=["cam0"],
    )
    info = json.loads((tmp_path / "ds" / "meta" / "info.json").read_text())
    cam = info["features"]["observation.images.cam0"]
    assert cam["shape"] == [480, 640, 3]
    assert cam["info"]["video.height"] == 480
    assert cam["info"]["video.width"] == 640
