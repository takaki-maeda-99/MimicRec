from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass

import numpy as np

from mimicrec.errors import ReplaySafetyError
from mimicrec.session.replay_safety import ReplaySafetyConfig, ReplayWatchdog
from mimicrec.session.state import Session
from mimicrec.types import RobotCommand, SessionState, SubState
from mimicrec.util.clock import Clock
from mimicrec.util.latest_value import LatestValue

logger = logging.getLogger(__name__)


@dataclass
class ReplayTrajectory:
    """Joint-target sequence + the rate at which it was captured.

    `fps` is the trajectory's native rate. Replay should iterate at that rate
    so playback tempo matches the recording. If None, falls back to the
    session's fps.

    `gripper_targets` is the per-frame gripper position (radians) when the
    recording included one, otherwise None — the dispatcher only forwards
    a gripper command when both the trajectory and the adapter support it.
    """
    joint_targets: np.ndarray   # shape (T, dof)
    fps: int | None = None
    gripper_targets: np.ndarray | None = None  # shape (T,)


async def run_replay(
    session: Session,
    trajectory: ReplayTrajectory,
    fps: int,
    command_goal_slot: LatestValue[RobotCommand],
    clock: Clock,
    measured_state_slot: "LatestValue | None" = None,
    safety: "ReplaySafetyConfig | None" = None,
    error_bus: "object | None" = None,
    interp_steps: int = 5,
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

    logger.warning(
        "[replay] START: traj_fps=%s session_fps=%s effective_fps=%s n_frames=%d safety=%s interp_steps=%d",
        trajectory.fps, fps, effective_fps, len(trajectory.joint_targets),
        "yes" if safety is not None else "no", max(1, int(interp_steps)),
    )

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
    raw_targets = trajectory.joint_targets
    # Trajectory is now arm-only; gripper is carried separately on
    # ``trajectory.gripper_targets`` (None when the recording had none).
    # The dataset reader handles legacy recordings where gripper was the
    # 7th column of action.joint_pos by splitting them on read.
    targets = list(raw_targets)
    grip_targets: list[float] | None = (
        list(trajectory.gripper_targets)
        if trajectory.gripper_targets is not None
        else None
    )
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
            # Pad the gripper track with the recorded first value during
            # the ramp so the gripper holds its initial pose while the
            # arm moves into the start frame.
            if grip_targets is not None:
                grip_targets = [float(grip_targets[0])] * n_ramp + grip_targets

    n_ramp_used = len(targets) - len(trajectory.joint_targets)
    logger.warning(
        "[replay] ramp=%d frames + traj=%d frames = %d total (~%.1fs at %dHz)  gripper=%s",
        n_ramp_used, len(trajectory.joint_targets), len(targets),
        len(targets) / effective_fps, effective_fps,
        "yes" if grip_targets is not None else "no",
    )

    # Substep count for linear interpolation. target_i is sent at the
    # start of its tick (matching legacy timing, so playback tempo is
    # unchanged when interp_steps varies); within the tick, n_sub-1
    # interpolated setpoints ramp toward target_{i+1}. The final substep
    # (= target_{i+1}) is delivered as the next iteration's primary send,
    # so we don't emit it here. interp_steps=1 reproduces legacy behavior.
    n_sub = max(1, int(interp_steps))
    substep_interval_ns = tick_interval_ns // n_sub

    sent_count = 0
    try:
        for tick_i, q in enumerate(targets):
            if session.stopped.is_set() or not session.replay_active:
                logger.warning("[replay] LOOP EXIT at tick %d/%d (stopped=%s replay_active=%s)",
                               tick_i, len(targets),
                               session.stopped.is_set(), session.replay_active)
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
                    logger.warning(
                        "[replay] SAFETY TRIP at tick %d/%d: %s",
                        tick_i, len(targets), e,
                    )
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

            grip = (
                float(grip_targets[tick_i])
                if grip_targets is not None and tick_i < len(grip_targets)
                else None
            )

            # Send target_i at the start of its tick — same time the
            # legacy single-send code fired, so playback tempo is preserved.
            now3 = clock.monotonic_ns()
            command_goal_slot.set(
                RobotCommand(q=target, gripper=grip, t_mono_ns=now3),
                t_mono_ns=now3,
            )
            if wd is not None:
                wd.note_command_sent(now3)
            sent_count += 1

            # Within this tick, ramp linearly from target_i toward
            # target_{i+1} so the controller sees evenly spaced setpoints
            # rather than a step. Substeps s=1..n_sub-1 fire at
            # base_ns + s*dt/n_sub; s=n_sub is intentionally skipped — the
            # next iteration's primary send delivers target_{i+1} exactly
            # at t_{i+1}. No substeps after the final recorded frame.
            # Note: substeps reach (n_sub-1)/n_sub of the way to target_{i+1}
            # before that target is safety-checked at the next iteration.
            if n_sub > 1 and tick_i + 1 < len(targets):
                next_target = targets[tick_i + 1].astype(np.float32)
                next_grip = (
                    float(grip_targets[tick_i + 1])
                    if grip_targets is not None
                    and tick_i + 1 < len(grip_targets)
                    else None
                )
                base_ns = next_tick_ns - tick_interval_ns
                for s in range(1, n_sub):
                    alpha = s / n_sub
                    sub_q = (
                        target + (next_target - target) * alpha
                    ).astype(np.float32)
                    if grip is None or next_grip is None:
                        sub_grip = grip if grip is not None else next_grip
                    else:
                        sub_grip = float(grip + (next_grip - grip) * alpha)
                    await clock.sleep_until(base_ns + s * substep_interval_ns)
                    now_sub = clock.monotonic_ns()
                    command_goal_slot.set(
                        RobotCommand(q=sub_q, gripper=sub_grip, t_mono_ns=now_sub),
                        t_mono_ns=now_sub,
                    )
                    if wd is not None:
                        wd.note_command_sent(now_sub)

            prev_prev_q, prev_q = prev_q, target
            await clock.sleep_until(next_tick_ns)
            next_tick_ns += tick_interval_ns
    except Exception as e:
        logger.exception("[replay] EXCEPTION at tick (sent=%d): %s", sent_count, e)
        raise
    finally:
        logger.warning(
            "[replay] FINISH: sent=%d/%d frames",
            sent_count, len(targets),
        )
        session.replay_active = False
        session.sub_state = None


def request_stop(session: Session) -> None:
    """Called by the session lifecycle to break the replay loop."""
    session.replay_active = False
    session.sub_state = None
