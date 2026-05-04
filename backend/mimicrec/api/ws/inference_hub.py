"""WebSocket hub for inference telemetry events.

Pub-sub broker pattern: producers call `hub.publish(event)`, subscribers
receive events via per-subscriber asyncio.Queue. The hub itself is a
singleton stored on `app.state.inference_hub`.
"""
from __future__ import annotations
import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class InferenceHub:
    """Broadcasts inference telemetry events to all WS subscribers.

    Per-subscriber queue is bounded (maxsize=256) so a slow consumer
    can't accumulate unbounded memory; on overflow the event is dropped
    for that subscriber and a warning logged once per minute.
    """
    QUEUE_MAX = 256

    def __init__(self) -> None:
        self._subs: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self.QUEUE_MAX)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subs.remove(q)
        except ValueError:
            pass

    async def publish(self, event: dict) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("inference_hub subscriber queue full; dropping event %s", event.get("type"))


def get_inference_hub(app) -> InferenceHub:
    hub = getattr(app.state, "inference_hub", None)
    if hub is None:
        hub = InferenceHub()
        app.state.inference_hub = hub
    return hub


router = APIRouter()


@router.websocket("/ws/inference")
async def ws_inference(websocket: WebSocket):
    await websocket.accept()
    hub = get_inference_hub(websocket.app)
    q = hub.subscribe()
    try:
        while True:
            event = await q.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws_inference error")
    finally:
        hub.unsubscribe(q)
