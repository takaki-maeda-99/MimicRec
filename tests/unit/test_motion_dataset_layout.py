import json

from mimicrec.recording.dataset_layout import init_motion_dataset


def test_init_motion_dataset_declares_namespaced_features(tmp_path):
    init_motion_dataset(
        tmp_path / "dataset",
        30,
        resources={
            "right_robot.arm": {"kind": "joint", "joint_names": ["j1", "j2"]},
            "right_robot.gripper": {"kind": "scalar"},
            "base.drive": {"kind": "planar"},
        },
        motion_groups={
            "right_hand": {"auxiliary": ["gripper"]},
            "locomotion": {"auxiliary": []},
        },
        camera_names=[],
        profile_name="mobile_right_arm",
    )

    info = json.loads((tmp_path / "dataset" / "meta" / "info.json").read_text())
    features = info["features"]
    assert "action.motion.right_hand.se3_delta" in features
    assert "observation.state.right_robot.arm.joint_pos" in features
    assert "action.resource.right_robot.gripper.position" in features
    assert "action.resource.base.drive.velocity_xy_yaw" in features
    assert info["motion_schema"]["representation"] == "se3_log_increment"
    assert info["motion_schema"]["profile"] == "mobile_right_arm"
