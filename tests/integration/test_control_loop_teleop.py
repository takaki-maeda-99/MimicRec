import asyncio
import numpy as np
import pytest

from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.control_loop import run_teleop_control_loop
from mimicrec.session.state import Session
from mimicrec.types import (
    RobotCommand, RobotState, SampleBundle, SessionMode, SessionState, TeleopAction,
)
from mimicrec.util.clock import RealClock
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics
from tests.conftest import _prime_robot_reader, _prime_teleop_reader


async def test_teleop_loop_records_samples_only_while_recording(mock_robot, mock_teleop, metrics):
    session = Session(mode=SessionMode.TELEOP, state=SessionState.READY)
    rs: LatestValue[RobotState] = LatestValue()
    ts: LatestValue[TeleopAction] = LatestValue()
    cg: LatestValue[RobotCommand] = LatestValue()

    r_task = await _prime_robot_reader(mock_robot, rs)
    t_task = await _prime_teleop_reader(mock_teleop, ts)

    bundles: list[SampleBundle] = []
    def enqueue(b: SampleBundle) -> None:
        bundles.append(b)

    loop_task = asyncio.create_task(run_teleop_control_loop(
        session=session, fps=30,
        robot_state_slot=rs, teleop_slot=ts, camera_slots={},
        command_goal_slot=cg, mapper=IdentityMapper(),
        enqueue=enqueue, clock=RealClock(), metrics=metrics,
    ))

    await asyncio.sleep(0.1)
    count_before = len(bundles)
    assert count_before == 0
    assert cg.peek() is not None

    session.state = SessionState.RECORDING
    await asyncio.sleep(0.2)
    count_during = len(bundles)
    assert count_during >= 3

    session.state = SessionState.REVIEW
    await asyncio.sleep(0.2)
    count_after_review = len(bundles)

    assert count_after_review - count_during <= 1

    session.state = SessionState.READY
    await asyncio.sleep(0.1)

    session.stopped.set()
    await loop_task
    r_task.cancel(); t_task.cancel()
