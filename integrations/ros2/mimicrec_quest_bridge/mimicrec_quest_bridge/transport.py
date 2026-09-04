"""Threaded asyncio WebSocket transport for the ROS 2 node."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Callable, Sequence

import websockets


class MimicRecWebSocketTransport:
    def __init__(
        self,
        base_url: str,
        camera_names: Sequence[str],
        on_camera: Callable[[str, bytes, int], None],
        on_teleop_state: Callable[[bool], None] | None = None,
        motion_channel: str | None = None,
    ) -> None:
        base = base_url.rstrip("/")
        if base.startswith("http://"):
            base = "ws://" + base.removeprefix("http://")
        elif base.startswith("https://"):
            base = "wss://" + base.removeprefix("https://")
        if not base.startswith(("ws://", "wss://")):
            raise ValueError("mimicrec_url must start with ws://, wss://, http:// or https://")
        self._base_url = base
        self._camera_names = tuple(camera_names)
        self._on_camera = on_camera
        self._on_teleop_state = on_teleop_state or (lambda _connected: None)
        self._motion_channel = motion_channel
        self._logger = logging.getLogger(__name__)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._message_lock = threading.Lock()
        self._message_sequence = 0
        self._latest_message: dict = {"cmd": "stop"}
        if motion_channel is not None:
            self._latest_message["channel"] = motion_channel
        self._pending_events: list[tuple[float, dict]] = []
        self._teleop_connected = threading.Event()
        self._last_retry_log_at: dict[str, float] = {}

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._thread_main,
            name="mimicrec-ws-bridge",
            daemon=True,
        )
        self._thread.start()

    def send_pose_offset(
        self, offset: Sequence[float], gripper_fraction: float
    ) -> None:
        self._replace_message(
            {
                "cmd": "ee_pose_offset",
                "offset": [float(value) for value in offset],
                "gripper_fraction": float(gripper_fraction),
            }
        )

    def send_world_delta(
        self, delta: Sequence[float], gripper_fraction: float
    ) -> None:
        self._replace_message(
            {
                "cmd": "ee_world_delta",
                # Translation column followed by world/spatial rotvec. The
                # backend converts this literal pose increment to an se(3)
                # logarithm before recording the canonical SE3Delta.
                "delta": [float(value) for value in delta],
                "gripper_fraction": float(gripper_fraction),
            }
        )

    def send_world_pose_offset(
        self,
        offset: Sequence[float],
        control_rotation: Sequence[float],
        gripper_fraction: float,
    ) -> None:
        self._replace_message(
            {
                "cmd": "ee_world_pose_offset",
                # Absolute clutch-relative translation and spatial rotation
                # in the tracking WORLD frame. The backend differentiates it
                # for canonical recording while mappers retain the absolute
                # target for lossless rate-limited control.
                "offset": [float(value) for value in offset],
                "control_rotation": [
                    float(value) for value in control_rotation
                ],
                "gripper_fraction": float(gripper_fraction),
            }
        )

    def send_home(self) -> bool:
        """Queue a short-lived one-shot home request only while connected."""
        if not self._teleop_connected.is_set():
            return False
        with self._message_lock:
            self._pending_events.append(
                (time.monotonic() + 0.25, {"cmd": "home"})
            )
        return True

    def send_stop(self) -> None:
        self._replace_message({"cmd": "stop"})

    def stop(self) -> None:
        self.send_stop()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _replace_message(self, message: dict) -> None:
        if self._motion_channel is not None:
            message = {**message, "channel": self._motion_channel}
        with self._message_lock:
            self._latest_message = message
            self._message_sequence += 1

    def _snapshot_message(self) -> tuple[int, dict]:
        with self._message_lock:
            return self._message_sequence, dict(self._latest_message)

    def _take_events(self) -> list[dict]:
        now = time.monotonic()
        with self._message_lock:
            events = [message for expiry, message in self._pending_events if expiry >= now]
            self._pending_events.clear()
        if self._motion_channel is None:
            return events
        return [
            {**message, "channel": self._motion_channel} for message in events
        ]

    def _discard_events(self) -> None:
        with self._message_lock:
            self._pending_events.clear()

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception:
            self._logger.exception("MimicRec WebSocket bridge stopped unexpectedly")

    async def _run(self) -> None:
        tasks = [asyncio.create_task(self._teleop_loop())]
        tasks.extend(
            asyncio.create_task(self._camera_loop(camera_name))
            for camera_name in self._camera_names
        )
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _teleop_loop(self) -> None:
        url = f"{self._base_url}/ws/teleop"
        while not self._stop.is_set():
            connected = False
            try:
                async with websockets.connect(
                    url,
                    open_timeout=3,
                    close_timeout=1,
                    ping_interval=10,
                    ping_timeout=5,
                ) as websocket:
                    raw_init = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                    init = json.loads(raw_init)
                    if init.get("input_mode") != "ee_delta":
                        raise RuntimeError(
                            "active MimicRec session is not using an ee_delta teleoperator"
                        )
                    connected = True
                    self._teleop_connected.set()
                    self._on_teleop_state(True)
                    initial_stop = {"cmd": "stop"}
                    if self._motion_channel is not None:
                        initial_stop["channel"] = self._motion_channel
                    await websocket.send(json.dumps(initial_stop))
                    sent_sequence = -1
                    while True:
                        sequence, message = self._snapshot_message()
                        if sequence != sent_sequence:
                            await websocket.send(json.dumps(message))
                            sent_sequence = sequence
                        for event in self._take_events():
                            await websocket.send(json.dumps(event))
                        if self._stop.is_set():
                            break
                        await asyncio.sleep(0.005)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._log_retry("teleop", exc)
                await self._retry_delay()
            finally:
                self._teleop_connected.clear()
                self._discard_events()
                if connected:
                    self._on_teleop_state(False)

    async def _camera_loop(self, camera_name: str) -> None:
        url = f"{self._base_url}/ws/cameras/{camera_name}"
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    url,
                    open_timeout=3,
                    close_timeout=1,
                    ping_interval=10,
                    ping_timeout=5,
                    max_size=16 * 1024 * 1024,
                ) as websocket:
                    while not self._stop.is_set():
                        try:
                            payload = await asyncio.wait_for(
                                websocket.recv(), timeout=0.25
                            )
                        except asyncio.TimeoutError:
                            continue
                        if isinstance(payload, bytes):
                            self._on_camera(camera_name, payload, time.time_ns())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._log_retry(f"camera {camera_name}", exc)
                await self._retry_delay()

    def _log_retry(self, channel: str, exc: Exception) -> None:
        now = time.monotonic()
        if now - self._last_retry_log_at.get(channel, 0.0) < 10.0:
            return
        self._last_retry_log_at[channel] = now
        self._logger.warning("%s WebSocket unavailable (%s); retrying", channel, exc)

    async def _retry_delay(self) -> None:
        for _ in range(10):
            if self._stop.is_set():
                return
            await asyncio.sleep(0.1)
