import asyncio
import numpy as np

from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.control_loop import run_teleop_control_loop
from mimicrec.session.replay import ReplayTrajectory, run_replay
from mimicrec.session.state import Session
from mimicrec.types import (
    RobotCommand, RobotState, SessionMode, SessionState, SubState, TeleopAction,
)
from mimicrec.util.clock import RealClock
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics
from tests.conftest import _prime_robot_reader, _prime_teleop_reader


async def test_replay_gates_teleop_command_path(mock_robot, mock_teleop, metrics):
    session = Session(mode=SessionMode.TELEOP, state=SessionState.READY)
    rs: LatestValue[RobotState] = LatestValue()
    ts: LatestValue[TeleopAction] = LatestValue()
    cg: LatestValue[RobotCommand] = LatestValue()

    r = await _prime_robot_reader(mock_robot, rs)
    t = await _prime_teleop_reader(mock_teleop, ts)

    loop = asyncio.create_task(run_teleop_control_loop(
        session=session, fps=30,
        robot_state_slot=rs, teleop_slot=ts, camera_slots={},
        command_goal_slot=cg, mapper=IdentityMapper(),
        enqueue=lambda b: None, clock=RealClock(), metrics=metrics,
    ))

    mock_teleop.target = np.array([0.5, 0.5], dtype=np.float32)
    await asyncio.sleep(0.1)
    before = cg.peek().value.q.copy()

    traj = ReplayTrajectory(joint_targets=np.array(
        [[-1.0, -1.0]] * 30, dtype=np.float32
    ))
    replay_task = asyncio.create_task(run_replay(
        session=session, trajectory=traj, fps=30,
        command_goal_slot=cg, clock=RealClock(),
    ))
    await asyncio.sleep(0.05)
    assert session.replay_active is True
    assert session.sub_state == SubState.REPLAYING

    mock_teleop.target = np.array([9.9, 9.9], dtype=np.float32)
    await asyncio.sleep(0.15)
    during = cg.peek().value.q.copy()
    assert during[0] == -1.0 or during[1] == -1.0, f"expected replay target, got {during}"
    assert not (during == 9.9).any(), "teleop leaked into command goal during replay"

    await replay_task
    assert session.replay_active is False

    await asyncio.sleep(0.1)
    after = cg.peek().value.q.copy()
    assert (after == 9.9).any(), "teleop did not resume after replay"

    session.stopped.set()
    await loop
    r.cancel(); t.cancel()
