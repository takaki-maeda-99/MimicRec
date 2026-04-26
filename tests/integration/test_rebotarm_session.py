"""End-to-end test: rebotarm adapter -> SessionManager -> parquet has EE columns.

Spawns the mock reBotArm daemon as a subprocess, points the
ReBotArmZmqAdapter at it, runs a brief record cycle through SessionManager
(no local FKService), saves the episode, and asserts the saved parquet has
``observation.state.ee_pos`` / ``ee_rotvec`` / ``gripper_pos`` columns.

This proves the RobotState-side EE path: the daemon synthesizes EE in the
state payload, the adapter forwards it onto RobotState.ee_*, and the parquet
writer picks those values up without any local FK service.
"""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from mimicrec.adapters.mock_teleop import MockTeleoperator
from mimicrec.adapters.rebotarm_zmq import ReBotArmZmqAdapter
from mimicrec.cameras.manager import CameraManager
from mimicrec.mappers.identity import IdentityMapper
from mimicrec.recording.dataset_layout import dataset_paths, init_dataset
from mimicrec.session.lifecycle import SessionManager
from mimicrec.types import SessionMode, SessionState
from mimicrec.util.error_bus import ErrorBus


REPO = Path(__file__).resolve().parents[2]
MOCK = REPO / "scripts" / "rebotarm_daemon_mock.py"
PY = REPO / ".venv" / "bin" / "python"


@pytest.fixture
def daemon_port():
    """Spawn mock daemon on a unique port; tear down on test exit."""
    # Offset away from the unit-test fixture's window so parallel /
    # back-to-back runs don't collide on the bound port.
    port = 5700 + int(time.time() * 1000) % 100
    proc = subprocess.Popen(
        [str(PY), str(MOCK), "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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


async def test_rebotarm_session_records_ee_columns(tmp_path: Path, daemon_port: int):
    """Full session against the mock daemon writes EE columns into parquet
    even though no local FKService was wired into SessionManager."""
    ds = tmp_path / "ds"
    joint_names = [f"j{i}" for i in range(1, 7)]
    init_dataset(ds, fps=30, joint_names=joint_names, camera_names=[])

    robot = ReBotArmZmqAdapter(
        address=f"tcp://localhost:{daemon_port}",
        heartbeat_interval_ms=200,
    )
    teleop = MockTeleoperator(dof=6)
    bus = ErrorBus()
    cm = CameraManager(cameras={}, error_bus=bus)
    sm = SessionManager(
        dataset_root=ds,
        robot=robot,
        teleop=teleop,
        mapper=IdentityMapper(),
        cameras=cm,
        mode=SessionMode.TELEOP,
        fps=30,
        error_bus=bus,
        resolved_config={},
        replay_safety=None,
        # No fk= argument: this is the key invariant — EE columns must come
        # from RobotState fields populated by the adapter, not from a local
        # FKService.
    )
    # Make the invariant explicit so a regression that wires up an FK by
    # default would fail this assertion before the parquet check.
    assert sm._fk is None

    try:
        await sm.start()
        assert sm.state == SessionState.READY

        await sm.episode_start()
        assert sm.state == SessionState.RECORDING
        # Let a few ticks of state flow through to the writer.
        await asyncio.sleep(0.3)

        await sm.episode_stop()
        assert sm.state == SessionState.REVIEW

        await sm.episode_save(success=True, comment="rebotarm-mock")
        assert sm.state == SessionState.READY
    finally:
        await sm.end()

    paths = dataset_paths(ds)
    parquet_path = paths.data_dir / "chunk-000" / "episode_000000.parquet"
    assert parquet_path.exists(), f"missing episode parquet at {parquet_path}"

    table = pq.read_table(parquet_path)
    cols = set(table.column_names)
    assert "observation.state.ee_pos" in cols, (
        f"expected EE pos column from daemon-side EE; got {sorted(cols)}"
    )
    assert "observation.state.ee_rotvec" in cols, (
        f"expected EE rotvec column from daemon-side EE; got {sorted(cols)}"
    )
    assert "observation.state.gripper_pos" in cols, (
        f"expected gripper_pos column from daemon-side EE; got {sorted(cols)}"
    )

    # And those columns must have non-empty data — at least one row written.
    assert table.num_rows > 0, "expected at least one frame to have been recorded"
    ee_pos_values = table.column("observation.state.ee_pos").to_pylist()
    assert all(v is not None and len(v) == 3 for v in ee_pos_values), (
        f"ee_pos values malformed: {ee_pos_values[:3]}"
    )
