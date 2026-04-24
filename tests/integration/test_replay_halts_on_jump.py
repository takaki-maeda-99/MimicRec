import asyncio
import numpy as np
import pytest

from mimicrec.errors import ReplaySafetyError
from mimicrec.session.replay import ReplayTrajectory, run_replay
from mimicrec.session.replay_safety import ReplaySafetyConfig
from mimicrec.session.state import Session
from mimicrec.types import RobotCommand, RobotState, SessionMode, SessionState, Stamped
from mimicrec.util.clock import RealClock
from mimicrec.util.error_bus import ErrorBus
from mimicrec.util.latest_value import LatestValue


async def test_replay_halts_on_position_jump_and_holds_measured():
    session = Session(mode=SessionMode.TELEOP, state=SessionState.READY)
    cg: LatestValue[RobotCommand] = LatestValue()
    measured: LatestValue[RobotState] = LatestValue()
    measured.set(
        RobotState(
            joint_pos=np.zeros(2, dtype=np.float32),
            joint_vel=np.zeros(2, np.float32),
            joint_effort=np.zeros(2, np.float32),
        ),
        t_mono_ns=1,
    )

    cfg = ReplaySafetyConfig(
        ramp_duration_sec=0.0,
        max_joint_velocity=10.0,
        max_joint_acceleration=1000.0,
        max_joint_position_jump=0.1,
        command_timeout_sec=1.0,
        watchdog_hz=20,
        dof=2,
        dt_sec=1 / 30,
    )
    traj = ReplayTrajectory(joint_targets=np.array([[5.0, 5.0]], dtype=np.float32))
    bus = ErrorBus()
    sub = bus.subscribe()

    with pytest.raises(ReplaySafetyError):
        await run_replay(
            session=session, trajectory=traj, fps=30,
            command_goal_slot=cg, measured_state_slot=measured,
            clock=RealClock(), safety=cfg, error_bus=bus,
        )
    assert session.replay_active is False
    held = cg.peek()
    assert held is not None
    assert (held.value.q == 0.0).all()
    evt = sub.get_nowait()
    assert isinstance(evt, ReplaySafetyError)
