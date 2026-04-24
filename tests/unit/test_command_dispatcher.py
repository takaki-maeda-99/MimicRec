import asyncio
import numpy as np
import pytest

from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.session.dispatcher import run_command_dispatcher
from mimicrec.types import RobotCommand
from mimicrec.util.error_bus import ErrorBus
from mimicrec.util.latest_value import LatestValue


async def test_dispatcher_sends_each_new_goal_to_robot():
    robot = MockRobotAdapter()
    goal: LatestValue[RobotCommand] = LatestValue()
    bus = ErrorBus()
    stopped = asyncio.Event()

    task = asyncio.create_task(run_command_dispatcher(robot, goal, bus, stopped))

    goal.set(RobotCommand(q=np.array([0.1, 0.2], dtype=np.float32)), t_mono_ns=1)
    await asyncio.sleep(0.05)
    goal.set(RobotCommand(q=np.array([0.3, 0.4], dtype=np.float32)), t_mono_ns=2)
    await asyncio.sleep(0.05)

    stopped.set()
    await task

    sent = robot.sent_commands
    assert any(np.allclose(c, [0.3, 0.4]) for c in sent)
    legal = [np.array([0.1, 0.2], dtype=np.float32), np.array([0.3, 0.4], dtype=np.float32)]
    assert all(any(np.allclose(c, L) for L in legal) for c in sent)


async def test_dispatcher_collapses_bursts_latest_writer_wins():
    robot = MockRobotAdapter()
    async def slow_send(q):
        await asyncio.sleep(0.1)
        robot.sent_commands.append(q.copy())
    robot.send_joint_command = slow_send  # type: ignore[assignment]

    goal: LatestValue[RobotCommand] = LatestValue()
    bus = ErrorBus()
    stopped = asyncio.Event()
    task = asyncio.create_task(run_command_dispatcher(robot, goal, bus, stopped))

    goal.set(RobotCommand(q=np.array([1.0, 0.0], dtype=np.float32)), t_mono_ns=1)
    await asyncio.sleep(0.02)
    goal.set(RobotCommand(q=np.array([2.0, 0.0], dtype=np.float32)), t_mono_ns=2)
    goal.set(RobotCommand(q=np.array([3.0, 0.0], dtype=np.float32)), t_mono_ns=3)
    goal.set(RobotCommand(q=np.array([4.0, 0.0], dtype=np.float32)), t_mono_ns=4)
    await asyncio.sleep(0.25)

    stopped.set()
    await task

    values = [c[0] for c in robot.sent_commands]
    assert 1.0 in values
    assert 4.0 in values
    assert values.count(2.0) + values.count(3.0) <= 1
