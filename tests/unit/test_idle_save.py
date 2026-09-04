"""save_idle_pose: yaml 書き出しと atomic write を検証。"""
from __future__ import annotations
import math

import numpy as np
import pytest
import yaml

from mimicrec.adapters.robot import RobotMode
from mimicrec.session.idle import IdlePose, load_idle_pose, move_to_idle, save_idle_pose
from mimicrec.types import RobotState


def _pose() -> IdlePose:
    return IdlePose(
        joint_pos_rad=np.array([0.1, -0.2, 0.3, -0.4, 0.5, -0.6], dtype=np.float32),
        gripper_pos=12.5,
        joint_names=("j1", "j2", "j3", "j4", "j5", "j6"),
    )


def test_save_writes_expected_schema(tmp_path):
    path = tmp_path / "idle.yaml"
    pose = _pose()

    written = save_idle_pose(pose, path, source="ui_capture via session adapter")

    doc = yaml.safe_load(path.read_text())
    assert doc["joint_names"] == list(pose.joint_names)
    assert doc["joint_pos_rad"] == pytest.approx(pose.joint_pos_rad.tolist(), abs=1e-6)
    assert doc["joint_pos_deg"] == pytest.approx(
        [math.degrees(x) for x in pose.joint_pos_rad.tolist()], abs=1e-4
    )
    assert doc["gripper_pos"] == pytest.approx(pose.gripper_pos)
    assert isinstance(doc["captured_at_unix"], (int, float))
    assert doc["source"] == "ui_capture via session adapter"
    # ファイル内容と返り値が一致
    assert written == doc


def test_save_roundtrips_through_load(tmp_path):
    path = tmp_path / "idle.yaml"
    pose = _pose()
    save_idle_pose(pose, path)
    loaded = load_idle_pose(path)
    assert loaded.joint_names == pose.joint_names
    assert loaded.joint_pos_rad.tolist() == pytest.approx(pose.joint_pos_rad.tolist(), abs=1e-6)
    assert loaded.gripper_pos == pytest.approx(pose.gripper_pos)


def test_save_handles_missing_gripper(tmp_path):
    path = tmp_path / "idle.yaml"
    pose = IdlePose(
        joint_pos_rad=np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32),
        gripper_pos=None,
        joint_names=("j1", "j2", "j3", "j4", "j5", "j6"),
    )
    save_idle_pose(pose, path)
    doc = yaml.safe_load(path.read_text())
    assert doc["gripper_pos"] is None


def test_save_is_atomic_against_existing_file(tmp_path):
    """既存ファイルが先にあって書き込みが成功した場合、内容が完全に置き換わる
    (tempfile + rename パターン)。
    """
    path = tmp_path / "idle.yaml"
    path.write_text("garbage: true\n")
    save_idle_pose(_pose(), path)
    doc = yaml.safe_load(path.read_text())
    assert "garbage" not in doc
    assert "joint_pos_rad" in doc


def test_load_rejects_non_finite_pose(tmp_path):
    path = tmp_path / "idle.yaml"
    path.write_text("joint_pos_rad: [0.0, .nan]\n")
    with pytest.raises(ValueError, match="non-finite"):
        load_idle_pose(path)


class _ImmediateClock:
    def __init__(self):
        self.now = 0

    def monotonic_ns(self):
        return self.now

    async def sleep_until(self, target):
        self.now = target


class _IdleAdapter:
    joint_names = ["j1", "j2"]

    def __init__(self):
        self.joint_commands = []
        self.gripper_commands = []
        self.modes = []

    async def read_state(self):
        return RobotState(
            joint_pos=np.array([0.0, 0.0], dtype=np.float32),
            joint_vel=np.zeros(2, dtype=np.float32),
            joint_effort=np.zeros(2, dtype=np.float32),
            gripper_pos=-5.0,
        )

    async def set_mode(self, mode):
        self.modes.append(mode)

    async def send_joint_command(self, value):
        self.joint_commands.append(np.asarray(value).copy())

    async def send_gripper_command(self, value):
        self.gripper_commands.append(float(value))


@pytest.mark.asyncio
async def test_move_to_idle_ramps_arm_and_gripper():
    adapter = _IdleAdapter()
    pose = IdlePose(
        joint_pos_rad=np.array([1.0, -1.0], dtype=np.float32),
        gripper_pos=-1.0,
        joint_names=("j1", "j2"),
    )

    await move_to_idle(
        adapter,
        idle_pose=pose,
        duration_sec=0.2,
        fps=10,
        hold_sec=0.1,
        after_mode=RobotMode.POSITION,
        clock=_ImmediateClock(),
    )

    assert adapter.modes == [RobotMode.POSITION]
    assert np.allclose(adapter.joint_commands[-1], [1.0, -1.0])
    assert adapter.gripper_commands[-1] == pytest.approx(-1.0)
    assert adapter.gripper_commands[0] == pytest.approx(-3.0)


@pytest.mark.asyncio
async def test_move_to_idle_rejects_joint_name_mismatch():
    adapter = _IdleAdapter()
    pose = IdlePose(
        joint_pos_rad=np.array([0.0, 0.0], dtype=np.float32),
        gripper_pos=None,
        joint_names=("other1", "other2"),
    )
    with pytest.raises(ValueError, match="joint_names"):
        await move_to_idle(adapter, idle_pose=pose, clock=_ImmediateClock())
