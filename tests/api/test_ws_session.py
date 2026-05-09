from __future__ import annotations
import asyncio
from pathlib import Path

from httpx import AsyncClient
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


async def test_ws_session_receives_idle_snapshot():
    app = create_app()
    async with ASGIWebSocketTransport(app=app) as transport:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with aconnect_ws("/ws/session", client) as ws:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                assert msg["type"] == "session_state"
                assert msg["data"]["state"] == "idle"


async def test_ws_session_receives_state_change(tmp_path: Path):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir()

    async with ASGIWebSocketTransport(app=app) as transport:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with aconnect_ws("/ws/session", client) as ws:
                # Get initial idle snapshot
                msg = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                assert msg["data"]["state"] == "idle"

                # Start session via REST (use a separate non-WS transport)
                from httpx import ASGITransport as HttpTransport
                http_transport = HttpTransport(app=app)
                async with AsyncClient(transport=http_transport, base_url="http://test") as ac:
                    r = await ac.post("/api/session/start", json={
                        "mode": "teleop",
                        "dataset": "ws_test",
                        "task": "pick",
                        "robot": "mock",
                        "teleop": "mock_leader",
                        "mapper": "identity",
                        "cameras": [],
                        "fps": 30,
                    })
                    assert r.status_code == 200

                # Wait for state change message
                found_ready = False
                for _ in range(20):  # up to 4 seconds at 5Hz polling
                    try:
                        msg = await asyncio.wait_for(ws.receive_json(), timeout=0.5)
                        if msg.get("type") == "session_state" and msg["data"]["state"] == "ready":
                            found_ready = True
                            break
                    except asyncio.TimeoutError:
                        continue
                assert found_ready, "never received state=ready on WebSocket"

                # Cleanup
                http_transport = HttpTransport(app=app)
                async with AsyncClient(transport=http_transport, base_url="http://test") as ac:
                    await ac.post("/api/session/end")


def test_ws_state_payload_includes_gopros():
    """Regression: ``_build_ws_state`` must emit ``gopros`` so the frontend's
    5Hz WS-driven session-store update doesn't overwrite ``store.gopros``
    with ``[]`` and unmount the GoPro CameraPreview tile within 200ms of
    session start.

    Tests the builder directly to avoid coupling to the real-arm session
    start path (which loads ``configs/rebotarm/idle_pose.yaml`` and the
    GoPro UDP preview port — both unavailable in CI).
    """
    from types import SimpleNamespace
    from mimicrec.api.ws.session_hub import _build_ws_state
    from mimicrec.types import SessionMode, SessionState

    app = SimpleNamespace(state=SimpleNamespace(
        session_manager=SimpleNamespace(session=SimpleNamespace(
            state=SessionState.READY, sub_state=None, mode=SessionMode.TELEOP,
        )),
        session_meta={
            "dataset": "d", "task": "t", "robot": "mock", "teleop": "mock_leader",
            "mapper": "identity", "cameras": ["wrist"], "gopros": ["gopro_external"],
            "fps": 30,
        },
    ))

    payload = _build_ws_state(app)
    assert "gopros" in payload, (
        f"WS session_state payload is missing 'gopros' key — frontend "
        f"will overwrite store.gopros with [] and unmount preview tile. "
        f"Got keys: {sorted(payload.keys())}"
    )
    assert payload["gopros"] == ["gopro_external"]
    # Sanity: the existing ``cameras`` field is still emitted.
    assert payload["cameras"] == ["wrist"]
