"""Fake VLA HTTP server for integration / E2E tests.

Async-context-manager that boots an aiohttp server on a random port
and serves /predict with configurable behavior:
- chunk_size: number of steps per chunk
- fail_first_n: return 500 the first N requests, succeed thereafter
- latency_s: artificial delay before responding
- emit_done_after: emit response.done=True after N chunks (None = never)

Usage:
    async with FakeVLAServer(chunk_size=8) as srv:
        url = srv.url           # e.g. http://127.0.0.1:34567/predict
        # ... point a contract at this URL ...
"""
from __future__ import annotations
import asyncio
from aiohttp import web


class FakeVLAServer:
    def __init__(
        self,
        *,
        chunk_size: int = 16,
        fail_first_n: int = 0,
        latency_s: float = 0.0,
        emit_done_after: int | None = None,
    ):
        self.chunk_size = chunk_size
        self.fail_first_n = fail_first_n
        self.latency_s = latency_s
        self.emit_done_after = emit_done_after
        self.calls = 0
        self.received: list[dict] = []
        self._app = web.Application()
        self._app.router.add_post("/predict", self._handler)
        self._runner: web.AppRunner | None = None
        self._port: int | None = None

    async def __aenter__(self):
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self._port = site._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *args):
        if self._runner is not None:
            await self._runner.cleanup()

    @property
    def url(self) -> str:
        assert self._port is not None
        return f"http://127.0.0.1:{self._port}/predict"

    async def _handler(self, request):
        self.calls += 1
        body = await request.json()
        self.received.append(body)
        if self.calls <= self.fail_first_n:
            return web.Response(status=500)
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        # mild EE motion: 1 mm step in +x each step, gripper held mid
        chunk = [[0.001, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5] for _ in range(self.chunk_size)]
        resp: dict = {"actions": chunk}
        if self.emit_done_after is not None and self.calls >= self.emit_done_after:
            resp["done"] = 1.0
        return web.json_response(resp)
