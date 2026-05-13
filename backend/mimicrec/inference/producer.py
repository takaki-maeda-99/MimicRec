from __future__ import annotations
import asyncio
import time


# Map exception to short kind label used by error_bus + WS.
def classify(e: Exception) -> str:
    name = type(e).__name__
    if "Timeout" in name:
        return "http_timeout"
    if "JSONDecode" in name or "KeyError" in name:
        return "schema"
    return "transport"


INITIAL_BACKOFF_S = 0.1                          # module-level so tests can monkeypatch
NOT_READY_RETRY_S = 0.05


async def run_inference_producer(
    client, decoder, buffer, camera_slots, robot_state_slot, instruction_slot,
    safety, session, metrics, error_bus,
    publish_event=None,                          # Callable[[dict], Awaitable[None]] | None
):
    """`publish_event` is the WS broadcast hook (inference_hub.publish). It is
    optional so unit tests can pass `None` and verify metrics+buffer behavior
    without requiring a full hub. Task 19 wires the real hub via lifecycle."""
    buffer.request_refill_now()
    backoff_s = INITIAL_BACKOFF_S

    async def _publish(event: dict) -> None:
        if publish_event is not None:
            await publish_event(event)

    async def stop_aware_sleep(seconds: float) -> bool:
        try:
            await asyncio.wait_for(session.stopped.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False

    while not session.stopped.is_set():
        # Wait for a refill request OR a stop signal so we don't block
        # forever when session.stopped is set while we're in wait_for_refill.
        refill_task = asyncio.ensure_future(buffer.wait_for_refill())
        stop_task = asyncio.ensure_future(session.stopped.wait())
        done, pending = await asyncio.wait(
            [refill_task, stop_task], return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
        if session.stopped.is_set():
            return

        if session.producer_paused:
            continue

        gen = buffer.current_generation()
        frames = {n: s.peek() for n, s in camera_slots.items()}
        state = robot_state_slot.peek()
        instr = instruction_slot.peek()

        not_ready = (
            state is None or instr is None or
            not frames or any(f is None for f in frames.values())
        )
        if not_ready:
            if await stop_aware_sleep(NOT_READY_RETRY_S):
                return
            buffer.request_refill_now()
            continue

        t0 = time.perf_counter()
        try:
            extras = {
                "_t_mono_ns": {
                    "state": state.t_mono_ns,
                    **{f"image:{n}": f.t_mono_ns for n, f in frames.items()},
                    "instruction": instr.t_mono_ns,
                },
            }
            resp = await client.predict(frames, state, instr, extras=extras)
            chunk = decoder.decode(resp, current_state=state.value)
            pushed = buffer.try_push_chunk(chunk, generation=gen)
            if not pushed:
                metrics.inc("inference_chunk_dropped_stale")
                await _publish({"type": "inference_chunk_dropped_stale",
                                "generation_was": gen,
                                "current_generation": buffer.current_generation()})
                buffer.request_refill_now()
            else:
                # Snapshot the previous chunk's clamp count BEFORE on_new_chunk()
                # resets it. clamps_per_chunk is emitted at chunk boundaries,
                # which only the producer can detect (the control_loop just
                # consumes one step at a time and doesn't know what's a boundary).
                prev_clamps = safety.clamps_in_current_chunk()
                await _publish({"type": "clamps_per_chunk",
                                "count": prev_clamps,
                                "chunk_size": len(chunk)})
                safety.on_new_chunk()
                latency_ms = (time.perf_counter() - t0) * 1000
                metrics.observe("inference_latency_ms", latency_ms)
                await _publish({"type": "inference_done",
                                "latency_ms": latency_ms,
                                "chunk_size": len(chunk)})
                # First step of the freshly-decoded chunk: shows the operator
                # what the model is asking for (ΔEE + gripper) before IK +
                # safety clamping. Frontend `next_action_preview` handler
                # displays it in the live status panel.
                if chunk and chunk[0].ee_delta is not None:
                    await _publish({
                        "type": "next_action_preview",
                        "ee_delta": chunk[0].ee_delta.tolist(),
                        "gripper": float(chunk[0].gripper) if chunk[0].gripper is not None else 0.0,
                    })
                await _publish({"type": "buffer_state",
                                "depth": buffer.depth(),
                                "origin_size": buffer.origin_size(),
                                "generation": buffer.current_generation()})
                # Per-camera freshness so the UI can show whether the slot
                # actually has live frames. `peek()` returns the latest
                # Stamped[Frame] or None if no frame has ever landed.
                now_ns = time.monotonic_ns()
                cam_health = []
                for cam_name, slot in camera_slots.items():
                    stamped = slot.peek()
                    cam_health.append({
                        "name": cam_name,
                        "age_ms": None if stamped is None
                                  else max(0, (now_ns - stamped.t_mono_ns) // 1_000_000),
                    })
                await _publish({"type": "camera_health", "cameras": cam_health})
                backoff_s = INITIAL_BACKOFF_S
        except Exception as e:
            metrics.inc("inference_error_count")
            kind = classify(e)
            await error_bus.publish_inference_error(kind=kind, message=str(e))
            await _publish({"type": "inference_error", "kind": kind, "message": str(e)})
            if await stop_aware_sleep(backoff_s):
                return
            backoff_s = min(backoff_s * 2, 1.0)
            buffer.request_refill_now()
