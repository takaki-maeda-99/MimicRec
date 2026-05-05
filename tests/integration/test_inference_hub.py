import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mimicrec.api.ws.inference_hub import InferenceHub, get_inference_hub, router as hub_router


def test_subscribe_unsubscribe():
    hub = InferenceHub()
    q = hub.subscribe()
    assert len(hub._subs) == 1
    hub.unsubscribe(q)
    assert len(hub._subs) == 0


async def test_publish_to_subscriber():
    hub = InferenceHub()
    q = hub.subscribe()
    await hub.publish({"type": "test", "x": 1})
    received = q.get_nowait()
    assert received == {"type": "test", "x": 1}


async def test_publish_drops_on_full_queue():
    hub = InferenceHub()
    hub.QUEUE_MAX = 2          # type: ignore — instance override for this test
    q = hub.subscribe()
    # Re-create the queue with the smaller maxsize. (subscribe() captured the old
    # class attribute; recreate to test the drop behavior.)
    hub._subs = [asyncio.Queue(maxsize=2)]
    q = hub._subs[0]
    await hub.publish({"i": 0})
    await hub.publish({"i": 1})
    # Third publish must not raise; it gets dropped.
    await hub.publish({"i": 2})
    assert q.qsize() == 2


def test_get_inference_hub_singleton():
    app = FastAPI()
    h1 = get_inference_hub(app)
    h2 = get_inference_hub(app)
    assert h1 is h2


def test_ws_endpoint_registered():
    app = FastAPI()
    app.include_router(hub_router)
    paths = [r.path for r in app.routes]
    assert "/ws/inference" in paths
