from __future__ import annotations
import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from mimicrec.api.deps import get_session_manager_or_none

router = APIRouter()


def _build_ws_state(app) -> dict:
    sm = get_session_manager_or_none(app)
    meta = getattr(app.state, "session_meta", None) or {}
    if sm is None:
        return {"state": "idle"}
    return {
        "state": sm.session.state.value,
        "sub_state": sm.session.sub_state.value if sm.session.sub_state else None,
        "mode": sm.session.mode.value if sm.session.mode else None,
        "dataset": meta.get("dataset"),
        "task": meta.get("task"),
        "robot": meta.get("robot"),
    }


@router.websocket("/ws/session")
async def ws_session(websocket: WebSocket):
    await websocket.accept()
    app = websocket.app

    # Send initial state snapshot
    await websocket.send_json({
        "type": "session_state",
        "data": _build_ws_state(app),
    })

    last_state = _build_ws_state(app)
    error_sub = None

    try:
        while True:
            # Poll for state changes at ~5 Hz.
            # Use receive_text with timeout so the ASGI transport can detect
            # client-side close; plain asyncio.sleep never checks the channel.
            current = _build_ws_state(app)
            if current != last_state:
                await websocket.send_json({"type": "session_state", "data": current})
                last_state = current

            # Check for errors from ErrorBus
            sm = get_session_manager_or_none(app)
            if sm and error_sub is None:
                bus = getattr(app.state, "error_bus", None)
                if bus:
                    error_sub = bus.subscribe()

            if error_sub:
                try:
                    evt = error_sub.get_nowait()
                    await websocket.send_json({
                        "type": "error",
                        "data": {
                            "error": type(evt).__name__,
                            "message": str(evt),
                        },
                    })
                except asyncio.QueueEmpty:
                    pass

            # Episode progress during RECORDING
            if sm and current.get("state") == "recording":
                metrics = sm._metrics
                await websocket.send_json({
                    "type": "episode_progress",
                    "data": {
                        "num_frames": metrics.get("writer_rows_written"),
                        "stale_sample_count": metrics.get("stale_sample_count"),
                        "writer_queue_depth": metrics.gauge("queue_depth"),
                        "writer_lag_ms": metrics.gauge("writer_lag_ms"),
                        "ticks_skipped": metrics.get("ticks_skipped"),
                    },
                })

            # Replay progress during REPLAYING
            if sm and current.get("sub_state") == "replaying":
                await websocket.send_json({
                    "type": "replay_progress",
                    "data": {"frame_index": 0, "total_frames": 0, "speed": 1.0},
                })

            # 5 Hz poll: wait for client message or timeout.
            # This lets the ASGI layer deliver disconnect events.
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=0.2)
            except asyncio.TimeoutError:
                pass

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
