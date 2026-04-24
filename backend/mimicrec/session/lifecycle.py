from __future__ import annotations
from dataclasses import dataclass

from mimicrec.adapters.robot import RobotAdapter, RobotMode
from mimicrec.errors import HandTeachNotSupportedError, InvalidTransitionError
from mimicrec.session.state import Session
from mimicrec.types import SessionMode, SessionState


@dataclass
class StartSessionRequestDomain:
    """Plan-A internal request — Plan B maps HTTP bodies to this."""
    robot: RobotAdapter
    mode: SessionMode


def precheck_start(req: StartSessionRequestDomain) -> None:
    if req.mode == SessionMode.HAND_TEACH and not req.robot.supports_mode(RobotMode.GRAVITY_COMP):
        raise HandTeachNotSupportedError(
            f"robot {req.robot.name!r} does not support hand-teach "
            f"(GRAVITY_COMP). Start a TELEOP-mode session instead."
        )


def assert_can_start_episode(session: Session) -> None:
    if session.state != SessionState.READY:
        raise InvalidTransitionError(
            f"episode/start requires READY, got {session.state}"
        )
    if session.replay_active:
        raise InvalidTransitionError("episode/start blocked while replay is active")
