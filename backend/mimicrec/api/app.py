from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mimicrec.api.routes import configs, datasets, episode, replay, session
from mimicrec.api.ws import session_hub, state_hub, camera_hub, teleop_hub
from mimicrec.api.errors import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    sm = getattr(app.state, "session_manager", None)
    if sm:
        await sm.end()


def create_app() -> FastAPI:
    app = FastAPI(title="MimicRec", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # MVP: allow all origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.session_manager = None
    app.state.error_bus = None
    app.state.camera_manager = None
    app.state.resolved_config = None
    app.state.session_meta = None
    app.state.configs_root = None
    app.state.datasets_root = None
    app.include_router(session.router, prefix="/api")
    app.include_router(episode.router, prefix="/api")
    app.include_router(replay.router, prefix="/api")
    app.include_router(datasets.router, prefix="/api")
    app.include_router(configs.router, prefix="/api")
    app.include_router(session_hub.router)
    app.include_router(state_hub.router)
    app.include_router(camera_hub.router)
    app.include_router(teleop_hub.router)
    register_exception_handlers(app)
    return app


app = create_app()
