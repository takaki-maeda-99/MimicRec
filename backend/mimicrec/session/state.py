from __future__ import annotations
import asyncio
from dataclasses import dataclass, field

from mimicrec.types import SessionMode, SessionState, SubState


@dataclass
class Session:
    mode: SessionMode
    state: SessionState = SessionState.READY
    sub_state: SubState | None = None
    replay_active: bool = False
    stopped: asyncio.Event = field(default_factory=asyncio.Event)
