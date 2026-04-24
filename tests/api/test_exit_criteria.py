"""Exit-criteria test suite — maps 1:1 to Plan B acceptance gates."""
from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path

import yaml
from httpx import AsyncClient, ASGITransport as HttpTransport
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_app(tmp_path: Path | None = None):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    if tmp_path is not None:
        ds = tmp_path / "datasets"
        ds.mkdir(exist_ok=True)
        app.state.datasets_root = ds
    return app


# ---------------------------------------------------------------------------
# Criterion 1: GET /api/health -> 200
# ---------------------------------------------------------------------------

async def test_exit_criterion_1_health():
    app = _make_app()
    async with AsyncClient(transport=HttpTransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Criterion 2: POST /api/session/start -> 200, state == "ready"
# ---------------------------------------------------------------------------

async def test_exit_criterion_2_session_start(tmp_path: Path):
    app = _make_app(tmp_path)
    async with AsyncClient(transport=HttpTransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/session/start", json={
            "mode": "teleop", "dataset": "ec2", "task": "pick",
            "robot": "mock", "teleop": "mock_leader", "mapper": "identity",
            "cameras": [], "fps": 30,
        })
        assert r.status_code == 200
        assert r.json()["state"] == "ready"
        await ac.post("/api/session/end")


# ---------------------------------------------------------------------------
# Criterion 3: Full episode cycle via HTTP; parquet file exists afterwards
# ---------------------------------------------------------------------------

async def test_exit_criterion_3_full_episode_cycle(tmp_path: Path):
    app = _make_app(tmp_path)
    async with AsyncClient(transport=HttpTransport(app=app), base_url="http://test") as ac:
        await ac.post("/api/session/start", json={
            "mode": "teleop", "dataset": "ec3", "task": "pick",
            "robot": "mock", "teleop": "mock_leader", "mapper": "identity",
            "cameras": [], "fps": 30,
        })
        await ac.post("/api/episode/start")
        await asyncio.sleep(0.15)
        await ac.post("/api/episode/stop")
        r = await ac.post("/api/episode/save", json={"success": True})
        assert r.json()["state"] == "ready"
        pq = (tmp_path / "datasets" / "ec3" / "data"
              / "chunk-000" / "episode_000000.parquet")
        assert pq.exists(), f"parquet not found at {pq}"
        await ac.post("/api/session/end")


# ---------------------------------------------------------------------------
# Criterion 4: DELETE -> 204, episode tombstoned (not returned in listing)
# ---------------------------------------------------------------------------

async def test_exit_criterion_4_tombstone_delete(tmp_path: Path):
    app = _make_app(tmp_path)
    async with AsyncClient(transport=HttpTransport(app=app), base_url="http://test") as ac:
        await ac.post("/api/session/start", json={
            "mode": "teleop", "dataset": "ec4", "task": "pick",
            "robot": "mock", "teleop": "mock_leader", "mapper": "identity",
            "cameras": [], "fps": 30,
        })
        await ac.post("/api/episode/start")
        await asyncio.sleep(0.1)
        await ac.post("/api/episode/stop")
        await ac.post("/api/episode/save")
        await ac.post("/api/session/end")

        r = await ac.delete("/api/datasets/ec4/episodes/0")
        assert r.status_code == 204

        r = await ac.get("/api/datasets/ec4/episodes")
        assert r.status_code == 200
        assert len(r.json()) == 0, f"expected 0 episodes, got {r.json()}"


# ---------------------------------------------------------------------------
# Criterion 5: Archive zip excludes tombstoned episodes
# ---------------------------------------------------------------------------

async def test_exit_criterion_5_archive_excludes_tombstoned(tmp_path: Path):
    app = _make_app(tmp_path)
    async with AsyncClient(transport=HttpTransport(app=app), base_url="http://test") as ac:
        # Record two episodes
        await ac.post("/api/session/start", json={
            "mode": "teleop", "dataset": "ec5", "task": "pick",
            "robot": "mock", "teleop": "mock_leader", "mapper": "identity",
            "cameras": [], "fps": 30,
        })
        for _ in range(2):
            await ac.post("/api/episode/start")
            await asyncio.sleep(0.1)
            await ac.post("/api/episode/stop")
            await ac.post("/api/episode/save")
        await ac.post("/api/session/end")

        # Tombstone first episode
        await ac.delete("/api/datasets/ec5/episodes/0")

        # Download archive
        r = await ac.get("/api/datasets/ec5/archive")
        assert r.status_code == 200
        buf = io.BytesIO(r.content)
        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
        assert not any("episode_000000" in n for n in names), (
            f"tombstoned episode_000000 found in archive: {names}"
        )
        assert any("episode_000001" in n for n in names), (
            f"episode_000001 missing from archive: {names}"
        )


# ---------------------------------------------------------------------------
# Criterion 6: /ws/session delivers session_state events (snapshot on connect)
# ---------------------------------------------------------------------------

async def test_exit_criterion_6_ws_session_state_events():
    app = _make_app()
    async with ASGIWebSocketTransport(app=app) as transport:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with aconnect_ws("/ws/session", client) as ws:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                assert msg["type"] == "session_state"
                assert msg["data"]["state"] == "idle"


# ---------------------------------------------------------------------------
# Criterion 7: /ws/cameras/{cam} delivers JPEG binary frames
# ---------------------------------------------------------------------------

async def test_exit_criterion_7_ws_camera_jpeg(tmp_path: Path):
    app = _make_app(tmp_path)

    # Start session with a camera
    async with AsyncClient(transport=HttpTransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/session/start", json={
            "mode": "teleop", "dataset": "ec7", "task": "pick",
            "robot": "mock", "teleop": "mock_leader", "mapper": "identity",
            "cameras": ["mock_cam"], "fps": 30,
        })
        assert r.status_code == 200

    await asyncio.sleep(0.25)  # let camera produce frames

    async with ASGIWebSocketTransport(app=app) as transport:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with aconnect_ws("/ws/cameras/mock_cam", client) as ws:
                data = await asyncio.wait_for(ws.receive_bytes(), timeout=3.0)
                assert data[:2] == b'\xff\xd8', (
                    f"expected JPEG magic bytes, got {data[:4].hex()}"
                )

    # Cleanup
    async with AsyncClient(transport=HttpTransport(app=app), base_url="http://test") as ac:
        await ac.post("/api/session/end")


# ---------------------------------------------------------------------------
# Criterion 8: SO-101 hand-teach -> HTTP 422 HandTeachNotSupportedError
# ---------------------------------------------------------------------------

async def test_exit_criterion_8_so101_handteach_422(tmp_path: Path):
    # Create a temporary robot config that targets SO101Adapter
    robot_cfg_dir = tmp_path / "configs" / "robot"
    robot_cfg_dir.mkdir(parents=True, exist_ok=True)
    (robot_cfg_dir / "so101_test.yaml").write_text(yaml.dump({
        "_target_": "mimicrec.adapters.so101.SO101Adapter",
        "port": "/dev/null",
    }))

    # Also create stubs for the other config dirs so the loader doesn't break
    for sub in ("teleop", "mapper", "cameras"):
        (tmp_path / "configs" / sub).mkdir(parents=True, exist_ok=True)

    app = _make_app(tmp_path)
    app.state.configs_root = tmp_path / "configs"

    async with AsyncClient(transport=HttpTransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/session/start", json={
            "mode": "hand_teach", "dataset": "ec8_so101", "task": "teach",
            "robot": "so101_test", "cameras": [], "fps": 30,
        })
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"
        detail = r.json()["detail"].lower()
        assert "hand-teach" in detail or "gravity" in detail, (
            f"unexpected detail: {r.json()['detail']!r}"
        )


# ---------------------------------------------------------------------------
# Criterion 9: InvalidTransitionError on bad transition -> HTTP 409
# ---------------------------------------------------------------------------

async def test_exit_criterion_9_invalid_transition_409(tmp_path: Path):
    app = _make_app(tmp_path)
    async with AsyncClient(transport=HttpTransport(app=app), base_url="http://test") as ac:
        # episode/start without an active session -> InvalidTransitionError
        r = await ac.post("/api/episode/start")
        assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# Criterion 10: ReplayStartRequest with speed=0 -> 422 (Pydantic validation)
# ---------------------------------------------------------------------------

async def test_exit_criterion_10_speed_validation():
    app = _make_app()
    async with AsyncClient(transport=HttpTransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/replay/start", json={
            "dataset": "x", "episode_idx": 0, "speed": 0,
        })
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"
