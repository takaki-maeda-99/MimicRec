from __future__ import annotations
import asyncio
from typing import Callable

from mimicrec.inference.chunk_buffer import ChunkBuffer
from mimicrec.inference.safety import InferenceSafety
from mimicrec.session.state import Session
from mimicrec.types import (
    RobotState, RobotCommand, SessionState, Stamped, SampleBundle,
)
from mimicrec.util.clock import Clock
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics


async def run_inference_control_loop(
    session: Session,
    fps: int,
    robot_state_slot: LatestValue[RobotState],
    camera_slots: dict[str, LatestValue[object]],
    chunk_buffer: ChunkBuffer,
    safety: InferenceSafety,
    command_goal_slot: LatestValue[RobotCommand],
    enqueue: Callable[[SampleBundle], None],
    clock: Clock,
    metrics: Metrics,
) -> None:
    tick_interval_ns = 1_000_000_000 // fps
    next_tick_ns = clock.monotonic_ns() + tick_interval_ns

    while not session.stopped.is_set():
        tick_t = clock.monotonic_ns()

        if tick_t >= next_tick_ns + tick_interval_ns:
            skipped = (tick_t - next_tick_ns) // tick_interval_ns
            metrics.inc("ticks_skipped", int(skipped))
            next_tick_ns = tick_t + tick_interval_ns

        phase = session.state

        state = robot_state_slot.peek()
        if state is None:
            await clock.sleep_until(next_tick_ns)
            next_tick_ns += tick_interval_ns
            continue

        step = chunk_buffer.pop_next() if phase != SessionState.REVIEW else None
        if step is not None and chunk_buffer.depth() == 0:
            metrics.inc("chunks_consumed")
        command = safety.filter(step, state.value.joint_pos[:safety.joint_min.shape[0]], tick_t)

        if not session.replay_active:
            command_goal_slot.set(command, t_mono_ns=command.t_mono_ns)

        if phase == SessionState.RECORDING:
            frames = {name: slot.peek() for name, slot in camera_slots.items()}
            enqueue(SampleBundle(
                tick_t_mono_ns=tick_t, state=state, action=command, frames=frames,
            ))

        await clock.sleep_until(next_tick_ns)
        next_tick_ns += tick_interval_ns
