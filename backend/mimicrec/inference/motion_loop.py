from __future__ import annotations

import asyncio
import time

from mimicrec.motion.types import MotionStep
from mimicrec.types import Stamped


async def run_motion_inference(
    *,
    session,
    runtime,
    group_name: str,
    client,
    decoder,
    state_provider,
    camera_slots,
    instruction_slot,
    publish_event=None,
) -> None:
    async def publish(event: dict) -> None:
        if publish_event is not None:
            await publish_event(event)

    runtime.pause_inputs()
    try:
        while not session.stopped.is_set():
            if session.producer_paused:
                await asyncio.sleep(0.02)
                continue
            state = state_provider()
            instruction = instruction_slot.peek()
            frames = {name: slot.peek() for name, slot in camera_slots.items()}
            if (
                state is None
                or instruction is None
                or any(frame is None for frame in frames.values())
            ):
                await asyncio.sleep(0.02)
                continue
            started = time.perf_counter()
            response = await client.predict(
                frames,
                state,
                instruction,
                extras={"_t_mono_ns": {"state": state.t_mono_ns}},
            )
            chunk = decoder.decode(response)
            await publish({
                "type": "inference_done",
                "latency_ms": (time.perf_counter() - started) * 1000,
                "chunk_size": len(chunk),
            })
            for step in chunk:
                if session.stopped.is_set() or session.producer_paused:
                    break
                now = time.monotonic_ns()
                runtime.inject_step(group_name, MotionStep(
                    delta=step.delta,
                    auxiliary=step.auxiliary,
                    t_mono_ns=now,
                ))
                await publish({
                    "type": "next_action_preview",
                    "motion_group": group_name,
                    "se3_delta": step.delta.tangent.tolist(),
                    "gripper": step.auxiliary.get("gripper"),
                })
                await asyncio.sleep(step.delta.duration_sec)
    finally:
        runtime.resume_inputs()
        await client.aclose()
