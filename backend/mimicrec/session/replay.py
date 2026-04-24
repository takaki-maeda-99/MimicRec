from __future__ import annotations
import asyncio
from dataclasses import dataclass

import numpy as np

from mimicrec.session.state import Session
from mimicrec.types import RobotCommand, SessionState, SubState
from mimicrec.util.clock import Clock
from mimicrec.util.latest_value import LatestValue


@dataclass
class ReplayTrajectory:
    """Simplest possible trajectory: list of joint-target vectors at the session fps."""
    joint_targets: np.ndarray   # shape (T, dof)


async def run_replay(
    session: Session,
    trajectory: ReplayTrajectory,
    fps: int,
    command_goal_slot: LatestValue[RobotCommand],
    clock: Clock,
    measured_state_slot: "LatestValue | None" = None,
    safety: "object | None" = None,
    error_bus: "object | None" = None,
) -> None:
    if session.state != SessionState.READY:
        from mimicrec.errors import InvalidTransitionError
        raise InvalidTransitionError(
            f"replay requires SessionState.READY, got {session.state}"
        )
    if session.replay_active:
        from mimicrec.errors import InvalidTransitionError
        raise InvalidTransitionError("another replay is already active")
    session.replay_active = True
    session.sub_state = SubState.REPLAYING

    tick_interval_ns = 1_000_000_000 // fps
    next_tick_ns = clock.monotonic_ns() + tick_interval_ns
    try:
        for q in trajectory.joint_targets:
            if session.stopped.is_set() or not session.replay_active:
                break
            command_goal_slot.set(
                RobotCommand(q=q.astype(np.float32), t_mono_ns=clock.monotonic_ns()),
                t_mono_ns=clock.monotonic_ns(),
            )
            await clock.sleep_until(next_tick_ns)
            next_tick_ns += tick_interval_ns
    finally:
        session.replay_active = False
        session.sub_state = None


def request_stop(session: Session) -> None:
    """Called by the session lifecycle to break the replay loop."""
    session.replay_active = False
    session.sub_state = None
