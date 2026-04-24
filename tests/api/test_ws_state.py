from __future__ import annotations
import asyncio
from pathlib import Path

from httpx import AsyncClient, ASGITransport as HttpTransport
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


async def test_ws_state_receives_joint_data(tmp_path: Path):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir()

    # Start session first
    transport = HttpTransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/session/start", json={
            "mode": "teleop", "dataset": "ws_state_test", "task": "pick",
            "robot": "mock", "teleop": "mock_leader", "mapper": "identity",
            "cameras": [], "fps": 30,
        })
        assert r.status_code == 200

    await asyncio.sleep(0.15)  # let readers populate slots

    async with ASGIWebSocketTransport(app=app) as ws_transport:
        async with AsyncClient(transport=ws_transport, base_url="http://test") as client:
            async with aconnect_ws("/ws/state", client) as ws:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                assert "joint_pos" in msg
                assert "joint_vel" in msg
                assert "joint_effort" in msg
                assert "t_mono_ns" in msg
                assert isinstance(msg["joint_pos"], list)

    # Cleanup
    transport = HttpTransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.post("/api/session/end")
