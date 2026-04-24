from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI
from mimicrec.api.routes import session


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    sm = getattr(app.state, "session_manager", None)
    if sm:
        await sm.end()


def create_app() -> FastAPI:
    app = FastAPI(title="MimicRec", version="0.1.0", lifespan=lifespan)
    app.state.session_manager = None
    app.state.error_bus = None
    app.state.camera_manager = None
    app.state.resolved_config = None
    app.state.session_meta = None
    app.state.configs_root = None
    app.state.datasets_root = None
    app.include_router(session.router, prefix="/api")
    return app
