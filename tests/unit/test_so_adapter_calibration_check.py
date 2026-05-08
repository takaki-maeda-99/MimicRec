"""SO101Adapter / SOLeaderAdapter must fail-fast when the lerobot calibration
file is missing OR when the motors don't match the file, and the message must
tell the operator both options (place a file vs. run calibration).

Background: lerobot's ``SOFollower.connect(calibrate=False)`` /
``SOLeader.connect(calibrate=False)`` skip the ``is_calibrated`` check
entirely when ``calibrate=False``, so neither a missing calibration file nor
a motor/file mismatch raises during connect. Without these guards the session
enters READY, the frontend transitions to the recording UI, and the operator
only finds out tens of seconds later when reads start failing — at which
point the session ends silently and the operator is bounced back to the
settings screen with no actionable error.

These tests pin the contract:

  * If the calibration file does not exist, ``connect()`` raises
    ``HardwareError`` BEFORE talking to the bus, with a message that
    includes the expected file path AND the calibration command.
  * If the file exists but the motors don't match it, the adapter writes
    the file's values to the motors (the same recovery lerobot does
    interactively when the operator presses ENTER). If that still leaves
    the motors out of sync, raise ``HardwareError`` with a message that
    again surfaces both options.
"""
from __future__ import annotations
import json
from pathlib import Path

import pytest

from mimicrec.errors import HardwareError


class _FakeBus:
    def __init__(self):
        self.write_calibration_called_with = None

    def write_calibration(self, calibration):
        self.write_calibration_called_with = calibration


class _FakeSOFollower:
    """Stand-in for ``lerobot.robots.so_follower.so_follower.SO101Follower``.

    Mirrors only the surface mimicrec touches:
      * ``__init__(config)`` accepts the lerobot config object
      * ``calibration_fpath`` — Path the real Robot.__init__ would set
      * ``calibration`` — dict the real Robot.__init__ would load from disk
      * ``is_calibrated`` — bool property
      * ``bus`` — exposes ``write_calibration`` for the recovery path
      * ``connect(calibrate=...)`` / ``disconnect()`` — no-op flags

    Tests configure these on a per-instance basis via the factory closure.
    """
    def __init__(self, config, *, calibration_fpath: Path,
                 is_calibrated_sequence: list[bool], calibration: dict | None = None):
        self._cfg = config
        self.calibration_fpath = calibration_fpath
        self.calibration = {} if calibration is None else calibration
        self._is_calibrated_sequence = list(is_calibrated_sequence)
        self.bus = _FakeBus()
        self.connect_called = False
        self.disconnect_called = False

    @property
    def is_calibrated(self) -> bool:
        # Pop sequentially so the test can simulate "False then True"
        # (recovery succeeded) vs. "False then False" (recovery failed).
        if self._is_calibrated_sequence:
            return self._is_calibrated_sequence.pop(0)
        return True

    def connect(self, calibrate: bool = True) -> None:
        self.connect_called = True

    def disconnect(self) -> None:
        self.disconnect_called = True


class _FakeSOLeader(_FakeSOFollower):
    """Same shape as the follower fake — leader uses the same lerobot
    Robot/Teleoperator base, so the same surface is enough."""


def _patch_lerobot_follower(monkeypatch, factory):
    monkeypatch.setattr(
        "lerobot.robots.so_follower.so_follower.SO101Follower",
        factory,
    )
    monkeypatch.setattr(
        "lerobot.robots.so_follower.config_so_follower.SOFollowerRobotConfig",
        lambda **kw: kw,
    )


def _patch_lerobot_leader(monkeypatch, factory):
    monkeypatch.setattr(
        "lerobot.teleoperators.so_leader.so_leader.SOLeader",
        factory,
    )
    monkeypatch.setattr(
        "lerobot.teleoperators.so_leader.config_so_leader.SOLeaderTeleopConfig",
        lambda **kw: kw,
    )


# ---------------------------------------------------------------------------
# Missing file → fail-fast with actionable two-option message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_so101_missing_file_raises_with_path_and_command(monkeypatch, tmp_path):
    from mimicrec.adapters import so101 as so101_mod

    missing = tmp_path / "no_such_file.json"
    instances: list[_FakeSOFollower] = []

    def _ctor(config):
        inst = _FakeSOFollower(config, calibration_fpath=missing, is_calibrated_sequence=[])
        instances.append(inst)
        return inst

    _patch_lerobot_follower(monkeypatch, _ctor)
    adapter = so101_mod.SO101Adapter(port="/dev/null", id="missing_calib_test_arm")

    with pytest.raises(HardwareError) as exc_info:
        await adapter.connect()

    msg = str(exc_info.value)
    # Both options must be in the message — operators with an existing
    # file need to know where to place it; operators without one need
    # the calibration command.
    assert str(missing) in msg, "error must include the expected file path"
    assert "calibrate_so101.py" in msg, "error must include the calibration command"
    assert "missing_calib_test_arm" in msg, "command must include the configured id"
    assert "/dev/null" in msg, "command must include the configured port"
    # Bus must not have been touched.
    assert instances[0].connect_called is False


@pytest.mark.asyncio
async def test_so_leader_missing_file_raises_with_path_and_command(monkeypatch, tmp_path):
    from mimicrec.adapters import so_leader as so_leader_mod

    missing = tmp_path / "no_such_leader.json"
    instances: list[_FakeSOLeader] = []

    def _ctor(config):
        inst = _FakeSOLeader(config, calibration_fpath=missing, is_calibrated_sequence=[])
        instances.append(inst)
        return inst

    _patch_lerobot_leader(monkeypatch, _ctor)
    adapter = so_leader_mod.SOLeaderAdapter(port="/dev/null", id="missing_calib_test_leader")

    with pytest.raises(HardwareError) as exc_info:
        await adapter.connect()

    msg = str(exc_info.value)
    assert str(missing) in msg
    assert "calibrate_so101.py" in msg
    assert "missing_calib_test_leader" in msg
    assert instances[0].connect_called is False


# ---------------------------------------------------------------------------
# File exists but motors don't match → auto-recovery via write_calibration
# ---------------------------------------------------------------------------

def _create_fake_calibration_file(tmp_path: Path, name: str) -> Path:
    """Write a placeholder calibration json so .is_file() returns True."""
    p = tmp_path / name
    p.write_text(json.dumps({}))
    return p


@pytest.mark.asyncio
async def test_so101_motors_uncalibrated_recovers_via_write_calibration(monkeypatch, tmp_path):
    """If the file is present but the motors don't have its values applied,
    the adapter writes the file to the motors (the same recovery lerobot
    does interactively) and proceeds. No HardwareError."""
    from mimicrec.adapters import so101 as so101_mod

    fpath = _create_fake_calibration_file(tmp_path, "arm.json")
    loaded_cal = {"shoulder_pan": "stub_value"}
    captured: list[_FakeSOFollower] = []

    def _ctor(config):
        # is_calibrated returns False the first time (motors out of sync),
        # then True (recovery succeeded).
        inst = _FakeSOFollower(
            config,
            calibration_fpath=fpath,
            is_calibrated_sequence=[False, True],
            calibration=loaded_cal,
        )
        captured.append(inst)
        return inst

    _patch_lerobot_follower(monkeypatch, _ctor)
    adapter = so101_mod.SO101Adapter(port="/dev/null", id="arm")

    await adapter.connect()  # must NOT raise

    assert captured[0].connect_called is True
    assert captured[0].bus.write_calibration_called_with == loaded_cal, (
        "adapter must write the loaded calibration to the bus when motors "
        "don't already match — same as pressing ENTER in lerobot's "
        "interactive flow"
    )


@pytest.mark.asyncio
async def test_so101_motors_uncalibrated_after_recovery_raises_actionable(monkeypatch, tmp_path):
    """If the file is present but write_calibration didn't bring the motors
    into sync (e.g. wrong file for these motors), raise HardwareError with
    the path of the file AND the calibration command."""
    from mimicrec.adapters import so101 as so101_mod

    fpath = _create_fake_calibration_file(tmp_path, "arm.json")
    captured: list[_FakeSOFollower] = []

    def _ctor(config):
        inst = _FakeSOFollower(
            config,
            calibration_fpath=fpath,
            # Stays False after recovery attempt.
            is_calibrated_sequence=[False, False],
            calibration={"shoulder_pan": "stub"},
        )
        captured.append(inst)
        return inst

    _patch_lerobot_follower(monkeypatch, _ctor)
    adapter = so101_mod.SO101Adapter(port="/dev/null", id="arm")

    with pytest.raises(HardwareError) as exc_info:
        await adapter.connect()

    msg = str(exc_info.value)
    assert str(fpath) in msg
    assert "calibrate_so101.py" in msg
    # The adapter should have disconnected the bus before raising — we
    # don't want a session start failure to leave the serial port held
    # open from a half-initialized adapter.
    assert captured[0].disconnect_called is True


@pytest.mark.asyncio
async def test_so_leader_motors_uncalibrated_recovers_via_write_calibration(monkeypatch, tmp_path):
    from mimicrec.adapters import so_leader as so_leader_mod

    fpath = _create_fake_calibration_file(tmp_path, "leader.json")
    loaded_cal = {"shoulder_pan": "stub"}
    captured: list[_FakeSOLeader] = []

    def _ctor(config):
        inst = _FakeSOLeader(
            config,
            calibration_fpath=fpath,
            is_calibrated_sequence=[False, True],
            calibration=loaded_cal,
        )
        captured.append(inst)
        return inst

    _patch_lerobot_leader(monkeypatch, _ctor)
    adapter = so_leader_mod.SOLeaderAdapter(port="/dev/null", id="leader")

    await adapter.connect()
    assert captured[0].bus.write_calibration_called_with == loaded_cal


@pytest.mark.asyncio
async def test_so_leader_motors_uncalibrated_after_recovery_raises_actionable(monkeypatch, tmp_path):
    from mimicrec.adapters import so_leader as so_leader_mod

    fpath = _create_fake_calibration_file(tmp_path, "leader.json")
    captured: list[_FakeSOLeader] = []

    def _ctor(config):
        inst = _FakeSOLeader(
            config,
            calibration_fpath=fpath,
            is_calibrated_sequence=[False, False],
            calibration={"shoulder_pan": "stub"},
        )
        captured.append(inst)
        return inst

    _patch_lerobot_leader(monkeypatch, _ctor)
    adapter = so_leader_mod.SOLeaderAdapter(port="/dev/null", id="leader")

    with pytest.raises(HardwareError) as exc_info:
        await adapter.connect()

    msg = str(exc_info.value)
    assert str(fpath) in msg
    assert "calibrate_so101.py" in msg
    assert captured[0].disconnect_called is True
