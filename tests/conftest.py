from __future__ import annotations
import asyncio
from typing import AsyncIterator
import time

import pytest

from mimicrec.adapters.mock_robot import MockRobotAdapter
from mimicrec.adapters.mock_teleop import MockTeleoperator
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.session.state import Session
from mimicrec.types import RobotCommand, RobotState, SampleBundle, SessionMode, SessionState, TeleopAction
from mimicrec.util.clock import FakeClock, RealClock
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics


@pytest.fixture
def real_clock():
    return RealClock()


@pytest.fixture
def fake_clock():
    return FakeClock(start_ns=0)


@pytest.fixture
def metrics():
    return Metrics()


@pytest.fixture
def mock_robot():
    return MockRobotAdapter()


@pytest.fixture
def mock_teleop():
    return MockTeleoperator(dof=2)


async def _prime_robot_reader(robot, slot: LatestValue[RobotState]) -> asyncio.Task:
    async def run():
        while True:
            t = time.monotonic_ns()
            st = await robot.read_state()
            st.t_mono_ns = t
            slot.set(st, t_mono_ns=t)
    return asyncio.create_task(run())


async def _prime_teleop_reader(teleop, slot: LatestValue[TeleopAction]) -> asyncio.Task:
    async def run():
        while True:
            t = time.monotonic_ns()
            a = await teleop.read_action()
            a.t_mono_ns = t
            slot.set(a, t_mono_ns=t)
    return asyncio.create_task(run())
