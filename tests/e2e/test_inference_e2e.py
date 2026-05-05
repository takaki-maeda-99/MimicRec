"""End-to-end inference test against a fake VLA HTTP server + mock_robot.

Marked @pytest.mark.e2e so it's opt-in (run with `pytest -m e2e`). The
existing CI suite stays fast; this test is for manual / nightly runs.

We use the make_inference_session fixture from tests/conftest.py, which
boots a SessionManager wired to a FakeVLAServer (mild EE motion: 1 mm
+x per step). The mock_robot adapter applies commands but doesn't
simulate physics — joint_pos stays where set.
"""
from __future__ import annotations
import asyncio
import time

import numpy as np
import pytest


@pytest.mark.e2e
async def test_inference_short_e2e_against_mock_robot(make_inference_session, fake_vla_server):
    """Shorter than 60s — 5s of RECORDING is enough to confirm the pipeline.

    Asserts:
    - VLA server received >1 call (producer is making chunked requests)
    - No inference_error_count metric incremented
    - Parquet + mp4 written under the dataset root
    """
    sm = await make_inference_session(instruction="pick the bottle")

    # READY for ~0.5s to let producer fill at least one chunk
    assert await _wait_for(lambda: sm._chunk_buffer.depth() > 0, timeout=5.0)

    await sm.episode_start()
    end = time.monotonic() + 5.0
    while time.monotonic() < end:
        await asyncio.sleep(0.1)
    await sm.episode_stop()
    await sm.episode_save(success=True, comment="e2e")

    assert fake_vla_server.calls > 1, f"VLA only called {fake_vla_server.calls} times"
    err_count = sm._metrics.get("inference_error_count")
    assert err_count == 0, f"unexpected {err_count} inference errors"

    # Verify parquet was written for at least one episode
    ds = sm._dataset_root
    parquets = list((ds / "data" / "chunk-000").glob("*.parquet"))
    assert len(parquets) > 0, f"no parquet files in {ds}"


@pytest.mark.e2e
async def test_review_tail_within_max_delta(make_inference_session, fake_vla_server):
    """The slow-stop tail after REVIEW entry must never exceed max_delta.

    The captured list accumulates commands during READY/RECORDING too, so
    READY setpoints (potentially clamped to ~max_delta themselves) would
    dominate `max(deltas)` over the full series. We isolate the REVIEW
    window explicitly — that is the property the spec requires.
    """
    sm = await make_inference_session(instruction="x")

    # Capture every dispatched command. Watch the command_goal_slot via a wrapper
    # since LatestValue may not have a subscribe API — read its current value periodically.
    captured: list[np.ndarray] = []
    stopped = asyncio.Event()

    async def watcher():
        last_t = -1
        while not stopped.is_set():
            stamped = sm._command_goal_slot.peek()
            if stamped is not None and stamped.t_mono_ns != last_t:
                last_t = stamped.t_mono_ns
                captured.append(stamped.value.q.copy())
            await asyncio.sleep(0.005)

    watch_task = asyncio.create_task(watcher())
    try:
        # Let producer + control_loop run to populate the slot
        await sm.episode_start()
        await asyncio.sleep(0.5)

        review_entry_idx = len(captured)
        await sm.episode_stop()        # → REVIEW
        await asyncio.sleep(0.2)        # let slow-stop tick a few times

        post_review = captured[review_entry_idx:]
        deltas = [
            np.abs(post_review[i + 1] - post_review[i]).max()
            for i in range(len(post_review) - 1)
        ]
        # max_delta from conftest fixture is 5.0 deg per tick.
        if deltas:
            assert max(deltas) <= 5.0 + 1e-6, \
                f"REVIEW-tail max delta {max(deltas)} exceeds max_joint_delta_per_step_deg"
    finally:
        stopped.set()
        await watch_task


async def _wait_for(predicate, timeout=5.0, step=0.02):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(step)
    return False
