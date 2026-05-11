import asyncio
import pytest

from mimicrec.gopro.dl_queue import DLQueue
from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.gopro.recorder import GoProRecorder
from mimicrec.recording.dataset_layout import dataset_paths
from mimicrec.util.error_bus import ErrorBus


@pytest.fixture
def paths(tmp_path):
    p = dataset_paths(tmp_path / "ds")
    for d in (p.meta_dir, p.pending_dir, p.videos_dir):
        d.mkdir(parents=True, exist_ok=True)
    return p


@pytest.mark.asyncio
async def test_recorder_writes_slot_into_sidecar(paths):
    """Slot must be written as cam_name, NOT device.name. The slot is
    the dataset key; the device's yaml name is the physical adapter
    identity (used for logging / USB ops) and must not leak into the
    DL pipeline."""
    d = MockGoProDevice(name="gopro_external", usb_serial="S1")
    await d.connect()
    queue = DLQueue(paths.pending_dir / "gopro_dl")
    r = GoProRecorder(d, queue, paths, ErrorBus(), slot="front")

    await r.start_episode(0, t_host_mono_ns=0)
    await r.stop_episode(0)

    job = await asyncio.wait_for(queue.dequeue(), timeout=1.0)
    assert job.cam_name == "front", (
        f"sidecar cam_name must be the slot, got {job.cam_name!r}"
    )
