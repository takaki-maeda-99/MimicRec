import asyncio
import numpy as np

from mimicrec.adapters.fault_profile import FaultProfile
from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.control_loop import run_teleop_control_loop
from mimicrec.session.state import Session
from mimicrec.types import RobotCommand, RobotState, SessionMode, SessionState, TeleopAction
from mimicrec.util.clock import RealClock
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics
from tests.conftest import _prime_robot_reader, _prime_teleop_reader


async def test_stale_samples_detected_under_latency(mock_teleop):
    # Robot reader adds 150ms fault latency on top of 5ms base,
    # so each read takes ~155ms.  At 30 fps the stale threshold
    # is 3 * 33ms = 100ms -- the slot timestamp will routinely
    # lag behind tick_t by more than that.
    robot = MockRobotAdapter(fault=FaultProfile(latency_ms=150, jitter_ms=10))
    session = Session(mode=SessionMode.TELEOP, state=SessionState.READY)
    rs: LatestValue[RobotState] = LatestValue()
    ts: LatestValue[TeleopAction] = LatestValue()
    cg: LatestValue[RobotCommand] = LatestValue()
    metrics = Metrics()

    r = await _prime_robot_reader(robot, rs)
    t = await _prime_teleop_reader(mock_teleop, ts)
    loop = asyncio.create_task(run_teleop_control_loop(
        session=session, fps=30,
        robot_state_slot=rs, teleop_slot=ts, camera_slots={},
        command_goal_slot=cg, mapper=IdentityMapper(),
        enqueue=lambda b: None, clock=RealClock(), metrics=metrics,
    ))

    await asyncio.sleep(0.6)
    session.stopped.set()
    await loop
    r.cancel(); t.cancel()

    assert metrics.get("stale_sample_count") > 0


async def test_stale_sample_counter_increments_when_reader_is_stuck(mock_teleop):
    robot = MockRobotAdapter(fault=FaultProfile(stuck_for_n_calls=1000, latency_ms=120))
    session = Session(mode=SessionMode.TELEOP, state=SessionState.RECORDING)
    rs: LatestValue[RobotState] = LatestValue()
    ts: LatestValue[TeleopAction] = LatestValue()
    cg: LatestValue[RobotCommand] = LatestValue()
    metrics = Metrics()

    r = await _prime_robot_reader(robot, rs)
    t = await _prime_teleop_reader(mock_teleop, ts)
    loop = asyncio.create_task(run_teleop_control_loop(
        session=session, fps=30,
        robot_state_slot=rs, teleop_slot=ts, camera_slots={},
        command_goal_slot=cg, mapper=IdentityMapper(),
        enqueue=lambda b: None, clock=RealClock(), metrics=metrics,
    ))
    await asyncio.sleep(0.5)
    session.stopped.set()
    await loop
    r.cancel(); t.cancel()

    assert metrics.get("stale_sample_count") > 0
