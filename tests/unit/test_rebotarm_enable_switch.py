"""Unit tests for the enable-switch debouncer and factory.

The real ``EnableSwitch`` class touches libgpiod and runs a background
poll thread — neither is easy to exercise in CI. The debounce semantics
are factored out into ``DebouncedLatch`` (pure Python, no I/O) so they
can be driven with synthetic timestamps; the factory has a no-op
fallback path for missing gpiod / bad chips that we cover with a
broken-config probe.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from rebotarm_daemon.config import EnableSwitchParams
from rebotarm_daemon.enable_switch import DebouncedLatch, make_enable_switch


# ---------------------------------------------------------------------------
# DebouncedLatch
# ---------------------------------------------------------------------------


def test_latch_holds_initial_state_with_no_updates():
    latch = DebouncedLatch(initial=True, debounce_s=0.02)
    assert latch.state is True


def test_latch_holds_initial_state_when_raw_matches():
    """Stream of observations matching the current state must not flip."""
    latch = DebouncedLatch(initial=False, debounce_s=0.02)
    for t in [0.0, 0.01, 0.05, 0.1, 1.0]:
        latch.update(False, t)
    assert latch.state is False


def test_latch_flips_after_debounce_elapses():
    """A new raw value must persist for >= debounce_s before the latch flips.

    Timestamps stay clear of the exact boundary so float subtraction
    doesn't influence the result — the contract under test is the
    relative ordering "early → no flip, late → flip", not the precise
    boundary behaviour at the float-rounding edge.
    """
    latch = DebouncedLatch(initial=False, debounce_s=0.020)
    # First sighting of True at t=0.0 — starts the debounce window.
    latch.update(True, 0.000)
    assert latch.state is False, "too early; window has not elapsed"
    # Still inside the 20 ms window.
    latch.update(True, 0.010)
    assert latch.state is False
    # Comfortably past the window — must flip.
    latch.update(True, 0.025)
    assert latch.state is True


def test_latch_chatter_resets_countdown():
    """Bouncing between True/False during the debounce window must NOT flip.

    Real switches chatter on contact. The debouncer's whole job is to
    swallow that and only commit a transition once the raw signal has
    settled — this test fails if the implementation forgets to reset
    its candidate timestamp on every change. Timestamps are chosen well
    clear of the 20 ms boundary so float rounding doesn't influence the
    result.
    """
    latch = DebouncedLatch(initial=False, debounce_s=0.020)
    latch.update(True, 0.000)
    latch.update(False, 0.005)  # bounce back
    latch.update(True, 0.010)   # second rising edge — resets the window
    latch.update(True, 0.025)   # 15 ms after the second edge — still too early
    assert latch.state is False
    latch.update(True, 0.035)   # 25 ms after the second edge — past debounce
    assert latch.state is True


def test_latch_flips_back_after_release():
    """Round-trip: lock then unlock, both gated by debounce."""
    latch = DebouncedLatch(initial=False, debounce_s=0.010)
    latch.update(True, 0.000)
    latch.update(True, 0.015)   # comfortably past the 10 ms window
    assert latch.state is True
    # Releasing the switch starts a new debounce window for the falling edge.
    latch.update(False, 0.020)
    assert latch.state is True, "falling edge inside window must not flip yet"
    latch.update(False, 0.035)  # 15 ms after the falling edge
    assert latch.state is False


def test_latch_zero_debounce_flips_on_next_consistent_observation():
    """``debounce_s == 0`` reduces to ``flip as soon as a new value is seen
    twice in a row``. Useful as a degenerate edge case.
    """
    latch = DebouncedLatch(initial=False, debounce_s=0.0)
    latch.update(True, 0.0)
    # Even at t==last_change_t the elapsed time is zero, which satisfies
    # ``>= 0`` and lets the latch flip on the very next consistent update.
    latch.update(True, 0.0)
    assert latch.state is True


# ---------------------------------------------------------------------------
# make_enable_switch (factory fallback paths)
# ---------------------------------------------------------------------------


def test_make_enable_switch_returns_none_when_disabled():
    """``params is None`` (YAML section omitted) must be a no-op."""
    assert make_enable_switch(None) is None


def test_make_enable_switch_returns_none_on_bad_chip(tmp_path):
    """An unopenable chip must not crash the daemon — just disable the switch.

    Hits the broad ``except Exception`` branch in the factory. This is
    the path that protects dev machines without GPIO hardware.
    """
    params = EnableSwitchParams(
        chip="does_not_exist_chip_xyz",
        line=17,
        bias="pull_up",
        active_state="high",
    )
    assert make_enable_switch(params) is None
