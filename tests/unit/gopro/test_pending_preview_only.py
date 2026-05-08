from pathlib import Path
import numpy as np
import pytest

from mimicrec.recording.pending import PendingEpisode
from mimicrec.types import Frame, Stamped


def _frame(preview_only: bool = False) -> Stamped[Frame]:
    img = np.zeros((48, 64, 3), dtype=np.uint8)
    return Stamped(value=Frame(image=img, preview_only=preview_only), t_mono_ns=0)


@pytest.mark.asyncio
async def test_preview_only_skips_video_write_but_appends_row(tmp_path: Path) -> None:
    pe = PendingEpisode.open(tmp_path, episode_index=0)
    pe.open_video_writers(fps=30, cameras={"g_preview": (64, 48)})  # writer exists
    pe.append_row(
        {"timestamp": 0.0, "frame_index": 0, "episode_index": 0, "index": 0, "task_index": 0},
        frames={"g_preview": _frame(preview_only=True)},
    )
    pe.finalize()
    mp4 = tmp_path / ".pending" / "ep_000000" / "g_preview.mp4"
    assert mp4.exists()
    assert mp4.stat().st_size < 4 * 1024  # 0 frames written


@pytest.mark.asyncio
async def test_realtime_frame_writes_normally(tmp_path: Path) -> None:
    pe = PendingEpisode.open(tmp_path, episode_index=0)
    pe.open_video_writers(fps=30, cameras={"realtime": (64, 48)})
    for i in range(5):
        pe.append_row(
            {"timestamp": i / 30.0, "frame_index": i, "episode_index": 0, "index": i, "task_index": 0},
            frames={"realtime": _frame(preview_only=False)},
        )
    pe.finalize()
    mp4 = tmp_path / ".pending" / "ep_000000" / "realtime.mp4"
    assert mp4.stat().st_size > 1000
