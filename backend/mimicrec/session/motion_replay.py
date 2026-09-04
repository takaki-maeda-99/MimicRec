from __future__ import annotations

from dataclasses import dataclass
import asyncio
import time

from mimicrec.motion.types import MotionStep
from mimicrec.types import SessionState, SubState


@dataclass
class MotionReplayTrajectory:
    frames: list[dict[str, MotionStep]]
    fps: int


async def run_motion_replay(
    session,
    runtime,
    trajectory: MotionReplayTrajectory,
    *,
    speed: float = 1.0,
) -> None:
    if session.state != SessionState.READY:
        raise RuntimeError("motion replay requires a READY session")
    if session.replay_active:
        raise RuntimeError("another replay is already active")
    if speed <= 0.0:
        raise ValueError("replay speed must be > 0")
    session.replay_active = True
    session.sub_state = SubState.REPLAYING
    runtime.pause_inputs()
    try:
        fallback_duration = 1.0 / trajectory.fps
        for frame in trajectory.frames:
            if not session.replay_active or session.stopped.is_set():
                break
            now = time.monotonic_ns()
            durations = []
            for group_name, recorded in frame.items():
                runtime.inject_step(
                    group_name,
                    MotionStep(
                        delta=recorded.delta,
                        auxiliary=recorded.auxiliary,
                        t_mono_ns=now,
                    ),
                )
                durations.append(recorded.delta.duration_sec)
            duration = max(durations) if durations else fallback_duration
            await asyncio.sleep(duration / speed)
    finally:
        runtime.resume_inputs()
        session.replay_active = False
        session.sub_state = None
