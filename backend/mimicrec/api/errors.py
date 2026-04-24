from __future__ import annotations
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mimicrec.errors import (
    HandTeachNotSupportedError, InvalidTransitionError,
    HardwareError, RecorderError, ReplaySafetyError,
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HandTeachNotSupportedError)
    async def handle_handteach(req: Request, exc: HandTeachNotSupportedError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(InvalidTransitionError)
    async def handle_transition(req: Request, exc: InvalidTransitionError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(HardwareError)
    async def handle_hardware(req: Request, exc: HardwareError):
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.exception_handler(RecorderError)
    async def handle_recorder(req: Request, exc: RecorderError):
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.exception_handler(ReplaySafetyError)
    async def handle_replay_safety(req: Request, exc: ReplaySafetyError):
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.exception_handler(FileNotFoundError)
    async def handle_not_found(req: Request, exc: FileNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(KeyError)
    async def handle_key_error(req: Request, exc: KeyError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def handle_value_error(req: Request, exc: ValueError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})
