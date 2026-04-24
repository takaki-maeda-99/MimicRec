import asyncio

from mimicrec.adapters.robot import RobotMode
from mimicrec.session.control_loop import run_handteach_control_loop
from mimicrec.session.state import Session
from mimicrec.types import RobotState, SampleBundle, SessionMode, SessionState
from mimicrec.util.clock import RealClock
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics
from tests.conftest import _prime_robot_reader


async def test_handteach_sets_gravity_comp_and_fills_action(mock_robot, metrics):
    session = Session(mode=SessionMode.HAND_TEACH, state=SessionState.RECORDING)
    rs: LatestValue[RobotState] = LatestValue()
    r = await _prime_robot_reader(mock_robot, rs)

    bundles: list[SampleBundle] = []
    loop_task = asyncio.create_task(run_handteach_control_loop(
        session=session, fps=30,
        robot_adapter=mock_robot, robot_state_slot=rs, camera_slots={},
        enqueue=bundles.append, clock=RealClock(), metrics=metrics,
    ))
    await asyncio.sleep(0.15)

    assert mock_robot._mode == RobotMode.GRAVITY_COMP
    assert len(bundles) >= 3
    for b in bundles:
        assert (b.action.q == b.state.value.joint_pos).all()

    session.stopped.set()
    await loop_task
    r.cancel()
