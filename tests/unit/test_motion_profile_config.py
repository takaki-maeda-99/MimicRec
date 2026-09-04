from pathlib import Path

import pytest
from omegaconf import OmegaConf

from mimicrec.api.schemas import MotionProfileSessionRequest
from mimicrec.motion.config import build_motion_profile
from mimicrec.motion.se3 import SE3Frame


def test_repository_bimanual_profile_builds_named_graph_without_hardware_io():
    root = Path(__file__).resolve().parents[2] / "configs"

    built = build_motion_profile(
        "quest_bimanual_rebot_so101", configs_root=root
    )

    assert built.runtime.resource_names == (
        "right_robot.arm",
        "right_robot.gripper",
        "left_robot.arm",
        "left_robot.gripper",
    )
    assert [group.name for group in built.runtime.motion_groups] == [
        "right_hand",
        "left_hand",
    ]
    assert set(built.teleop_router.channels) == {"right", "left"}
    assert all(
        motion_input.source.converter.frame == SE3Frame.WORLD
        for motion_input in built.runtime.motion_inputs
    )
    right = next(
        group for group in built.runtime.motion_groups if group.name == "right_hand"
    )
    assert right.mapper.target_frame == "base"
    assert right.mapper.mapper._delta_frame == "base"
    left = next(
        group for group in built.runtime.motion_groups if group.name == "left_hand"
    )
    assert left.mapper.arm_resource == "left_robot.arm"


def test_native_mapper_resource_is_derived_from_profile_output():
    root = Path(__file__).resolve().parents[2] / "configs"
    document = OmegaConf.to_container(
        OmegaConf.load(root / "motion_profiles/quest_bimanual_rebot_so101.yaml"),
        resolve=True,
    )
    document["adapters"]["left_unit"] = document["adapters"].pop("left_robot")
    document["home"]["adapters"]["left_unit"] = document["home"][
        "adapters"
    ].pop("left_robot")
    document["motion_groups"]["left_hand"]["outputs"] = [
        "left_unit.arm",
        "left_unit.gripper",
    ]
    built = build_motion_profile(
        "renamed", configs_root=root, document=document
    )
    left = next(
        group for group in built.runtime.motion_groups if group.name == "left_hand"
    )

    assert left.mapper.arm_resource == "left_unit.arm"
    assert left.mapper.gripper_resource == "left_unit.gripper"


def test_motion_session_request_does_not_require_single_robot_mapper_pair():
    request = MotionProfileSessionRequest(
        mode="motion",
        profile="quest_bimanual_rebot_so101",
        dataset="demo",
        task="pick",
    )

    assert request.robot is None
    assert request.profile == "quest_bimanual_rebot_so101"


def test_missing_profile_fails_before_any_adapter_connect(tmp_path):
    (tmp_path / "motion_profiles").mkdir()

    with pytest.raises(FileNotFoundError):
        build_motion_profile("missing", configs_root=tmp_path)
