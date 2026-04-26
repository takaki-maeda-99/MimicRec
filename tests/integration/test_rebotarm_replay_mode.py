"""Regression test: send_command must require POSITION mode on the daemon.

The bug this guards against: replay would feed targets into the daemon while
it sat in MODE_GRAVITY_COMP (the default). The daemon's control loop ignores
position targets in gravity-comp mode, so commands silently no-op'd. Both
the real and mock daemon now reject CMD_SEND_COMMAND with a clear error
when not in POSITION mode, and the lifecycle's replay_start flips the mode
explicitly before issuing commands.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from mimicrec.adapters.rebotarm_zmq import ReBotArmZmqAdapter
from mimicrec.adapters.robot import RobotMode
from mimicrec.errors import HardwareError


REPO = Path(__file__).resolve().parents[2]
MOCK = REPO / "scripts" / "rebotarm_daemon_mock.py"
PY = REPO / ".venv" / "bin" / "python"


@pytest.fixture
def mock_daemon():
    port = 5702
    proc = subprocess.Popen(
        [str(PY), str(MOCK), "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid,
    )
    time.sleep(0.5)
    try:
        yield port
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=2)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=2)


@pytest.mark.asyncio
async def test_send_command_requires_position_mode(mock_daemon):
    """In default (gravity-comp) mode, send_joint_command must raise. After
    set_mode(POSITION), the same command must succeed."""
    a = ReBotArmZmqAdapter(
        address=f"tcp://localhost:{mock_daemon}",
        heartbeat_interval_ms=100,
    )
    await a.connect()
    try:
        # Daemon defaults to MODE_GRAVITY_COMP — sending a position command
        # while in that mode would silently no-op without the contract, so
        # the daemon must reject it.
        with pytest.raises(HardwareError):
            await a.send_joint_command(np.zeros(6, dtype=np.float32))

        # After the mode flip, the same command is accepted.
        await a.set_mode(RobotMode.POSITION)
        await a.send_joint_command(np.zeros(6, dtype=np.float32))

        # Flipping back into gravity-comp re-engages the rejection.
        await a.set_mode(RobotMode.GRAVITY_COMP)
        with pytest.raises(HardwareError):
            await a.send_joint_command(np.zeros(6, dtype=np.float32))
    finally:
        await a.disconnect()
