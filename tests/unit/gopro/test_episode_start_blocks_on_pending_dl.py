"""Bug B: episode_start must refuse to start while GoPro DL is in flight.

Rationale: starting a new shutter while DLWorker is still downloading the
previous episode's mp4 over the same USB-CDC-NCM bus produces sporadic
download/ffmpeg failures (the original symptom that motivated the
preview-toggle work). Block the transition until the pending count
reaches zero — auto-cycle handles this naturally by polling
/api/session/gopro_pending before retrying.
"""
from __future__ import annotations

import pytest

from mimicrec.errors import InvalidTransitionError
from mimicrec.session.lifecycle import assert_can_start_episode
from mimicrec.session.state import Session
from mimicrec.types import SessionMode


class _FakeRegistry:
    def __init__(self, pending_count: int) -> None:
        self.pending_count = pending_count


def test_assert_can_start_episode_no_registry_passes():
    s = Session(mode=SessionMode.TELEOP)
    assert_can_start_episode(s, gopro_registry=None)  # must not raise


def test_assert_can_start_episode_pending_zero_passes():
    s = Session(mode=SessionMode.TELEOP)
    assert_can_start_episode(s, gopro_registry=_FakeRegistry(pending_count=0))


def test_assert_can_start_episode_pending_positive_raises():
    s = Session(mode=SessionMode.TELEOP)
    with pytest.raises(InvalidTransitionError, match="GoPro"):
        assert_can_start_episode(s, gopro_registry=_FakeRegistry(pending_count=2))


def test_assert_can_start_episode_default_registry_argument_is_none():
    """Backward compat: existing callers passing only Session must still work."""
    s = Session(mode=SessionMode.TELEOP)
    assert_can_start_episode(s)  # gopro_registry defaults to None
