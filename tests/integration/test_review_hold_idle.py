import asyncio

from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.control_loop import run_teleop_control_loop
from mimicrec.session.state import Session
from mimicrec.types import RobotCommand, RobotState, SessionMode, SessionState, TeleopAction
from mimicrec.util.clock import RealClock
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics
from tests.conftest import _prime_robot_reader, _prime_teleop_reader


async def test_review_holds_last_command_goal(mock_robot, mock_teleop, metrics):
    session = Session(mode=SessionMode.TELEOP, state=SessionState.READY)
    rs: LatestValue[RobotState] = LatestValue()
    ts: LatestValue[TeleopAction] = LatestValue()
    cg: LatestValue[RobotCommand] = LatestValue()

    r = await _prime_robot_reader(mock_robot, rs)
    t = await _prime_teleop_reader(mock_teleop, ts)

    loop_task = asyncio.create_task(run_teleop_control_loop(
        session=session, fps=30,
        robot_state_slot=rs, teleop_slot=ts, camera_slots={},
        command_goal_slot=cg, mapper=IdentityMapper(),
        enqueue=lambda b: None, clock=RealClock(), metrics=metrics,
    ))

    await asyncio.sleep(0.1)
    first = cg.peek()
    assert first is not None
    first_t = first.t_mono_ns

    session.state = SessionState.REVIEW
    await asyncio.sleep(0.15)
    after_review = cg.peek()
    assert after_review is not None
    assert after_review.t_mono_ns == first_t

    session.state = SessionState.READY
    await asyncio.sleep(0.1)
    resumed = cg.peek()
    assert resumed is not None
    assert resumed.t_mono_ns > first_t

    session.stopped.set()
    await loop_task
    r.cancel(); t.cancel()
