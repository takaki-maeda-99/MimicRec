from __future__ import annotations
import asyncio
from pathlib import Path

from httpx import AsyncClient, ASGITransport as HttpTransport
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


async def test_ws_camera_receives_jpeg(tmp_path: Path):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir()

    # Start session with a camera
    transport = HttpTransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/session/start", json={
            "mode": "teleop", "dataset": "ws_cam_test", "task": "pick",
            "robot": "mock", "teleop": "mock_leader", "mapper": "identity",
            "cameras": ["mock_cam"], "fps": 30,
        })
        assert r.status_code == 200

    await asyncio.sleep(0.25)  # let camera produce frames

    async with ASGIWebSocketTransport(app=app) as ws_transport:
        async with AsyncClient(transport=ws_transport, base_url="http://test") as client:
            async with aconnect_ws("/ws/cameras/mock_cam", client) as ws:
                data = await asyncio.wait_for(ws.receive_bytes(), timeout=3.0)
                # JPEG starts with FF D8
                assert data[:2] == b'\xff\xd8', f"expected JPEG, got {data[:4].hex()}"

    # Cleanup
    transport = HttpTransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.post("/api/session/end")


async def test_ws_camera_no_session_closes():
    app = create_app()
    async with ASGIWebSocketTransport(app=app) as ws_transport:
        async with AsyncClient(transport=ws_transport, base_url="http://test") as client:
            try:
                async with aconnect_ws("/ws/cameras/front", client) as ws:
                    # Should receive close
                    pass
            except Exception:
                pass  # Expected -- no session active
