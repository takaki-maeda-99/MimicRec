from __future__ import annotations
import asyncio
from dataclasses import dataclass

import numpy as np

from mimicrec.errors import ReplaySafetyError
from mimicrec.session.replay_safety import ReplaySafetyConfig, ReplayWatchdog
from mimicrec.session.state import Session
from mimicrec.types import RobotCommand, SessionState, SubState
from mimicrec.util.clock import Clock
from mimicrec.util.latest_value import LatestValue


@dataclass
class ReplayTrajectory:
    """Joint-target sequence + the rate at which it was captured.

    `fps` is the trajectory's native rate. Replay should iterate at that rate
    so playback tempo matches the recording. If None, falls back to the
    session's fps.
    """
    joint_targets: np.ndarray   # shape (T, dof)
    fps: int | None = None


async def run_replay(
    session: Session,
    trajectory: ReplayTrajectory,
    fps: int,
    command_goal_slot: LatestValue[RobotCommand],
    clock: Clock,
    measured_state_slot: "LatestValue | None" = None,
    safety: "ReplaySafetyConfig | None" = None,
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

    # Iterate at the trajectory's native rate when known — keeps playback
    # tempo right even if the active session was started at a different fps.
    effective_fps = trajectory.fps or fps
    tick_interval_ns = 1_000_000_000 // effective_fps
    next_tick_ns = clock.monotonic_ns() + tick_interval_ns

    # Sync the watchdog's dt_sec with the trajectory's native fps so vel/accel
    # checks compute with the correct timebase (otherwise a 15Hz recording
    # replayed in a 30Hz-configured session would report 2x velocity).
    if safety is not None and trajectory.fps is not None:
        from dataclasses import replace as _replace
        safety = _replace(safety, dt_sec=1.0 / trajectory.fps)
    wd = ReplayWatchdog(safety) if safety is not None else None
    prev_q: np.ndarray | None = None
    prev_prev_q: np.ndarray | None = None

    # Build the playback sequence: an initial ramp from the current measured
    # pose to trajectory[0] (so the watchdog doesn't trip on tick 0 because
    # the arm happens to be away from the recorded start), then the recorded
    # trajectory. Without this ramp, replay only works when the arm starts
    # already at trajectory[0] — usually false.
    targets = list(trajectory.joint_targets)
    if (
        safety is not None
        and measured_state_slot is not None
        and len(targets) > 0
        and safety.ramp_duration_sec > 0
    ):
        m0 = measured_state_slot.peek()
        if m0 is not None:
            start = m0.value.joint_pos.astype(np.float32)
            goal = np.asarray(targets[0], dtype=np.float32)
            n_ramp = max(1, int(safety.ramp_duration_sec * effective_fps))
            ramp = [
                start + (goal - start) * (i / n_ramp)
                for i in range(1, n_ramp + 1)
            ]
            targets = ramp + targets

    try:
        for q in targets:
            if session.stopped.is_set() or not session.replay_active:
                break
            target = q.astype(np.float32)

            if wd is not None:
                now_ns = clock.monotonic_ns()
                try:
                    wd.assert_fresh(now_ns)
                    measured = None
                    if measured_state_slot is not None:
                        m = measured_state_slot.peek()
                        measured = m.value.joint_pos if m is not None else target
                    wd.check(
                        target=target,
                        prev_target=prev_q,
                        prev_prev_target=prev_prev_q,
                        measured=measured if measured is not None else target,
                    )
                except ReplaySafetyError as e:
                    if measured_state_slot is not None:
                        m = measured_state_slot.peek()
                        if m is not None:
                            now2 = clock.monotonic_ns()
                            command_goal_slot.set(
                                RobotCommand(q=m.value.joint_pos.copy(), t_mono_ns=now2),
                                t_mono_ns=now2,
                            )
                    if error_bus is not None:
                        await error_bus.publish(e)
                    raise

            now3 = clock.monotonic_ns()
            command_goal_slot.set(RobotCommand(q=target, t_mono_ns=now3), t_mono_ns=now3)
            if wd is not None:
                wd.note_command_sent(now3)
            prev_prev_q, prev_q = prev_q, target
            await clock.sleep_until(next_tick_ns)
            next_tick_ns += tick_interval_ns
    finally:
        session.replay_active = False
        session.sub_state = None


def request_stop(session: Session) -> None:
    """Called by the session lifecycle to break the replay loop."""
    session.replay_active = False
    session.sub_state = None
