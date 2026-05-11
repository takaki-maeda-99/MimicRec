"""GripperBinarize: snap raw gripper targets to grip-saturating values.

Three cases on the recorded track:
  1. v <= threshold                    → open_value
  2. v > threshold AND |Δ| < dwell    → closed_value (holding)
  3. v > threshold AND moving         → passthrough (mid-close ramp)

Replay calls ``apply_track`` to transform the whole gripper track in one
go so the dwell check has frame-to-frame state.
"""
from mimicrec.session.replay import GripperBinarize


def _bin(dwell: float = 0.1) -> GripperBinarize:
    return GripperBinarize(
        threshold=-4.0,
        open_value=-5.7,
        closed_value=-2.0,
        dwell_delta=dwell,
    )


def test_apply_is_pure_threshold():
    b = _bin()
    assert b.apply(-2.5) == -2.0
    assert b.apply(-3.99) == -2.0
    assert b.apply(-4.0) == -5.7
    assert b.apply(-5.6) == -5.7


def test_track_below_threshold_snaps_open():
    b = _bin()
    track = [-5.5, -5.49, -5.5, -5.6]
    assert b.apply_track(track) == [-5.7, -5.7, -5.7, -5.7]


def test_track_above_threshold_and_stable_snaps_closed():
    b = _bin()
    # Operator holding an object — value sits above threshold without
    # moving more than dwell_delta frame-to-frame.
    track = [-3.5, -3.5, -3.5, -3.5]
    assert b.apply_track(track) == [-2.0, -2.0, -2.0, -2.0]


def test_track_above_threshold_and_moving_passes_through():
    b = _bin()
    # Operator closing the gripper — values cross the -4.0 threshold
    # while still moving. Below-threshold frames snap to open; above-
    # threshold frames passthrough until the hand settles, then snap
    # to closed once |Δ| < dwell.
    track = [-5.0, -4.5, -3.5, -2.8, -2.5, -2.5]
    out = b.apply_track(track)
    # Frames 0..1: below threshold → open snap.
    assert out[0] == -5.7
    assert out[1] == -5.7
    # Frames 2..4: above threshold but moving by ≥ 0.3 each → passthrough.
    assert out[2] == -3.5
    assert out[3] == -2.8
    assert out[4] == -2.5
    # Frame 5: above threshold, |Δ|=0 < dwell → snap to closed.
    assert out[5] == -2.0


def test_track_dwell_zero_disables_hold_detection():
    b = _bin(dwell=0.0)
    # With dwell off, every above-threshold frame snaps closed,
    # every below-threshold frame snaps open — pure binarize.
    track = [-5.5, -3.5, -3.5, -2.5, -5.0]
    assert b.apply_track(track) == [-5.7, -2.0, -2.0, -2.0, -5.7]


def test_track_first_frame_above_threshold_snaps_closed():
    # Edge case: recording starts mid-grip. First frame has prev=v
    # so |Δ|=0 < dwell, treated as stable.
    b = _bin()
    track = [-3.0]
    assert b.apply_track(track) == [-2.0]


def test_track_empty_passthrough():
    b = _bin()
    assert b.apply_track([]) == []
