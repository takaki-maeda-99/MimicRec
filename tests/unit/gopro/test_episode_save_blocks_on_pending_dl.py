"""Bug B': episode_save must refuse while GoPro DL is still in flight.

Rationale: allowing success/failure to be committed before the mp4 has
landed in the dataset means the parquet metadata records an episode
whose video may never arrive (DL timeout, ffmpeg failure on a truncated
file). Blocking at this transition makes save atomic — by the time
it returns, the GoPro file is guaranteed to be either in the dataset or
permanently failed (sidecar cleaned up by the worker, pending == 0).

This is the primary gate; ``assert_can_start_episode`` retains its own
pending-count check as defense-in-depth (start gate covers any
hypothetical state where a sidecar appears between save and the next
start).

Discard is intentionally NOT gated — operators must always be able to
throw away a bad take fast.
"""
from __future__ import annotations

import pytest

from mimicrec.errors import InvalidTransitionError
from mimicrec.session.lifecycle import assert_can_save_episode
from mimicrec.session.state import Session
from mimicrec.types import SessionMode, SessionState


class _FakeRegistry:
    def __init__(self, pending_count: int) -> None:
        # ``pending_count`` is the legacy "all sidecars" metric; the
        # gate reads ``dl_in_flight_count`` which excludes already-
        # staged sidecars. Tests model the simple case where both
        # are equal (no staged sidecars present).
        self.pending_count = pending_count
        self.dl_in_flight_count = pending_count


def _review_session() -> Session:
    s = Session(mode=SessionMode.TELEOP)
    s.state = SessionState.REVIEW
    return s


def test_save_no_registry_passes():
    assert_can_save_episode(_review_session(), gopro_registry=None)


def test_save_pending_zero_passes():
    assert_can_save_episode(_review_session(), gopro_registry=_FakeRegistry(pending_count=0))


def test_save_pending_positive_raises():
    with pytest.raises(InvalidTransitionError, match="transferring"):
        assert_can_save_episode(_review_session(), gopro_registry=_FakeRegistry(pending_count=3))


def test_save_wrong_state_raises():
    s = Session(mode=SessionMode.TELEOP)
    s.state = SessionState.READY  # not REVIEW
    with pytest.raises(InvalidTransitionError, match="REVIEW"):
        assert_can_save_episode(s, gopro_registry=_FakeRegistry(pending_count=0))


def test_save_default_registry_argument_is_none():
    """Backward compat: callers passing only Session continue to work."""
    assert_can_save_episode(_review_session())
