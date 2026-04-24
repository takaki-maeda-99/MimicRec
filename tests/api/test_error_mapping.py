from httpx import AsyncClient, ASGITransport
from mimicrec.api.app import create_app
from mimicrec.errors import (
    HandTeachNotSupportedError, InvalidTransitionError,
    HardwareError, RecorderError, ReplaySafetyError,
)


def _app_with_error_routes():
    app = create_app()

    @app.get("/test/handteach")
    async def _():
        raise HandTeachNotSupportedError("test")

    @app.get("/test/transition")
    async def _t():
        raise InvalidTransitionError("test")

    @app.get("/test/hardware")
    async def _h():
        raise HardwareError("test")

    @app.get("/test/recorder")
    async def _r():
        raise RecorderError("test")

    @app.get("/test/replay_safety")
    async def _rs():
        raise ReplaySafetyError("test")

    @app.get("/test/not_found")
    async def _nf():
        raise FileNotFoundError("test")

    @app.get("/test/key_error")
    async def _ke():
        raise KeyError("test")

    return app


async def test_handteach_returns_422():
    app = _app_with_error_routes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/test/handteach")
    assert r.status_code == 422
    assert "test" in r.json()["detail"]


async def test_transition_returns_409():
    app = _app_with_error_routes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/test/transition")
    assert r.status_code == 409


async def test_hardware_returns_500():
    app = _app_with_error_routes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/test/hardware")
    assert r.status_code == 500


async def test_not_found_returns_404():
    app = _app_with_error_routes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/test/not_found")
    assert r.status_code == 404


async def test_key_error_returns_404():
    app = _app_with_error_routes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/test/key_error")
    assert r.status_code == 404
