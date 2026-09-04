from __future__ import annotations

import numpy as np
import pytest

from mimicrec.adapters.web_teleop import WebTeleoperator


@pytest.mark.asyncio
async def test_ee_axes_are_scaled_and_persist_until_stopped():
    teleop = WebTeleoperator(
        control_mode="ee_delta",
        linear_step_m=0.001,
        angular_step_rad=0.01,
        gripper_step_rad=0.02,
    )
    await teleop.input_queue.put(
        {
            "cmd": "ee_axes",
            "axes": [1, -1, 0, 0, 0.5, -1],
            "gripper": 1,
        }
    )
    action = await teleop.read_action()
    assert np.allclose(action.ee_delta, [0.001, -0.001, 0, 0, 0.005, -0.01])
    assert action.gripper_delta == pytest.approx(0.02)

    action = await teleop.read_action()
    assert action.ee_delta[0] == pytest.approx(0.001)

    teleop.stop_motion()
    action = await teleop.read_action()
    assert np.allclose(action.ee_delta, 0.0)
    assert action.gripper_delta == 0.0


@pytest.mark.asyncio
async def test_invalid_ee_axes_are_ignored():
    teleop = WebTeleoperator(control_mode="ee_delta")
    await teleop.input_queue.put({"cmd": "ee_axes", "axes": [1, 2]})
    action = await teleop.read_action()
    assert np.allclose(action.ee_delta, 0.0)


@pytest.mark.asyncio
async def test_ee_velocity_is_converted_to_per_control_tick_delta():
    teleop = WebTeleoperator(control_mode="ee_delta", control_rate_hz=50)
    await teleop.input_queue.put(
        {
            "cmd": "ee_velocity",
            "velocity": [0.1, -0.05, 0, 1.0, 0, -0.5],
            "gripper_velocity": 0.2,
        }
    )

    action = await teleop.read_action()

    assert np.allclose(
        action.ee_delta,
        [0.002, -0.001, 0, 0.02, 0, -0.01],
    )
    assert action.gripper_delta == pytest.approx(0.004)


@pytest.mark.asyncio
async def test_ee_velocity_stops_after_input_timeout():
    now = 100.0
    teleop = WebTeleoperator(
        control_mode="ee_delta",
        control_rate_hz=60,
        input_timeout_sec=0.25,
    )
    teleop._monotonic = lambda: now
    await teleop.input_queue.put(
        {"cmd": "ee_velocity", "velocity": [0.1, 0, 0, 0, 0, 0]}
    )
    assert (await teleop.read_action()).ee_delta[0] > 0

    now = 100.3
    action = await teleop.read_action()

    assert np.allclose(action.ee_delta, 0.0)


@pytest.mark.asyncio
async def test_invalid_ee_velocity_is_ignored():
    teleop = WebTeleoperator(control_mode="ee_delta")
    await teleop.input_queue.put(
        {"cmd": "ee_velocity", "velocity": [float("nan"), 0, 0, 0, 0, 0]}
    )
    action = await teleop.read_action()
    assert np.allclose(action.ee_delta, 0.0)


@pytest.mark.asyncio
async def test_pose_offset_is_forwarded_without_control_rate_scaling():
    teleop = WebTeleoperator(control_mode="ee_delta", control_rate_hz=50)
    await teleop.input_queue.put(
        {
            "cmd": "ee_pose_offset",
            "offset": [0.1, -0.2, 0, 0, 0, 0.75],
            "gripper_fraction": 0.6,
        }
    )

    action = await teleop.read_action()

    assert np.allclose(action.ee_pose_offset, [0.1, -0.2, 0, 0, 0, 0.75])
    assert action.ee_pose_active is True
    assert action.gripper_fraction == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_world_delta_is_forwarded_as_one_cartesian_step():
    teleop = WebTeleoperator(control_mode="ee_delta", control_rate_hz=60)
    await teleop.input_queue.put(
        {
            "cmd": "ee_world_delta",
            "delta": [0.01, -0.02, 0.03, 0.1, 0.0, -0.1],
            "gripper_fraction": 0.25,
        }
    )

    action = await teleop.read_action()

    assert action.ee_cartesian_delta == pytest.approx(
        [0.01, -0.02, 0.03, 0.1, 0.0, -0.1]
    )
    assert action.ee_pose_active is True
    assert action.gripper_fraction == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_world_pose_offset_is_retained_as_absolute_target():
    teleop = WebTeleoperator(control_mode="ee_delta", control_rate_hz=60)
    await teleop.input_queue.put(
        {
            "cmd": "ee_world_pose_offset",
            "offset": [0.1, -0.2, 0.3, 0.0, 0.2, 0.0],
            "gripper_fraction": 0.75,
        }
    )

    action = await teleop.read_action()

    assert action.ee_world_pose_offset == pytest.approx(
        [0.1, -0.2, 0.3, 0.0, 0.2, 0.0]
    )
    assert action.ee_pose_active is True
    assert action.gripper_fraction == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_pose_offset_timeout_releases_pose_reference():
    now = 100.0
    teleop = WebTeleoperator(
        control_mode="ee_delta", control_rate_hz=60, input_timeout_sec=0.25
    )
    teleop._monotonic = lambda: now
    await teleop.input_queue.put(
        {"cmd": "ee_pose_offset", "offset": [0, 0, 0, 0, 0, 0.5]}
    )
    assert (await teleop.read_action()).ee_pose_active is True

    now = 100.3
    action = await teleop.read_action()

    assert action.ee_pose_active is False
    assert action.ee_pose_offset is None


@pytest.mark.asyncio
async def test_home_is_a_one_shot_and_releases_pose_control():
    teleop = WebTeleoperator(control_mode="ee_delta")
    await teleop.input_queue.put({"cmd": "home"})

    action = await teleop.read_action()
    following = await teleop.read_action()

    assert action.home_requested is True
    assert action.ee_pose_active is False
    assert following.home_requested is False


@pytest.mark.asyncio
async def test_pose_rearm_ignores_motion_until_stop_then_fresh_pose():
    teleop = WebTeleoperator(control_mode="ee_delta")
    teleop.require_pose_release()
    pose_message = {
        "cmd": "ee_pose_offset",
        "offset": [0.1, 0, 0, 0, 0, 0],
        "gripper_fraction": 0.5,
    }
    await teleop.input_queue.put(pose_message)
    blocked = await teleop.read_action()
    assert blocked.ee_pose_active is False

    await teleop.input_queue.put({"cmd": "stop"})
    await teleop.input_queue.put(pose_message)
    rearmed = await teleop.read_action()
    assert rearmed.ee_pose_active is True
    assert rearmed.ee_pose_offset[0] == pytest.approx(0.1)
