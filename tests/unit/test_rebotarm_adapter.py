import asyncio
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest
import numpy as np

from mimicrec.adapters.rebotarm_zmq import ReBotArmZmqAdapter

REPO = Path(__file__).resolve().parents[2]
MOCK = REPO / "scripts" / "rebotarm_daemon_mock.py"
PY = REPO / ".venv" / "bin" / "python"


@pytest.fixture
def daemon_port():
    """Spawn mock daemon on a unique port, yield port, kill on teardown."""
    port = 5600 + int(time.time() * 1000) % 100  # cheap uniqueifier
    proc = subprocess.Popen([str(PY), str(MOCK), "--port", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            preexec_fn=os.setsid)
    time.sleep(0.5)
    try:
        yield port
    finally:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=2)


@pytest.mark.asyncio
async def test_connect_returns_dof_and_starts_heartbeat(daemon_port):
    a = ReBotArmZmqAdapter(address=f"tcp://localhost:{daemon_port}",
                           heartbeat_interval_ms=100)
    await a.connect()
    try:
        assert a.dof == 6
        assert a.joint_names == [f"j{i}" for i in range(1, 7)]
        # heartbeat task should be active
        assert a._heartbeat_task is not None
        await asyncio.sleep(0.25)
        assert not a._heartbeat_task.done()
    finally:
        await a.disconnect()


@pytest.mark.asyncio
async def test_read_state_includes_ee_fields(daemon_port):
    a = ReBotArmZmqAdapter(address=f"tcp://localhost:{daemon_port}",
                           heartbeat_interval_ms=100)
    await a.connect()
    try:
        s = await a.read_state()
        assert s.joint_pos.shape == (6,)
        assert s.ee_pos is not None and s.ee_pos.shape == (3,)
        assert s.ee_rotvec is not None and s.ee_rotvec.shape == (3,)
        assert s.gripper_pos is not None
    finally:
        await a.disconnect()


@pytest.mark.asyncio
async def test_send_joint_command_round_trips(daemon_port):
    a = ReBotArmZmqAdapter(address=f"tcp://localhost:{daemon_port}",
                           heartbeat_interval_ms=100)
    await a.connect()
    try:
        await a.send_joint_command(np.zeros(6, dtype=np.float32))
    finally:
        await a.disconnect()


@pytest.mark.asyncio
async def test_estop_blocks_send_command(daemon_port):
    a = ReBotArmZmqAdapter(address=f"tcp://localhost:{daemon_port}",
                           heartbeat_interval_ms=100)
    await a.connect()
    try:
        await a.estop()
        with pytest.raises(Exception):
            await a.send_joint_command(np.zeros(6, dtype=np.float32))
        await a.clear_estop()
        # now succeeds again
        await a.send_joint_command(np.zeros(6, dtype=np.float32))
    finally:
        await a.disconnect()
