"""Existing-dataset config immutability: a session-start that disagrees with
the recorded info.json schema (robot_type / fps / cameras set) must
return 400 instead of silently appending heterogeneous episodes.

LeRobot v3 datasets have a fixed features schema; mid-dataset camera
addition produces orphan video files that no loader will read.
"""
from httpx import AsyncClient, ASGITransport


async def _start_initial_session(app, body):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/session/start", json=body)
        assert r.status_code == 200, r.text
        await ac.post("/api/session/end")


async def test_existing_dataset_rejects_camera_addition(app, tmp_path):
    """First session creates dataset with cameras=[]; second session tries to
    add a camera → 400."""
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir()

    initial = {
        "mode": "teleop",
        "dataset": "ds_immutable",
        "task": "pick",
        "robot": "mock",
        "teleop": "mock_leader",
        "mapper": "identity",
        "cameras": [],
        "fps": 30,
    }
    await _start_initial_session(app, initial)

    # Now request a session on the same dataset but with a camera that
    # wasn't in the schema.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/session/start", json={**initial, "cameras": ["mock_cam"]})

    assert r.status_code == 400, r.text
    detail = r.json().get("detail", "")
    assert "ds_immutable" in detail
    assert "unexpected" in detail or "missing" in detail


async def test_existing_dataset_rejects_fps_change(app, tmp_path):
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir()

    initial = {
        "mode": "teleop",
        "dataset": "ds_fps",
        "task": "pick",
        "robot": "mock",
        "teleop": "mock_leader",
        "mapper": "identity",
        "cameras": [],
        "fps": 30,
    }
    await _start_initial_session(app, initial)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/session/start", json={**initial, "fps": 60})

    assert r.status_code == 400, r.text
    detail = r.json().get("detail", "")
    assert "fps" in detail


async def test_existing_dataset_accepts_matching_config(app, tmp_path):
    """Sanity: re-opening a dataset with the same config must not 400."""
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir()

    body = {
        "mode": "teleop",
        "dataset": "ds_match",
        "task": "pick",
        "robot": "mock",
        "teleop": "mock_leader",
        "mapper": "identity",
        "cameras": [],
        "fps": 30,
    }
    await _start_initial_session(app, body)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/session/start", json=body)
        assert r.status_code == 200, r.text
        await ac.post("/api/session/end")
