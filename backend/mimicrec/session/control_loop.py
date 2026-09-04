from __future__ import annotations
from typing import Callable

from mimicrec.mappers.base import TeleopMapper
from mimicrec.session.state import Session
from mimicrec.types import (
    RobotCommand,
    RobotState,
    SampleBundle,
    SessionState,
    TeleopAction,
)
from mimicrec.util.clock import Clock
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics


EnqueueFn = Callable[[SampleBundle], None]


async def run_teleop_control_loop(
    session: Session,
    fps: int,
    robot_state_slot: LatestValue[RobotState],
    teleop_slot: LatestValue[TeleopAction],
    camera_slots: dict[str, LatestValue[object]],
    command_goal_slot: LatestValue[RobotCommand],
    mapper: TeleopMapper,
    enqueue: EnqueueFn,
    clock: Clock,
    metrics: Metrics,
    control_fps: int | None = None,
) -> None:
    # Cartesian keyboard control benefits from a higher command rate than the
    # dataset/camera FPS. Recording remains at ``fps`` while mapping and
    # dispatch can run at ``control_fps``.
    tick_interval_ns = 1_000_000_000 // (control_fps or fps)
    record_interval_ns = 1_000_000_000 // fps
    next_tick_ns = clock.monotonic_ns() + tick_interval_ns
    next_record_ns = clock.monotonic_ns()
    was_recording = False

    while not session.stopped.is_set():
        tick_t = clock.monotonic_ns()

        if tick_t >= next_tick_ns + tick_interval_ns:
            skipped = (tick_t - next_tick_ns) // tick_interval_ns
            metrics.inc("ticks_skipped", int(skipped))
            next_tick_ns = tick_t + tick_interval_ns

        phase = session.state
        if session.home_active:
            await clock.sleep_until(next_tick_ns)
            next_tick_ns += tick_interval_ns
            continue
        if phase == SessionState.REVIEW:
            was_recording = False
            await clock.sleep_until(next_tick_ns)
            next_tick_ns += tick_interval_ns
            continue

        state = robot_state_slot.peek()
        action = teleop_slot.peek()
        if state is None or action is None:
            await clock.sleep_until(next_tick_ns)
            next_tick_ns += tick_interval_ns
            continue

        stale_threshold_ns = 3 * tick_interval_ns
        if tick_t - state.t_mono_ns > stale_threshold_ns:
            metrics.inc("stale_sample_count")
        if tick_t - action.t_mono_ns > stale_threshold_ns:
            metrics.inc("stale_sample_count")

        # Skip if teleop hasn't produced a valid action yet (e.g. WebTeleoperator before browser connects)
        if (
            action.value.target_joint_pos is None
            and action.value.ee_delta is None
            and action.value.ee_pose_offset is None
            and action.value.ee_pose_active is None
        ):
            await clock.sleep_until(next_tick_ns)
            next_tick_ns += tick_interval_ns
            continue

        command = mapper.map(action.value, state.value)
        command.t_mono_ns = clock.monotonic_ns()
        if hasattr(mapper, "telemetry"):
            for name, value in mapper.telemetry(state.value, command).items():
                metrics.set_gauge(name, float(value))

        if not session.replay_active:
            command_goal_slot.set(command, t_mono_ns=command.t_mono_ns)

        if phase == SessionState.RECORDING:
            if not was_recording:
                next_record_ns = tick_t
                was_recording = True
            if tick_t >= next_record_ns:
                frames = {name: slot.peek() for name, slot in camera_slots.items()}
                enqueue(
                    SampleBundle(
                        tick_t_mono_ns=tick_t,
                        state=state,
                        action=command,
                        frames=frames,
                    )
                )
                next_record_ns += record_interval_ns
                if next_record_ns <= tick_t:
                    next_record_ns = tick_t + record_interval_ns
        else:
            was_recording = False

        await clock.sleep_until(next_tick_ns)
        next_tick_ns += tick_interval_ns


async def run_handteach_control_loop(
    session: Session,
    fps: int,
    robot_adapter,
    robot_state_slot: LatestValue[RobotState],
    camera_slots: dict[str, LatestValue[object]],
    enqueue: EnqueueFn,
    clock: Clock,
    metrics: Metrics,
) -> None:
    # Mode is owned by SessionManager: POSITION at idle hold, then
    # GRAVITY_COMP on episode_start. Don't override here — doing so
    # used to clobber the post-idle POSITION hold on session start.
    tick_interval_ns = 1_000_000_000 // fps
    next_tick_ns = clock.monotonic_ns() + tick_interval_ns

    while not session.stopped.is_set():
        tick_t = clock.monotonic_ns()

        if tick_t >= next_tick_ns + tick_interval_ns:
            skipped = (tick_t - next_tick_ns) // tick_interval_ns
            metrics.inc("ticks_skipped", int(skipped))
            next_tick_ns = tick_t + tick_interval_ns

        phase = session.state
        if phase == SessionState.REVIEW:
            await clock.sleep_until(next_tick_ns)
            next_tick_ns += tick_interval_ns
            continue

        state = robot_state_slot.peek()
        if state is None:
            await clock.sleep_until(next_tick_ns)
            next_tick_ns += tick_interval_ns
            continue

        stale_threshold_ns = 3 * tick_interval_ns
        if tick_t - state.t_mono_ns > stale_threshold_ns:
            metrics.inc("stale_sample_count")

        if phase == SessionState.RECORDING:
            # Hand-teach has no commanded action — synthesize one from the
            # measured state. Gripper goes in its own field so adapters
            # that don't support gripper commands ignore it cleanly, and
            # the parquet writer pulls it from action.gripper rather than
            # depending on q's column count.
            synthesized = RobotCommand(
                q=state.value.joint_pos.copy(),
                gripper=state.value.gripper_pos,
                t_mono_ns=tick_t,
            )
            frames = {name: slot.peek() for name, slot in camera_slots.items()}
            enqueue(SampleBundle(
                tick_t_mono_ns=tick_t,
                state=state,
                action=synthesized,
                frames=frames,
            ))

        await clock.sleep_until(next_tick_ns)
        next_tick_ns += tick_interval_ns
