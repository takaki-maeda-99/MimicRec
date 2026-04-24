from __future__ import annotations
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/cameras/{cam_name}")
async def ws_camera(websocket: WebSocket, cam_name: str):
    await websocket.accept()
    cm = getattr(websocket.app.state, "camera_manager", None)
    if not cm:
        await websocket.close(code=1008, reason="no active session")
        return
    try:
        q = cm.subscribe_preview(cam_name)
    except KeyError:
        await websocket.close(code=1008, reason=f"camera '{cam_name}' not found")
        return
    try:
        while True:
            try:
                jpg = await asyncio.wait_for(q.get(), timeout=1.0)
                await websocket.send_bytes(jpg)
            except asyncio.TimeoutError:
                # Check if client disconnected
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
                except asyncio.TimeoutError:
                    continue
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
