from httpx import AsyncClient, ASGITransport


async def test_pending_returns_zero_when_no_session(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/session/gopro_pending")
    assert r.status_code == 200
    assert r.json() == {"pending": 0}
