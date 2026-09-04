import numpy as np
import pytest

from mimicrec.motion.se3 import SE3Delta
from mimicrec.motion.types import MotionStep
from mimicrec.session.motion_replay import MotionReplayTrajectory, run_motion_replay
from mimicrec.session.state import Session
from mimicrec.types import SessionMode, SessionState


class _Runtime:
    def __init__(self):
        self.paused = False
        self.injected = []

    def pause_inputs(self):
        self.paused = True

    def resume_inputs(self):
        self.paused = False

    def inject_step(self, group, step):
        assert self.paused
        self.injected.append((group, step))


@pytest.mark.asyncio
async def test_motion_replay_reinjects_se3_tokens_and_restores_live_inputs():
    runtime = _Runtime()
    session = Session(mode=SessionMode.TELEOP, state=SessionState.READY)
    trajectory = MotionReplayTrajectory(
        frames=[{
            "hand": MotionStep(
                SE3Delta(np.array([0.01, 0, 0, 0, 0, 0]), duration_sec=0.001),
                auxiliary={"gripper": 0.2},
            )
        }],
        fps=1000,
    )

    await run_motion_replay(session, runtime, trajectory)

    assert len(runtime.injected) == 1
    assert runtime.injected[0][0] == "hand"
    assert runtime.injected[0][1].delta.tangent[0] == pytest.approx(0.01)
    assert runtime.injected[0][1].auxiliary["gripper"] == pytest.approx(0.2)
    assert runtime.paused is False
    assert session.replay_active is False
