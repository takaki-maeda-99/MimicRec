import os
import signal
import subprocess
import sys
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
    port = 5701
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
async def test_estop_blocks_and_clear_resumes(mock_daemon):
    a = ReBotArmZmqAdapter(address=f"tcp://localhost:{mock_daemon}",
                           heartbeat_interval_ms=100)
    await a.connect()
    try:
        # The daemon defaults to gravity-comp mode and rejects send_command
        # in that mode (mode contract); flip to POSITION first so this test
        # exercises the estop -> reject -> clear -> accept transitions and
        # not the orthogonal mode-contract rejection.
        await a.set_mode(RobotMode.POSITION)
        # baseline: send_command works
        await a.send_joint_command(np.zeros(6, dtype=np.float32))
        # estop
        await a.estop()
        with pytest.raises(HardwareError):
            await a.send_joint_command(np.zeros(6, dtype=np.float32))
        # clear
        result = await a.clear_estop()
        assert result.get("ok")
        # send_command works again
        await a.send_joint_command(np.zeros(6, dtype=np.float32))
    finally:
        await a.disconnect()
