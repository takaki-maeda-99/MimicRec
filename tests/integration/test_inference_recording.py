import asyncio
import pytest


async def test_inference_recording_round_trip():
    """start session → episode_start → tick → episode_stop → save(success=True).
    Verify: parquet rows, mp4, tasks.parquet has instruction, episodes.jsonl has 3 new columns."""
    pytest.skip("complete after Task 26 (make_inference_session + fake_vla_server fixtures)")


async def test_max_episode_seconds_watchdog_fires():
    """watchdog auto-fires episode_stop after max_episode_seconds; expect state=review and watchdog_timeout WS event."""
    pytest.skip("complete after Task 26")
