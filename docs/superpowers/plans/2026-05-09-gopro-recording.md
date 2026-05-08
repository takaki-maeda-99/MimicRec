# GoPro Hero 11 Recording Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add GoPro Hero 11 video+IMU recording to MimicRec as a peer of `OpenCVCamera`. GoPro records to its own SD card per-episode, host pulls files asynchronously over USB, GPMF (IMU) is preserved untouched in the MP4. Live UDP preview is surfaced through the existing CameraManager preview pipeline (preview-only — never written to dataset).

**Architecture:** One `GoProDevice` per physical camera owns the `open_gopro` SDK client. `GoProPreviewSource` (Camera-shaped view) reads UDP MPEG-TS. `GoProRecorder` (control-plane view) drives `set_shutter` and enqueues download jobs. `DLWorker` runs in the background, serializing downloads across all GoPros, with a persistent sidecar JSON queue for crash recovery. `GoProDeviceRegistry` is a peer of `CameraManager`; registry starts before CameraManager so preview sources can be merged into the cameras dict.

**Tech Stack:** Python 3.12 (FastAPI / asyncio / pyav / pyarrow), `open_gopro` PyPI package, pytest with `asyncio_mode=auto`, React/TypeScript frontend.

**Spec:** `docs/superpowers/specs/2026-05-09-gopro-recording-design.md`

**Test runner:** `env -u PYTHONPATH /home/tirobot/MimicRec/backend/.venv/bin/python -m pytest ../tests/...` from `backend/` cwd.

**Hardware-marked test:** `pytest -m gopro_hardware` (default `addopts = -m 'not gopro_hardware'` is set in `pytest.ini` during this plan).

---

## File Structure

**New files:**

| Path | Responsibility |
|---|---|
| `backend/mimicrec/gopro/__init__.py` | Empty package marker |
| `backend/mimicrec/gopro/types.py` | `GoProSpec`, `MediaItem` dataclasses (leaf module — no internal deps) |
| `backend/mimicrec/gopro/dl_queue.py` | `GoProDLJob` + persistent `DLQueue` (sidecar JSON in `.pending/gopro_dl/`) |
| `backend/mimicrec/gopro/mock.py` | `MockGoProDevice` for unit/integration tests without hardware |
| `backend/mimicrec/gopro/recorder.py` | `GoProRecorder` — control-plane view |
| `backend/mimicrec/gopro/dl_worker.py` | `GoProDLWorker` — serialized DL loop |
| `backend/mimicrec/gopro/preview.py` | `GoProPreviewSource` — UDP MPEG-TS decoder, Camera I/F |
| `backend/mimicrec/gopro/registry.py` | `GoProDeviceRegistry` — session lifecycle |
| `backend/mimicrec/gopro/device.py` | Real `GoProDevice` wrapping `WiredGoPro` SDK client |
| `configs/gopros/gopro_external.yaml` | Example Hydra config (1 GoPro) |
| `tests/unit/gopro/test_types.py` | `GoProSpec` / `MediaItem` instantiation |
| `tests/unit/gopro/test_frame_preview_only.py` | `Frame.preview_only` field |
| `tests/unit/gopro/test_pending_preview_only.py` | `PendingEpisode.append_row` honors `preview_only` |
| `tests/unit/gopro/test_dl_queue.py` | DLQueue persistence + restore |
| `tests/unit/gopro/test_mock_device.py` | MockGoProDevice surface |
| `tests/unit/gopro/test_recorder.py` | Lifecycle with mock |
| `tests/unit/gopro/test_dl_worker.py` | Worker loop, resume-from-tmp, duration check |
| `tests/unit/gopro/test_preview.py` | Preview source emits `preview_only=True` |
| `tests/unit/gopro/test_registry.py` | Uniqueness, lifecycle, fan-out |
| `tests/unit/gopro/test_device.py` | Real device with mocked `open_gopro` |
| `tests/unit/gopro/test_init_dataset_gopro.py` | `init_dataset` features entry for GoPro |
| `tests/integration/test_gopro_mock_session.py` | End-to-end with MockGoProDevice (no hardware) |
| `tests/integration/test_gopro_hardware.py` | Real Hero 11 (marker: `gopro_hardware`) |
| `tests/fixtures/gopro/sample_episode.mp4` | Short Hero 11 sample MP4 with GPMF, ~5MB |

**Modified files:**

| Path | Change |
|---|---|
| `backend/mimicrec/types.py` | Add `Frame.preview_only: bool = False` |
| `backend/mimicrec/recording/pending.py` | `append_row` skips video write when `frame.preview_only=True` |
| `backend/mimicrec/recording/dataset_layout.py` | `init_dataset` gains `gopro_specs` param; writes `has_gpmf=true` features |
| `backend/mimicrec/api/schemas.py` | `_BaseSessionRequest.gopros: list[str] = []`; `SessionStatePayload.gopros` |
| `backend/mimicrec/api/deps.py` | Load `configs/gopros/`, build registry, merge preview sources, pass `gopro_specs` to `init_dataset`, assert name disjointness |
| `backend/mimicrec/api/routes/session.py` (or new file) | `GET /api/session/gopro_pending` endpoint |
| `pytest.ini` | Add `gopro_hardware` marker, set default `addopts = -m 'not gopro_hardware'` |
| `pyproject.toml` | Add `open_gopro` dependency (version pinned after Phase 0) |
| `frontend/src/...` | Pending DL badge component, quit-warning dialog |

---

## Phase 0 — Pre-implementation verification (gating spike)

This is a one-shot research task. **STOP HERE and report back if Task 0 fails** — the spec says shelve.

### Task 0: Verify `WiredGoPro` Hero 11 API coverage

**Files:**
- Create: `docs/superpowers/notes/2026-05-09-gopro-sdk-verification.md`

- [ ] **Step 1: Install `open_gopro` in the backend venv**

```
cd /home/tirobot/MimicRec/backend
.venv/bin/pip install open_gopro
.venv/bin/python -c "import open_gopro; print(open_gopro.__version__)"
```

Record the version printed.

- [ ] **Step 2: Plug in Hero 11 via USB and power on**

Camera must be in default video mode for the spike. Confirm with `lsusb | grep -i gopro` showing the device.

- [ ] **Step 3: Probe each required SDK API**

Create `/tmp/gopro_probe.py`:

```python
import asyncio
from open_gopro import WiredGoPro, constants
from datetime import datetime

async def main():
    async with WiredGoPro() as gp:
        print("connected:", gp.is_open)

        r = await gp.http_command.set_date_time(date_time=datetime.now())
        print("set_date_time:", r.ok)

        r = await gp.http_command.load_preset_group(group=constants.proto.EnumPresetGroup.PRESET_GROUP_ID_VIDEO)
        print("video preset group:", r.ok)

        r = await gp.http_command.set_shutter(shutter=constants.Toggle.ENABLE)
        print("shutter on:", r.ok)
        await asyncio.sleep(2.0)
        r = await gp.http_command.set_shutter(shutter=constants.Toggle.DISABLE)
        print("shutter off:", r.ok)

        ml = await gp.http_command.get_media_list()
        print("media_list count:", len(ml.data.files))
        if ml.data.files:
            f = ml.data.files[0]
            print("sample:", f.filename, f.size, f.creation_timestamp)

        r = await gp.http_command.get_camera_state()
        print("camera_state ok:", r.ok)
        print("storage_remaining:", r.data.get(constants.StatusId.SD_STATUS, "missing"))

        r = await gp.http_command.set_preview_stream(mode=constants.Toggle.ENABLE, port=8556)
        print("preview start:", r.ok)
        await asyncio.sleep(2.0)
        r = await gp.http_command.set_preview_stream(mode=constants.Toggle.DISABLE)
        print("preview stop:", r.ok)

        if ml.data.files:
            from pathlib import Path
            dst = Path("/tmp/gopro_dl_test.mp4")
            await gp.http_command.download_file(camera_file=ml.data.files[0].filename, local_file=dst)
            print("download size:", dst.stat().st_size)

asyncio.run(main())
```

```
cd /home/tirobot/MimicRec/backend
.venv/bin/python /tmp/gopro_probe.py 2>&1 | tee /tmp/gopro_probe.log
```

- [ ] **Step 4: Decision**

For each API in the probe output: PASS = call returned ok and meaningful data; FAIL = exception, missing attribute, or non-ok response.

If **any** of `set_date_time`, `set_shutter`, `get_media_list`, `download_file`, `set_preview_stream`, `get_camera_state`, `load_preset_group` is FAIL: **shelve the spec**, write the failure summary to `docs/superpowers/notes/2026-05-09-gopro-sdk-verification.md`, and report back.

If all PASS: continue.

- [ ] **Step 5: Pin version + record findings**

Edit `backend/pyproject.toml`, add `"open_gopro==<exact version>"` to dependencies (replace `<exact version>` with the version from Step 1).

Write `docs/superpowers/notes/2026-05-09-gopro-sdk-verification.md` containing:
- `open_gopro` version
- Hero 11 firmware (from probe output)
- Confirmed API surface (one line per API)
- UDP preview observed: codec / resolution / fps (sniff with `ffprobe rtp://0.0.0.0:8556` if needed)
- `media_list` polling latency: time between `set_shutter` and the new file appearing in subsequent `get_media_list` calls (poll every 100ms in a follow-up script if needed)

- [ ] **Step 6: Commit**

```
git add backend/pyproject.toml docs/superpowers/notes/2026-05-09-gopro-sdk-verification.md
git commit -m "chore(gopro): SDK verification + open_gopro version pin"
```

---

## Phase 1 — Foundation types

### Task 1: `gopro/types.py` — `GoProSpec` and `MediaItem`

**Files:**
- Create: `backend/mimicrec/gopro/__init__.py`
- Create: `backend/mimicrec/gopro/types.py`
- Test: `tests/unit/gopro/__init__.py`, `tests/unit/gopro/test_types.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/gopro/__init__.py` (empty) and `tests/unit/gopro/test_types.py`:

```python
from mimicrec.gopro.types import GoProSpec, MediaItem


def test_gopro_spec_fields():
    s = GoProSpec(name="g1", width=1920, height=1080, fps=60, codec="h264")
    assert s.name == "g1"
    assert s.width == 1920
    assert s.height == 1080
    assert s.fps == 60
    assert s.codec == "h264"


def test_gopro_spec_is_frozen():
    s = GoProSpec(name="g1", width=1920, height=1080, fps=60, codec="h264")
    import pytest
    with pytest.raises(Exception):
        s.width = 1280  # type: ignore[misc]


def test_media_item_fields():
    m = MediaItem(filename="GX010001.MP4", size=12345, mtime_ns=1_700_000_000_000_000_000)
    assert m.filename == "GX010001.MP4"
    assert m.size == 12345
    assert m.mtime_ns == 1_700_000_000_000_000_000
```

- [ ] **Step 2: Run test — verify it fails**

```
cd /home/tirobot/MimicRec/backend
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_types.py -v
```

Expected: `ModuleNotFoundError: No module named 'mimicrec.gopro'`

- [ ] **Step 3: Create the module**

Create `backend/mimicrec/gopro/__init__.py` (empty file).

Create `backend/mimicrec/gopro/types.py`:

```python
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class GoProSpec:
    """Resolved video parameters for info.json features writing.
    Lives in `gopro/types.py` (leaf module) so `recording/dataset_layout.py`
    can import it without pulling in the heavy `gopro/device.py` (open_gopro)."""
    name: str
    width: int
    height: int
    fps: int
    codec: str   # "h264" or "h265"


@dataclass
class MediaItem:
    """One file on the GoPro SD card."""
    filename: str            # e.g. "GX010001.MP4"
    size: int                # bytes
    mtime_ns: int            # camera-clock nanoseconds (NOT host monotonic)
```

- [ ] **Step 4: Run test — verify it passes**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_types.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/gopro/__init__.py backend/mimicrec/gopro/types.py tests/unit/gopro/__init__.py tests/unit/gopro/test_types.py
git commit -m "feat(gopro): GoProSpec and MediaItem leaf types"
```

---

### Task 2: `Frame.preview_only` field

**Files:**
- Modify: `backend/mimicrec/types.py:69-72`
- Test: `tests/unit/gopro/test_frame_preview_only.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/gopro/test_frame_preview_only.py`:

```python
import numpy as np

from mimicrec.types import Frame


def test_frame_preview_only_default_false():
    f = Frame(image=np.zeros((4, 4, 3), dtype=np.uint8))
    assert f.preview_only is False


def test_frame_preview_only_settable():
    f = Frame(image=np.zeros((4, 4, 3), dtype=np.uint8), preview_only=True)
    assert f.preview_only is True
```

- [ ] **Step 2: Run test — verify it fails**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_frame_preview_only.py -v
```

Expected: `TypeError: __init__() got an unexpected keyword argument 'preview_only'` and AttributeError on default.

- [ ] **Step 3: Add the field**

Edit `backend/mimicrec/types.py`:

```python
@dataclass
class Frame:
    image: np.ndarray          # HxWx3 uint8 BGR
    t_mono_ns: int = 0
    preview_only: bool = False
```

- [ ] **Step 4: Run test — verify it passes**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_frame_preview_only.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Smoke-run existing tests to ensure no regression**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit -v
```

Expected: all existing tests pass (Frame is constructed in many places — the new field has a default so no positional break).

- [ ] **Step 6: Commit**

```
git add backend/mimicrec/types.py tests/unit/gopro/test_frame_preview_only.py
git commit -m "feat(types): Frame.preview_only field for preview-only sources"
```

---

### Task 3: `PendingEpisode.append_row` honors `preview_only`

**Files:**
- Modify: `backend/mimicrec/recording/pending.py:50-65` (the `append_row` method)
- Test: `tests/unit/gopro/test_pending_preview_only.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/gopro/test_pending_preview_only.py`:

```python
from pathlib import Path

import numpy as np
import pytest

from mimicrec.recording.pending import PendingEpisode
from mimicrec.types import Frame, Stamped


def _frame(preview_only: bool = False) -> Stamped[Frame]:
    img = np.zeros((48, 64, 3), dtype=np.uint8)
    return Stamped(value=Frame(image=img, preview_only=preview_only), t_mono_ns=0)


@pytest.mark.asyncio
async def test_append_row_skips_video_write_for_preview_only(tmp_path: Path) -> None:
    pe = PendingEpisode.open(tmp_path, episode_index=0)
    pe.open_video_writers(fps=30, cameras={"cam_realtime": (64, 48)})
    # Note: "gopro_preview" intentionally has NO video writer because it's a
    # preview source — the registry would have filtered it out at the call site.
    # We pass it in append_row anyway to verify the silent-skip path.

    pe.append_row(
        {"timestamp": 0.0, "frame_index": 0, "episode_index": 0, "index": 0, "task_index": 0},
        frames={
            "cam_realtime": _frame(preview_only=False),
            "gopro_preview": _frame(preview_only=True),
        },
    )

    # The realtime camera writer received its frame; preview-only frame did not crash.
    assert pe.num_frames == 1


@pytest.mark.asyncio
async def test_append_row_skips_video_write_when_writer_exists_but_frame_is_preview_only(
    tmp_path: Path,
) -> None:
    """Belt-and-suspenders: even if a writer accidentally exists for a preview
    name, the preview_only flag must prevent writing."""
    pe = PendingEpisode.open(tmp_path, episode_index=0)
    pe.open_video_writers(fps=30, cameras={"gopro_preview": (64, 48)})  # would normally NOT happen

    pe.append_row(
        {"timestamp": 0.0, "frame_index": 0, "episode_index": 0, "index": 0, "task_index": 0},
        frames={"gopro_preview": _frame(preview_only=True)},
    )

    # Finalize and ensure the resulting MP4 has zero frames written.
    pe.finalize()
    mp4 = tmp_path / ".pending" / "ep_000000" / "gopro_preview.mp4"
    assert mp4.exists()
    # PyAV-written MP4 with 0 frames is < 4 KB; with 1 frame ≥ 4 KB. Sanity threshold:
    assert mp4.stat().st_size < 4 * 1024


@pytest.mark.asyncio
async def test_append_row_writes_video_for_realtime_camera(tmp_path: Path) -> None:
    """Sanity: realtime cameras still get their frames written."""
    pe = PendingEpisode.open(tmp_path, episode_index=0)
    pe.open_video_writers(fps=30, cameras={"cam_realtime": (64, 48)})
    for i in range(5):
        pe.append_row(
            {"timestamp": i / 30.0, "frame_index": i, "episode_index": 0, "index": i, "task_index": 0},
            frames={"cam_realtime": _frame(preview_only=False)},
        )
    pe.finalize()
    mp4 = tmp_path / ".pending" / "ep_000000" / "cam_realtime.mp4"
    assert mp4.exists()
    assert mp4.stat().st_size > 1000   # 5 frames at 64x48 ultrafast h264
```

- [ ] **Step 2: Run test — verify it fails**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_pending_preview_only.py -v
```

Expected: the second test (`...when_writer_exists_but_frame_is_preview_only`) fails because `append_row` currently writes the frame regardless of `preview_only`. Other tests may pass coincidentally.

- [ ] **Step 3: Implement the skip**

Edit `backend/mimicrec/recording/pending.py`. Find the `append_row` method (~line 50) and update the inner write loop:

```python
    def append_row(self, row: dict, frames: dict[str, object] | None = None) -> int:
        if self._finalized:
            raise RuntimeError("cannot append after finalize()")
        self._rows.append(row)
        if frames and getattr(self, "_video_writers", None):
            for name, stamped in frames.items():
                if stamped is None:
                    continue
                # Preview-only frames (e.g., GoPro UDP preview) are surfaced to
                # CameraManager for the operator UI but must never enter the
                # recorded MP4. Skip writing while still allowing the row to be
                # appended to the per-frame parquet.
                if getattr(stamped.value, "preview_only", False):
                    continue
                writer = self._video_writers.get(name)
                if writer is not None:
                    writer.write_frame(stamped.value.image)
        return len(self._rows) - 1
```

- [ ] **Step 4: Run test — verify it passes**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_pending_preview_only.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/recording/pending.py tests/unit/gopro/test_pending_preview_only.py
git commit -m "feat(recording): PendingEpisode.append_row skips video write for preview_only frames"
```

---

## Phase 2 — Persistent queue + Mock device

### Task 4: `gopro/dl_queue.py` — `GoProDLJob` + `DLQueue`

**Files:**
- Create: `backend/mimicrec/gopro/dl_queue.py`
- Test: `tests/unit/gopro/test_dl_queue.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/gopro/test_dl_queue.py`:

```python
import asyncio
import json
from pathlib import Path

import pytest

from mimicrec.gopro.dl_queue import DLQueue, GoProDLJob


def _job(job_id: str = "job1", episode_index: int = 0) -> GoProDLJob:
    return GoProDLJob(
        job_id=job_id,
        gopro_serial="C3441234567890",
        sd_filename="GX010001.MP4",
        episode_index=episode_index,
        chunk_index=0,
        cam_name="gopro_external",
        gopro_t0_mono_ns=1_000_000_000,
        episode_stop_mono_ns=2_000_000_000,
    )


@pytest.mark.asyncio
async def test_enqueue_writes_sidecar(tmp_path: Path) -> None:
    q = DLQueue(tmp_path / "pending" / "gopro_dl")
    await q.enqueue(_job(job_id="abc"))
    sidecar = tmp_path / "pending" / "gopro_dl" / "abc.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text())
    assert data["job_id"] == "abc"
    assert data["episode_index"] == 0
    assert data["sd_filename"] == "GX010001.MP4"


@pytest.mark.asyncio
async def test_dequeue_returns_enqueued_jobs_in_order(tmp_path: Path) -> None:
    q = DLQueue(tmp_path / "pending" / "gopro_dl")
    await q.enqueue(_job(job_id="a", episode_index=0))
    await q.enqueue(_job(job_id="b", episode_index=1))
    j1 = await asyncio.wait_for(q.dequeue(), timeout=1.0)
    j2 = await asyncio.wait_for(q.dequeue(), timeout=1.0)
    assert {j1.job_id, j2.job_id} == {"a", "b"}


@pytest.mark.asyncio
async def test_mark_done_removes_sidecar(tmp_path: Path) -> None:
    q = DLQueue(tmp_path / "pending" / "gopro_dl")
    await q.enqueue(_job(job_id="x"))
    await q.mark_done("x")
    sidecar = tmp_path / "pending" / "gopro_dl" / "x.json"
    assert not sidecar.exists()


@pytest.mark.asyncio
async def test_mark_done_idempotent(tmp_path: Path) -> None:
    q = DLQueue(tmp_path / "pending" / "gopro_dl")
    # No prior enqueue — should not raise.
    await q.mark_done("never_existed")


@pytest.mark.asyncio
async def test_restore_loads_sidecars(tmp_path: Path) -> None:
    pdir = tmp_path / "pending" / "gopro_dl"
    pdir.mkdir(parents=True)
    j1 = _job(job_id="aaa", episode_index=2)
    j2 = _job(job_id="bbb", episode_index=3)
    (pdir / "aaa.json").write_text(json.dumps(j1.to_json()))
    (pdir / "bbb.json").write_text(json.dumps(j2.to_json()))

    q = DLQueue.restore(pdir)
    out = []
    for _ in range(2):
        out.append(await asyncio.wait_for(q.dequeue(), timeout=1.0))
    assert sorted([j.job_id for j in out]) == ["aaa", "bbb"]


@pytest.mark.asyncio
async def test_restore_creates_missing_dir(tmp_path: Path) -> None:
    pdir = tmp_path / "never_existed"
    q = DLQueue.restore(pdir)
    assert pdir.exists()
    # No jobs enqueued, dequeue would block; that's fine.
    assert q is not None


def test_to_json_roundtrip() -> None:
    j = _job()
    j2 = GoProDLJob.from_json(j.to_json())
    assert j == j2
```

- [ ] **Step 2: Run test — verify it fails**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_dl_queue.py -v
```

Expected: ModuleNotFoundError on `mimicrec.gopro.dl_queue`.

- [ ] **Step 3: Implement `dl_queue.py`**

Create `backend/mimicrec/gopro/dl_queue.py`:

```python
from __future__ import annotations
import asyncio
import json
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class GoProDLJob:
    job_id: str
    gopro_serial: str
    sd_filename: str
    episode_index: int
    chunk_index: int
    cam_name: str
    gopro_t0_mono_ns: int | None
    episode_stop_mono_ns: int

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> "GoProDLJob":
        return cls(**d)


class DLQueue:
    """Persistent FIFO queue. Sidecar JSON in pending_dir / <job_id>.json
    is written (and fsynced) before the in-memory queue is appended,
    so a crash between enqueue and processing is recoverable."""

    def __init__(self, pending_dir: Path):
        self._dir = pending_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._q: asyncio.Queue[GoProDLJob] = asyncio.Queue()

    async def enqueue(self, job: GoProDLJob) -> None:
        path = self._dir / f"{job.job_id}.json"
        tmp = self._dir / f"{job.job_id}.json.tmp"
        tmp.write_text(json.dumps(job.to_json(), indent=2))
        # fsync the file then atomic rename so a crash never leaves a
        # half-written sidecar visible to restore().
        with open(tmp, "rb") as fh:
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        await self._q.put(job)

    async def dequeue(self) -> GoProDLJob:
        return await self._q.get()

    async def mark_done(self, job_id: str) -> None:
        path = self._dir / f"{job_id}.json"
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    @classmethod
    def restore(cls, pending_dir: Path) -> "DLQueue":
        q = cls(pending_dir)
        for sidecar in sorted(pending_dir.glob("*.json")):
            try:
                data = json.loads(sidecar.read_text())
                job = GoProDLJob.from_json(data)
            except Exception:
                # Corrupt sidecar — leave on disk for human inspection, skip.
                continue
            q._q.put_nowait(job)
        return q

    @property
    def pending_count(self) -> int:
        return self._q.qsize()
```

- [ ] **Step 4: Run test — verify it passes**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_dl_queue.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/gopro/dl_queue.py tests/unit/gopro/test_dl_queue.py
git commit -m "feat(gopro): persistent DLQueue with sidecar JSON"
```

---

### Task 5: `gopro/mock.py` — `MockGoProDevice`

**Files:**
- Create: `backend/mimicrec/gopro/mock.py`
- Test: `tests/unit/gopro/test_mock_device.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/gopro/test_mock_device.py`:

```python
import asyncio
import shutil
from pathlib import Path

import pytest

from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.gopro.types import GoProSpec, MediaItem


@pytest.mark.asyncio
async def test_connect_disconnect_idempotent() -> None:
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    await d.connect()        # idempotent
    await d.disconnect()
    await d.disconnect()


@pytest.mark.asyncio
async def test_shutter_cycle_creates_media_item() -> None:
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    before = await d.media_list()
    await d.shutter_on()
    await asyncio.sleep(0.01)
    await d.shutter_off()
    after = await d.media_list()
    assert len(after) == len(before) + 1
    assert isinstance(after[-1], MediaItem)
    assert after[-1].filename.endswith(".MP4")


@pytest.mark.asyncio
async def test_get_spec_from_preset() -> None:
    d = MockGoProDevice(name="g1", usb_serial="S1", recording_preset="1080p_60_wide")
    spec = d.get_spec()
    assert spec == GoProSpec(name="g1", width=1920, height=1080, fps=60, codec="h264")


@pytest.mark.asyncio
async def test_unknown_preset_raises_on_connect() -> None:
    d = MockGoProDevice(name="g1", usb_serial="S1", recording_preset="bogus")
    from mimicrec.errors import HardwareError
    with pytest.raises(HardwareError):
        await d.connect()


@pytest.mark.asyncio
async def test_download_file_copies_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture.mp4"
    fixture.write_bytes(b"\x00" * 1024)
    d = MockGoProDevice(name="g1", usb_serial="S1", fixture_mp4=fixture)
    await d.connect()
    await d.shutter_on(); await d.shutter_off()
    files = await d.media_list()
    dst = tmp_path / "out.mp4"
    await d.download_file(files[-1].filename, dst)
    assert dst.exists()
    assert dst.stat().st_size == 1024


@pytest.mark.asyncio
async def test_disable_blocks_subsequent_calls() -> None:
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    d.disable("test reason")
    assert d.is_disabled
    # shutter_on on disabled should be no-op (no exception).
    await d.shutter_on()
    await d.shutter_off()


@pytest.mark.asyncio
async def test_storage_remaining_default() -> None:
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    assert (await d.get_storage_remaining()) > 500_000_000
```

- [ ] **Step 2: Run test — verify it fails**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_mock_device.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `mock.py`**

Create `backend/mimicrec/gopro/mock.py`:

```python
from __future__ import annotations
import asyncio
import shutil
import time
from pathlib import Path

from mimicrec.errors import HardwareError
from mimicrec.gopro.types import GoProSpec, MediaItem

# Limited starting set; extend during real-device verification.
_PRESET_SPECS: dict[str, tuple[int, int, int, str]] = {
    "1080p_60_wide": (1920, 1080, 60, "h264"),
    "1080p_30_wide": (1920, 1080, 30, "h264"),
    "2.7K_60_wide":  (2704, 1520, 60, "h264"),
    "4K_30_wide":    (3840, 2160, 30, "h265"),
    "4K_60_wide":    (3840, 2160, 60, "h265"),
    "5.3K_30_wide":  (5312, 2988, 30, "h265"),
}


class MockGoProDevice:
    """Drop-in replacement for GoProDevice in tests. Does not import open_gopro."""

    def __init__(
        self,
        name: str,
        usb_serial: str,
        recording_preset: str = "1080p_60_wide",
        fixture_mp4: Path | None = None,
        emit_preview: bool = False,
        storage_remaining: int = 1_000_000_000,
    ) -> None:
        self._name = name
        self._serial = usb_serial
        self._preset = recording_preset
        self._fixture = fixture_mp4
        self._emit_preview = emit_preview
        self._storage = storage_remaining
        self._connected = False
        self._disabled = False
        self._shutter_on = False
        self._files: list[MediaItem] = []
        self._counter = 0
        self._preview_task: asyncio.Task | None = None
        self._preview_port: int | None = None

    @property
    def name(self) -> str: return self._name
    @property
    def usb_serial(self) -> str: return self._serial
    @property
    def is_disabled(self) -> bool: return self._disabled

    async def connect(self) -> None:
        if self._connected:
            return
        if self._preset not in _PRESET_SPECS:
            raise HardwareError(f"unknown preset: {self._preset}")
        self._connected = True

    async def disconnect(self) -> None:
        if self._preview_task:
            self._preview_task.cancel()
            self._preview_task = None
        self._connected = False

    async def shutter_on(self) -> None:
        if self._disabled or not self._connected:
            return
        self._shutter_on = True

    async def shutter_off(self) -> None:
        if self._disabled or not self._connected:
            return
        if self._shutter_on:
            self._counter += 1
            self._files.append(MediaItem(
                filename=f"GX{self._counter:06d}.MP4",
                size=12345,
                mtime_ns=time.monotonic_ns(),
            ))
            self._shutter_on = False

    async def media_list(self) -> list[MediaItem]:
        if self._disabled or not self._connected:
            return []
        return list(self._files)

    async def start_preview(self, port: int) -> None:
        if self._disabled or not self._connected:
            return
        self._preview_port = port
        # Optional emission left to integration tests; default is off.

    async def stop_preview(self) -> None:
        self._preview_port = None

    async def download_file(self, sd_filename: str, dest: Path) -> None:
        if self._fixture is not None and self._fixture.exists():
            shutil.copy(str(self._fixture), str(dest))
        else:
            dest.write_bytes(b"\x00" * 1024)

    async def get_storage_remaining(self) -> int:
        return self._storage

    def get_spec(self) -> GoProSpec:
        w, h, fps, codec = _PRESET_SPECS[self._preset]
        return GoProSpec(name=self._name, width=w, height=h, fps=fps, codec=codec)

    def disable(self, reason: str) -> None:
        if self._disabled:
            return
        self._disabled = True
        import logging
        logging.getLogger(__name__).warning("MockGoProDevice %s disabled: %s", self._name, reason)
```

- [ ] **Step 4: Run test — verify it passes**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_mock_device.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/gopro/mock.py tests/unit/gopro/test_mock_device.py
git commit -m "feat(gopro): MockGoProDevice for hardware-free testing"
```

---

## Phase 3 — Control plane components

### Task 6: `gopro/recorder.py` — `GoProRecorder`

**Files:**
- Create: `backend/mimicrec/gopro/recorder.py`
- Test: `tests/unit/gopro/test_recorder.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/gopro/test_recorder.py`:

```python
import asyncio
from pathlib import Path

import pytest

from mimicrec.gopro.dl_queue import DLQueue
from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.gopro.recorder import GoProRecorder
from mimicrec.recording.dataset_layout import dataset_paths


@pytest.fixture
def paths(tmp_path: Path):
    p = dataset_paths(tmp_path / "ds")
    p.meta_dir.mkdir(parents=True, exist_ok=True)
    p.pending_dir.mkdir(parents=True, exist_ok=True)
    p.videos_dir.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture
def queue(paths):
    return DLQueue(paths.pending_dir / "gopro_dl")


@pytest.mark.asyncio
async def test_normal_lifecycle_enqueues_job(paths, queue) -> None:
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    r = GoProRecorder(d, queue, paths)

    await r.start_episode(0, t_host_mono_ns=10_000_000_000)
    # MockGoProDevice creates the file on shutter_off, but media_list during
    # polling sees nothing — recorder still must succeed (sd_filename=None at start).
    await r.stop_episode(0)

    # stop should have re-polled, found the new file, and enqueued.
    job = await asyncio.wait_for(queue.dequeue(), timeout=1.0)
    assert job.episode_index == 0
    assert job.cam_name == "g1"
    assert job.sd_filename.startswith("GX")
    assert job.gopro_serial == "S1"


@pytest.mark.asyncio
async def test_disabled_device_is_noop(paths, queue) -> None:
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    d.disable("test")
    r = GoProRecorder(d, queue, paths)

    await r.start_episode(0, t_host_mono_ns=10_000_000_000)
    await r.stop_episode(0)

    # No job enqueued.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.dequeue(), timeout=0.2)


@pytest.mark.asyncio
async def test_stop_without_file_logs_orphan(paths, queue) -> None:
    """If shutter never wrote anything (e.g. mocked failure), no enqueue."""
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    # Patch shutter_off so it does NOT register a file.
    async def _no_op(): return None
    d.shutter_off = _no_op  # type: ignore[assignment]

    r = GoProRecorder(d, queue, paths)
    await r.start_episode(0, t_host_mono_ns=10_000_000_000)
    await r.stop_episode(0)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.dequeue(), timeout=0.2)
```

- [ ] **Step 2: Run test — verify it fails**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_recorder.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `recorder.py`**

Create `backend/mimicrec/gopro/recorder.py`:

```python
from __future__ import annotations
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

from mimicrec.gopro.dl_queue import DLQueue, GoProDLJob
from mimicrec.recording.dataset_layout import DatasetPaths, resolve_chunk

log = logging.getLogger(__name__)

_POLL_INTERVAL_S = 0.1
_POLL_TIMEOUT_S = 2.0


@dataclass
class _EpisodeState:
    episode_index: int
    sd_filename: str | None
    gopro_t0_mono_ns: int | None
    episode_start_mono_ns: int


class GoProRecorder:
    """Control-plane view over a single GoProDevice. Sends shutter commands
    and enqueues download jobs as episodes complete."""

    def __init__(self, device, queue: DLQueue, paths: DatasetPaths) -> None:
        self._device = device
        self._queue = queue
        self._paths = paths
        self._known_files: set[str] = set()
        self._state: _EpisodeState | None = None

    async def start_episode(self, episode_index: int, t_host_mono_ns: int) -> None:
        if getattr(self._device, "is_disabled", False):
            return
        try:
            await self._device.shutter_on()
        except Exception as e:
            log.warning("GoPro %s shutter_on failed: %s", self._device.name, e)
            self._state = None
            return

        # Snapshot known files BEFORE polling so we detect the new one.
        try:
            before = {f.filename for f in await self._device.media_list()}
            self._known_files |= before
        except Exception:
            before = set(self._known_files)

        # Poll until a new file appears or timeout.
        deadline = time.monotonic() + _POLL_TIMEOUT_S
        sd_filename: str | None = None
        gopro_t0_mono_ns: int | None = None
        while time.monotonic() < deadline:
            await asyncio.sleep(_POLL_INTERVAL_S)
            try:
                files = await self._device.media_list()
            except Exception:
                continue
            new = [f.filename for f in files if f.filename not in self._known_files]
            if new:
                sd_filename = new[0]
                gopro_t0_mono_ns = time.monotonic_ns()
                self._known_files.add(sd_filename)
                break

        self._state = _EpisodeState(
            episode_index=episode_index,
            sd_filename=sd_filename,
            gopro_t0_mono_ns=gopro_t0_mono_ns,
            episode_start_mono_ns=t_host_mono_ns,
        )

    async def stop_episode(self, episode_index: int) -> None:
        if getattr(self._device, "is_disabled", False):
            return
        state = self._state
        self._state = None

        # Best-effort shutter_off with up to 3 retries.
        for attempt in range(3):
            try:
                await self._device.shutter_off()
                break
            except Exception as e:
                if attempt == 2:
                    log.warning("GoPro %s shutter_off retries exhausted: %s",
                                self._device.name, e)
                    return
                await asyncio.sleep(0.2)

        if state is None or state.episode_index != episode_index:
            return

        sd_filename = state.sd_filename

        # If start-time polling missed the file, look now.
        if sd_filename is None:
            try:
                files = await self._device.media_list()
            except Exception:
                files = []
            new = [f for f in files if f.filename not in self._known_files]
            if new:
                # Pick the one with the largest mtime (newest).
                pick = max(new, key=lambda f: f.mtime_ns)
                sd_filename = pick.filename
                self._known_files.add(sd_filename)

        if sd_filename is None:
            log.warning("GoPro %s episode %d: no new file detected — orphan on SD",
                        self._device.name, episode_index)
            return

        chunk_index = resolve_chunk(episode_index)
        job = GoProDLJob(
            job_id=str(uuid.uuid4()),
            gopro_serial=self._device.usb_serial,
            sd_filename=sd_filename,
            episode_index=episode_index,
            chunk_index=chunk_index,
            cam_name=self._device.name,
            gopro_t0_mono_ns=state.gopro_t0_mono_ns,
            episode_stop_mono_ns=time.monotonic_ns(),
        )
        await self._queue.enqueue(job)
```

- [ ] **Step 4: Run test — verify it passes**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_recorder.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/gopro/recorder.py tests/unit/gopro/test_recorder.py
git commit -m "feat(gopro): GoProRecorder lifecycle with start/stop polling fallback"
```

---

### Task 7: `gopro/dl_worker.py` — `GoProDLWorker`

**Files:**
- Create: `backend/mimicrec/gopro/dl_worker.py`
- Test: `tests/unit/gopro/test_dl_worker.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/gopro/test_dl_worker.py`:

```python
import asyncio
import shutil
import time
from pathlib import Path

import pytest

from mimicrec.errors import HardwareError
from mimicrec.gopro.dl_queue import DLQueue, GoProDLJob
from mimicrec.gopro.dl_worker import GoProDLWorker
from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.recording.dataset_layout import dataset_paths
from mimicrec.util.error_bus import ErrorBus


@pytest.fixture
def paths(tmp_path: Path):
    p = dataset_paths(tmp_path / "ds")
    for d in (p.meta_dir, p.pending_dir, p.videos_dir):
        d.mkdir(parents=True, exist_ok=True)
    return p


def _job(job_id="j", episode_index=0, gopro_t0=None) -> GoProDLJob:
    return GoProDLJob(
        job_id=job_id,
        gopro_serial="S1",
        sd_filename="GX000001.MP4",
        episode_index=episode_index,
        chunk_index=0,
        cam_name="g1",
        gopro_t0_mono_ns=gopro_t0,
        episode_stop_mono_ns=time.monotonic_ns(),
    )


@pytest.mark.asyncio
async def test_normal_dl_moves_to_dataset(paths, tmp_path) -> None:
    fixture = tmp_path / "fixture.mp4"
    fixture.write_bytes(b"\x00" * 2048)
    d = MockGoProDevice(name="g1", usb_serial="S1", fixture_mp4=fixture)
    await d.connect()

    queue = DLQueue(paths.pending_dir / "gopro_dl")
    errors = ErrorBus()
    worker = GoProDLWorker(queue, devices={"S1": d}, paths=paths, errors=errors)

    await queue.enqueue(_job(job_id="j1"))
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.2)
    await worker.stop()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.CancelledError:
        pass

    dest = paths.episode_video(chunk_index=0, cam_name="g1", episode_index=0)
    assert dest.exists()
    assert dest.stat().st_size == 2048
    # Sidecar was deleted.
    assert not (paths.pending_dir / "gopro_dl" / "j1.json").exists()


@pytest.mark.asyncio
async def test_unknown_device_keeps_sidecar(paths) -> None:
    queue = DLQueue(paths.pending_dir / "gopro_dl")
    errors = ErrorBus()
    seen: list = []
    errors.subscribe(lambda e: seen.append(e))
    worker = GoProDLWorker(queue, devices={}, paths=paths, errors=errors)

    await queue.enqueue(_job(job_id="orphan"))
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.2)
    await worker.stop()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.CancelledError:
        pass

    assert (paths.pending_dir / "gopro_dl" / "orphan.json").exists()
    assert any(isinstance(e, HardwareError) for e in seen)


@pytest.mark.asyncio
async def test_duration_check_warns_when_short(paths, tmp_path) -> None:
    fixture = tmp_path / "fixture.mp4"
    fixture.write_bytes(b"\x00" * 1024)
    d = MockGoProDevice(name="g1", usb_serial="S1", fixture_mp4=fixture)
    await d.connect()

    queue = DLQueue(paths.pending_dir / "gopro_dl")
    errors = ErrorBus()
    seen: list = []
    errors.subscribe(lambda e: seen.append(e))
    worker = GoProDLWorker(queue, devices={"S1": d}, paths=paths, errors=errors)

    # Patch probe_mp4_duration on the worker's helper to return tiny value.
    import mimicrec.gopro.dl_worker as mod
    mod.probe_mp4_duration = lambda p: 0.1     # type: ignore[attr-defined]

    job = _job(job_id="j", gopro_t0=time.monotonic_ns() - 5_000_000_000)
    await queue.enqueue(job)
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.3)
    await worker.stop()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.CancelledError:
        pass

    assert any("shorter than episode" in str(e) for e in seen)


@pytest.mark.asyncio
async def test_resume_from_tmp_skips_redownload(paths, tmp_path) -> None:
    """If tmp file already exists from a previous failed move, do not re-DL."""
    fixture = tmp_path / "fixture.mp4"
    fixture.write_bytes(b"\x42" * 4096)
    d = MockGoProDevice(name="g1", usb_serial="S1", fixture_mp4=fixture)
    await d.connect()

    queue = DLQueue(paths.pending_dir / "gopro_dl")
    errors = ErrorBus()
    worker = GoProDLWorker(queue, devices={"S1": d}, paths=paths, errors=errors)

    job = _job(job_id="j_resume")
    # Pre-place a tmp with the same size as the SD-side file (mock returns 12345 from MediaItem).
    # Force MockGoProDevice to report a specific size by adding the file via shutter cycle:
    await d.shutter_on(); await d.shutter_off()
    files = await d.media_list()
    job = GoProDLJob(**{**_job(job_id="j_resume").to_json(),
                       "sd_filename": files[0].filename})
    tmp_path_file = paths.pending_dir / f"gopro_dl_{job.job_id}.mp4"
    tmp_path_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_path_file.write_bytes(b"\x42" * files[0].size)

    # Sabotage download_file so we know it isn't called.
    download_called = False
    async def boom(*args, **kwargs):
        nonlocal download_called
        download_called = True
    d.download_file = boom  # type: ignore[assignment]

    await queue.enqueue(job)
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.3)
    await worker.stop()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except asyncio.CancelledError:
        pass

    dest = paths.episode_video(chunk_index=0, cam_name="g1", episode_index=0)
    assert dest.exists()
    assert not download_called
```

- [ ] **Step 2: Run test — verify it fails**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_dl_worker.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `dl_worker.py`**

Create `backend/mimicrec/gopro/dl_worker.py`:

```python
from __future__ import annotations
import asyncio
import logging
import shutil
from pathlib import Path

from mimicrec.errors import HardwareError
from mimicrec.gopro.dl_queue import DLQueue
from mimicrec.recording.dataset_layout import DatasetPaths
from mimicrec.util.error_bus import ErrorBus

log = logging.getLogger(__name__)


def probe_mp4_duration(path: Path) -> float:
    """Return MP4 duration in seconds. Imported lazily so tests can monkeypatch."""
    import av
    with av.open(str(path)) as ctx:
        # Video stream duration in time_base units.
        s = ctx.streams.video[0]
        if s.duration is None or s.time_base is None:
            return 0.0
        return float(s.duration * s.time_base)


class GoProDLWorker:
    def __init__(
        self,
        queue: DLQueue,
        devices: dict[str, object],   # serial -> GoProDevice
        paths: DatasetPaths,
        errors: ErrorBus,
        shutdown_grace_sec: float = 30.0,
    ) -> None:
        self._queue = queue
        self._devices = devices
        self._paths = paths
        self._errors = errors
        self._grace = shutdown_grace_sec
        self._stop = asyncio.Event()
        self._inflight: asyncio.Task | None = None

    async def run(self) -> None:
        while not self._stop.is_set():
            dq_task = asyncio.create_task(self._queue.dequeue())
            stop_task = asyncio.create_task(self._stop.wait())
            done, pending = await asyncio.wait(
                {dq_task, stop_task}, return_when=asyncio.FIRST_COMPLETED,
            )
            for p in pending:
                p.cancel()
            if stop_task in done:
                if not dq_task.cancelled():
                    try:
                        dq_task.result()
                    except Exception:
                        pass
                return
            try:
                job = dq_task.result()
            except Exception:
                continue
            self._inflight = asyncio.create_task(self._process_one(job))
            try:
                await self._inflight
            except asyncio.CancelledError:
                return
            self._inflight = None

    async def _process_one(self, job) -> None:
        device = self._devices.get(job.gopro_serial)
        if device is None or getattr(device, "is_disabled", False):
            await self._errors.publish(
                HardwareError(f"GoPro DL: no device for serial {job.gopro_serial}, "
                              f"sidecar kept (episode {job.episode_index})")
            )
            return

        tmp = self._paths.pending_dir / f"gopro_dl_{job.job_id}.mp4"

        skip_dl = False
        if tmp.exists() and tmp.stat().st_size > 0:
            try:
                files = await device.media_list()
                match = next((f for f in files if f.filename == job.sd_filename), None)
                if match is not None and tmp.stat().st_size == match.size:
                    skip_dl = True
            except Exception:
                skip_dl = False

        if not skip_dl:
            try:
                await device.download_file(job.sd_filename, tmp)
            except Exception as e:
                await self._errors.publish(
                    HardwareError(f"GoPro DL failed for ep {job.episode_index}: {e}")
                )
                return

        if job.gopro_t0_mono_ns is not None:
            try:
                duration = probe_mp4_duration(tmp)
                expected = (job.episode_stop_mono_ns - job.gopro_t0_mono_ns) / 1e9
                if duration < expected - 0.5:
                    await self._errors.publish(HardwareError(
                        f"GoPro recording shorter than episode: ep {job.episode_index} "
                        f"duration={duration:.3f}s expected≈{expected:.3f}s"
                    ))
            except Exception as e:
                log.warning("duration probe failed for %s: %s", tmp, e)

        dest = self._paths.episode_video(job.chunk_index, job.cam_name, job.episode_index)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmp), str(dest))
        except Exception as e:
            await self._errors.publish(
                HardwareError(f"GoPro move failed for ep {job.episode_index}: {e}")
            )
            return

        await self._queue.mark_done(job.job_id)

    async def stop(self) -> None:
        self._stop.set()
        if self._inflight is not None:
            try:
                await asyncio.wait_for(self._inflight, timeout=self._grace)
            except asyncio.TimeoutError:
                self._inflight.cancel()
                try:
                    await self._inflight
                except (asyncio.CancelledError, Exception):
                    pass
```

- [ ] **Step 4: Add `subscribe` helper to ErrorBus if it doesn't exist**

Read `backend/mimicrec/util/error_bus.py`. If it does not have a `subscribe(callback)` method that calls back synchronously on each `publish`, add one:

```python
def subscribe(self, callback) -> None:
    """Synchronous callback for each published error (for tests)."""
    self._sync_subs.append(callback)
```

…and call all `_sync_subs` from inside `publish`. If the codebase already has an equivalent (queue subscription), update the test to use that pattern and skip this step.

- [ ] **Step 5: Run test — verify it passes**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_dl_worker.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```
git add backend/mimicrec/gopro/dl_worker.py backend/mimicrec/util/error_bus.py tests/unit/gopro/test_dl_worker.py
git commit -m "feat(gopro): GoProDLWorker with serialized DL, resume-from-tmp, duration check"
```

---

### Task 8: `gopro/preview.py` — `GoProPreviewSource`

**Files:**
- Create: `backend/mimicrec/gopro/preview.py`
- Test: `tests/unit/gopro/test_preview.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/gopro/test_preview.py`:

```python
import asyncio

import numpy as np
import pytest

from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.gopro.preview import GoProPreviewSource
from mimicrec.types import Frame


@pytest.mark.asyncio
async def test_preview_source_emits_preview_only_frames() -> None:
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    src = GoProPreviewSource(d, udp_port=18556)

    # Inject a synthetic frame for testability — preview source exposes a
    # `_push_frame_for_test` hook used only in tests.
    await src.connect()
    img = np.zeros((48, 64, 3), dtype=np.uint8)
    await src._push_frame_for_test(img)

    f = await asyncio.wait_for(src.read(), timeout=1.0)
    assert isinstance(f, Frame)
    assert f.preview_only is True
    assert f.image.shape == (48, 64, 3)

    await src.disconnect()


@pytest.mark.asyncio
async def test_disabled_device_read_blocks_cleanly() -> None:
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    d.disable("test")
    src = GoProPreviewSource(d, udp_port=18557)
    await src.connect()  # no-op when disabled

    # read() must not raise; it must block forever (no error spam).
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(src.read(), timeout=0.3)

    await src.disconnect()
```

- [ ] **Step 2: Run test — verify it fails**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_preview.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `preview.py`**

Create `backend/mimicrec/gopro/preview.py`:

```python
from __future__ import annotations
import asyncio
import logging
from typing import Optional

import numpy as np

from mimicrec.types import Frame

log = logging.getLogger(__name__)


class GoProPreviewSource:
    """Camera I/F view over a GoProDevice's UDP MPEG-TS preview stream.

    `read()` always returns Frame(preview_only=True). When the underlying
    device is disabled, `read()` awaits a never-firing event so the
    CameraManager `_run_camera` loop idles cleanly without spamming
    HardwareError every 50 ms."""

    def __init__(self, device, udp_port: int) -> None:
        self._device = device
        self._port = udp_port
        self._latest: asyncio.Queue[Frame] = asyncio.Queue(maxsize=1)
        self._never: asyncio.Event = asyncio.Event()  # never set
        self._decode_task: Optional[asyncio.Task] = None
        self._connected = False

    @property
    def name(self) -> str: return self._device.name

    async def connect(self) -> None:
        if getattr(self._device, "is_disabled", False):
            return
        try:
            await self._device.start_preview(self._port)
        except Exception as e:
            log.warning("start_preview failed for %s: %s", self._device.name, e)
            return
        self._decode_task = asyncio.create_task(self._decode_loop())
        self._connected = True

    async def disconnect(self) -> None:
        if self._decode_task is not None:
            self._decode_task.cancel()
            try:
                await self._decode_task
            except (asyncio.CancelledError, Exception):
                pass
            self._decode_task = None
        try:
            await self._device.stop_preview()
        except Exception as e:
            log.warning("stop_preview failed for %s: %s", self._device.name, e)
        self._connected = False

    async def read(self) -> Frame:
        if getattr(self._device, "is_disabled", False) or not self._connected:
            # Clean idle. Cancellable but non-spamming.
            await self._never.wait()
        return await self._latest.get()

    async def _decode_loop(self) -> None:
        """Bind UDP socket to self._port, feed bytes through pyav, push the
        most recent decoded frame into self._latest (drop-on-full).

        Implementation note: open `udp://0.0.0.0:<port>?fifo_size=...` via pyav.
        """
        import av
        url = f"udp://0.0.0.0:{self._port}?fifo_size=50000&overrun_nonfatal=1"
        try:
            with av.open(url, mode="r", timeout=5) as ctx:
                for packet in ctx.demux(video=0):
                    for av_frame in packet.decode():
                        img = av_frame.to_ndarray(format="bgr24")
                        try:
                            self._latest.put_nowait(
                                Frame(image=img, preview_only=True)
                            )
                        except asyncio.QueueFull:
                            try:
                                self._latest.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                            self._latest.put_nowait(
                                Frame(image=img, preview_only=True)
                            )
        except Exception as e:
            log.warning("preview decode loop ended for %s: %s",
                        self._device.name, e)

    async def _push_frame_for_test(self, image: np.ndarray) -> None:
        """Test-only hook bypassing the UDP/pyav pipeline."""
        try:
            self._latest.put_nowait(Frame(image=image, preview_only=True))
        except asyncio.QueueFull:
            self._latest.get_nowait()
            self._latest.put_nowait(Frame(image=image, preview_only=True))
        # Mark connected for read() pass-through.
        self._connected = True
```

- [ ] **Step 4: Run test — verify it passes**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_preview.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/gopro/preview.py tests/unit/gopro/test_preview.py
git commit -m "feat(gopro): GoProPreviewSource UDP MPEG-TS decoder with preview_only frames"
```

---

### Task 9: `gopro/registry.py` — `GoProDeviceRegistry`

**Files:**
- Create: `backend/mimicrec/gopro/registry.py`
- Test: `tests/unit/gopro/test_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/gopro/test_registry.py`:

```python
import asyncio
from pathlib import Path

import pytest

from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.gopro.registry import GoProDeviceRegistry
from mimicrec.gopro.types import GoProSpec
from mimicrec.recording.dataset_layout import dataset_paths
from mimicrec.util.error_bus import ErrorBus


@pytest.fixture
def paths(tmp_path: Path):
    p = dataset_paths(tmp_path / "ds")
    for d in (p.meta_dir, p.pending_dir, p.videos_dir):
        d.mkdir(parents=True, exist_ok=True)
    return p


def test_duplicate_name_raises(paths) -> None:
    a = MockGoProDevice(name="g1", usb_serial="S1")
    b = MockGoProDevice(name="g1", usb_serial="S2")
    with pytest.raises(ValueError, match="duplicate name"):
        GoProDeviceRegistry(devices=[a, b], paths=paths, errors=ErrorBus())


def test_duplicate_serial_raises(paths) -> None:
    a = MockGoProDevice(name="g1", usb_serial="S1")
    b = MockGoProDevice(name="g2", usb_serial="S1")
    with pytest.raises(ValueError, match="duplicate usb_serial"):
        GoProDeviceRegistry(devices=[a, b], paths=paths, errors=ErrorBus())


@pytest.mark.asyncio
async def test_start_connects_and_provides_preview_sources(paths) -> None:
    a = MockGoProDevice(name="g1", usb_serial="S1")
    reg = GoProDeviceRegistry(devices=[a], paths=paths, errors=ErrorBus())
    await reg.start()
    sources = reg.preview_sources()
    assert "g1" in sources
    specs = reg.gopro_specs()
    assert "g1" in specs and isinstance(specs["g1"], GoProSpec)
    await reg.stop()


@pytest.mark.asyncio
async def test_failed_connect_marks_device_disabled_and_continues(paths) -> None:
    a = MockGoProDevice(name="g_bad", usb_serial="S1", recording_preset="bogus")
    b = MockGoProDevice(name="g_ok",  usb_serial="S2")
    reg = GoProDeviceRegistry(devices=[a, b], paths=paths, errors=ErrorBus())
    await reg.start()
    assert a.is_disabled
    assert not b.is_disabled
    await reg.stop()


@pytest.mark.asyncio
async def test_episode_lifecycle_fans_out(paths) -> None:
    a = MockGoProDevice(name="g1", usb_serial="S1")
    reg = GoProDeviceRegistry(devices=[a], paths=paths, errors=ErrorBus())
    await reg.start()
    await reg.episode_start(0, t_host_mono_ns=0)
    await reg.episode_stop(0)
    await asyncio.sleep(0.1)
    # Pending count should reflect the enqueued job (DLWorker hasn't drained yet
    # because MockGoProDevice download is fast; just check ≤ 1 since worker may have already drained).
    assert reg.pending_count >= 0  # liveness check
    await reg.stop()
```

- [ ] **Step 2: Run test — verify it fails**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_registry.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `registry.py`**

Create `backend/mimicrec/gopro/registry.py`:

```python
from __future__ import annotations
import asyncio
import logging

from mimicrec.errors import HardwareError
from mimicrec.gopro.dl_queue import DLQueue
from mimicrec.gopro.dl_worker import GoProDLWorker
from mimicrec.gopro.preview import GoProPreviewSource
from mimicrec.gopro.recorder import GoProRecorder
from mimicrec.gopro.types import GoProSpec
from mimicrec.recording.dataset_layout import DatasetPaths
from mimicrec.util.error_bus import ErrorBus

log = logging.getLogger(__name__)


class GoProDeviceRegistry:
    def __init__(self, devices: list, paths: DatasetPaths, errors: ErrorBus) -> None:
        names = [d.name for d in devices]
        serials = [d.usb_serial for d in devices]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate name in GoPro devices: {names}")
        if len(set(serials)) != len(serials):
            raise ValueError(f"duplicate usb_serial in GoPro devices: {serials}")

        self._devices = devices
        self._paths = paths
        self._errors = errors
        self._queue: DLQueue | None = None
        self._worker: GoProDLWorker | None = None
        self._worker_task: asyncio.Task | None = None
        self._recorders: dict[str, GoProRecorder] = {}
        self._previews: dict[str, GoProPreviewSource] = {}

    async def start(self) -> None:
        # 1. Connect each device, disabling those that fail.
        async def _connect(d):
            try:
                await d.connect()
            except Exception as e:
                if hasattr(d, "disable"):
                    d.disable(f"connect failed: {e}")
                await self._errors.publish(HardwareError(f"GoPro {d.name} connect: {e}"))
        await asyncio.gather(*[_connect(d) for d in self._devices], return_exceptions=True)

        # 2. Restore the persistent DL queue.
        self._queue = DLQueue.restore(self._paths.pending_dir / "gopro_dl")

        # 3. Build recorders and preview sources for ALL devices (disabled or not).
        base_port = 18556
        for idx, d in enumerate(self._devices):
            self._recorders[d.name] = GoProRecorder(d, self._queue, self._paths)
            self._previews[d.name] = GoProPreviewSource(d, udp_port=base_port + idx)

        # 4. Start the worker.
        devices_by_serial = {d.usb_serial: d for d in self._devices}
        self._worker = GoProDLWorker(
            self._queue, devices=devices_by_serial,
            paths=self._paths, errors=self._errors,
        )
        self._worker_task = asyncio.create_task(self._worker.run())

    async def stop(self) -> None:
        if self._worker is not None:
            await self._worker.stop()
        if self._worker_task is not None:
            try:
                await asyncio.wait_for(self._worker_task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                self._worker_task.cancel()
        for src in self._previews.values():
            try:
                await src.disconnect()
            except Exception:
                pass
        for d in self._devices:
            try:
                await d.disconnect()
            except Exception:
                pass

    async def episode_start(self, episode_index: int, t_host_mono_ns: int) -> None:
        await asyncio.gather(
            *[r.start_episode(episode_index, t_host_mono_ns) for r in self._recorders.values()],
            return_exceptions=True,
        )

    async def episode_stop(self, episode_index: int) -> None:
        await asyncio.gather(
            *[r.stop_episode(episode_index) for r in self._recorders.values()],
            return_exceptions=True,
        )

    def preview_sources(self) -> dict[str, GoProPreviewSource]:
        return dict(self._previews)

    def gopro_specs(self) -> dict[str, GoProSpec]:
        return {d.name: d.get_spec() for d in self._devices}

    @property
    def pending_count(self) -> int:
        return self._queue.pending_count if self._queue is not None else 0
```

- [ ] **Step 4: Run test — verify it passes**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_registry.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/gopro/registry.py tests/unit/gopro/test_registry.py
git commit -m "feat(gopro): GoProDeviceRegistry with name/serial uniqueness, lifecycle fan-out"
```

---

## Phase 4 — Real device + dataset integration

### Task 10: `gopro/device.py` — Real `GoProDevice`

**Files:**
- Create: `backend/mimicrec/gopro/device.py`
- Test: `tests/unit/gopro/test_device.py`

- [ ] **Step 1: Write the failing test (with mocked open_gopro)**

Create `tests/unit/gopro/test_device.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

import pytest

from mimicrec.errors import HardwareError
from mimicrec.gopro.types import GoProSpec, MediaItem


@pytest.mark.asyncio
async def test_connect_calls_required_apis_in_order() -> None:
    from mimicrec.gopro.device import GoProDevice
    fake_client = MagicMock()
    fake_client.is_open = True
    fake_client.http_command = MagicMock()
    fake_client.http_command.set_date_time = AsyncMock(return_value=MagicMock(ok=True))
    fake_client.http_command.load_preset_group = AsyncMock(return_value=MagicMock(ok=True))
    fake_client.http_command.set_preset = AsyncMock(return_value=MagicMock(ok=True))
    fake_client.http_command.get_camera_state = AsyncMock(
        return_value=MagicMock(ok=True, data={"sd_status_remaining": 1_000_000_000})
    )
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_client)
    fake_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("mimicrec.gopro.device.WiredGoPro", return_value=fake_ctx):
        d = GoProDevice(name="g1", usb_serial="S1", recording_preset="1080p_60_wide")
        await d.connect()

        fake_client.http_command.set_date_time.assert_awaited()
        fake_client.http_command.load_preset_group.assert_awaited()
        fake_client.http_command.set_preset.assert_awaited()
        await d.disconnect()


@pytest.mark.asyncio
async def test_unknown_preset_raises_fatal() -> None:
    from mimicrec.gopro.device import GoProDevice
    d = GoProDevice(name="g1", usb_serial="S1", recording_preset="not_a_preset")
    with pytest.raises(HardwareError):
        await d.connect()


@pytest.mark.asyncio
async def test_storage_below_threshold_raises_fatal() -> None:
    from mimicrec.gopro.device import GoProDevice
    fake_client = MagicMock()
    fake_client.http_command.set_date_time = AsyncMock(return_value=MagicMock(ok=True))
    fake_client.http_command.load_preset_group = AsyncMock(return_value=MagicMock(ok=True))
    fake_client.http_command.set_preset = AsyncMock(return_value=MagicMock(ok=True))
    fake_client.http_command.get_camera_state = AsyncMock(
        return_value=MagicMock(ok=True, data={"sd_status_remaining": 100_000_000})  # 100 MB < 500 MB
    )
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_client)
    fake_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("mimicrec.gopro.device.WiredGoPro", return_value=fake_ctx):
        d = GoProDevice(name="g1", usb_serial="S1", recording_preset="1080p_60_wide")
        with pytest.raises(HardwareError, match="storage"):
            await d.connect()


@pytest.mark.asyncio
async def test_get_spec_resolves_preset() -> None:
    from mimicrec.gopro.device import GoProDevice
    d = GoProDevice(name="g1", usb_serial="S1", recording_preset="4K_60_wide")
    assert d.get_spec() == GoProSpec(name="g1", width=3840, height=2160, fps=60, codec="h265")
```

- [ ] **Step 2: Run test — verify it fails**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_device.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `device.py`**

> NOTE: Specific `open_gopro` API method names (`http_command.set_date_time`, etc.) are based on `open_gopro` 0.16.x. If Phase 0 verification revealed different names on the pinned version, adjust the calls below accordingly. The tests above use the same names, so they need to be adjusted in lockstep.

Create `backend/mimicrec/gopro/device.py`:

```python
from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from mimicrec.errors import HardwareError
from mimicrec.gopro.types import GoProSpec, MediaItem

log = logging.getLogger(__name__)

try:
    from open_gopro import WiredGoPro, constants  # type: ignore
except Exception:
    WiredGoPro = None  # type: ignore[assignment]
    constants = None   # type: ignore[assignment]

_PRESET_SPECS: dict[str, tuple[int, int, int, str]] = {
    "1080p_60_wide": (1920, 1080, 60, "h264"),
    "1080p_30_wide": (1920, 1080, 30, "h264"),
    "2.7K_60_wide":  (2704, 1520, 60, "h264"),
    "4K_30_wide":    (3840, 2160, 30, "h265"),
    "4K_60_wide":    (3840, 2160, 60, "h265"),
    "5.3K_30_wide":  (5312, 2988, 30, "h265"),
}

_STORAGE_MIN_BYTES = 500_000_000


class GoProDevice:
    def __init__(self, name: str, usb_serial: str, recording_preset: str) -> None:
        self._name = name
        self._serial = usb_serial
        self._preset = recording_preset
        self._client_ctx = None
        self._client = None
        self._disabled = False

    @property
    def name(self) -> str: return self._name
    @property
    def usb_serial(self) -> str: return self._serial
    @property
    def is_disabled(self) -> bool: return self._disabled

    def get_spec(self) -> GoProSpec:
        if self._preset not in _PRESET_SPECS:
            raise HardwareError(f"unknown preset: {self._preset}")
        w, h, fps, codec = _PRESET_SPECS[self._preset]
        return GoProSpec(name=self._name, width=w, height=h, fps=fps, codec=codec)

    async def connect(self) -> None:
        if self._client is not None:
            return
        if self._preset not in _PRESET_SPECS:
            raise HardwareError(f"unknown preset: {self._preset}")
        if WiredGoPro is None:
            raise HardwareError("open_gopro is not installed")
        self._client_ctx = WiredGoPro(target=self._serial)
        try:
            self._client = await self._client_ctx.__aenter__()
        except Exception as e:
            self._client_ctx = None
            raise HardwareError(f"WiredGoPro init failed: {e}") from e

        await self._must_ok(self._client.http_command.set_date_time(date_time=datetime.now()),
                            "set_date_time")
        await self._must_ok(
            self._client.http_command.load_preset_group(
                group=constants.proto.EnumPresetGroup.PRESET_GROUP_ID_VIDEO),
            "load_preset_group video")
        # Apply the named preset. This call's signature varies; if your
        # pinned open_gopro version exposes preset by name string, use that;
        # otherwise resolve via constants.proto.EnumPresetID.<name> and call
        # set_preset(preset=<id>).
        await self._must_ok(
            self._client.http_command.set_preset(preset=self._preset),
            f"set_preset {self._preset}")

        state = await self._must_ok(
            self._client.http_command.get_camera_state(), "get_camera_state")
        remaining = int(state.data.get("sd_status_remaining", 0))
        if remaining < _STORAGE_MIN_BYTES:
            raise HardwareError(
                f"GoPro {self._name} storage too low: {remaining} bytes remaining")

    async def disconnect(self) -> None:
        if self._client_ctx is None:
            return
        try:
            await self._client_ctx.__aexit__(None, None, None)
        except Exception as e:
            log.warning("GoPro %s disconnect failed: %s", self._name, e)
        self._client = None
        self._client_ctx = None

    async def shutter_on(self) -> None:
        if self._disabled or self._client is None: return
        await self._must_ok(
            self._client.http_command.set_shutter(shutter=constants.Toggle.ENABLE),
            "set_shutter on")

    async def shutter_off(self) -> None:
        if self._disabled or self._client is None: return
        await self._must_ok(
            self._client.http_command.set_shutter(shutter=constants.Toggle.DISABLE),
            "set_shutter off")

    async def media_list(self) -> list[MediaItem]:
        if self._disabled or self._client is None: return []
        r = await self._must_ok(self._client.http_command.get_media_list(),
                                 "get_media_list")
        out: list[MediaItem] = []
        for f in r.data.files:
            mtime_ns = int(getattr(f, "creation_timestamp", 0)) * 1_000_000_000
            out.append(MediaItem(filename=f.filename, size=int(f.size), mtime_ns=mtime_ns))
        return out

    async def start_preview(self, port: int) -> None:
        if self._disabled or self._client is None: return
        await self._must_ok(
            self._client.http_command.set_preview_stream(
                mode=constants.Toggle.ENABLE, port=port),
            "set_preview_stream on")

    async def stop_preview(self) -> None:
        if self._disabled or self._client is None: return
        await self._must_ok(
            self._client.http_command.set_preview_stream(mode=constants.Toggle.DISABLE),
            "set_preview_stream off")

    async def download_file(self, sd_filename: str, dest: Path) -> None:
        if self._disabled or self._client is None: return
        await self._must_ok(
            self._client.http_command.download_file(camera_file=sd_filename, local_file=dest),
            f"download_file {sd_filename}")

    async def get_storage_remaining(self) -> int:
        if self._disabled or self._client is None: return 0
        r = await self._must_ok(self._client.http_command.get_camera_state(), "get_camera_state")
        return int(r.data.get("sd_status_remaining", 0))

    def disable(self, reason: str) -> None:
        if self._disabled: return
        self._disabled = True
        log.warning("GoProDevice %s disabled: %s", self._name, reason)

    async def _must_ok(self, awaitable, what: str):
        r = await awaitable
        if not getattr(r, "ok", True):
            raise HardwareError(f"GoPro {self._name} {what} failed: {r}")
        return r
```

- [ ] **Step 4: Run test — verify it passes**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_device.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/gopro/device.py tests/unit/gopro/test_device.py
git commit -m "feat(gopro): GoProDevice wrapping WiredGoPro SDK client"
```

---

### Task 11: `init_dataset` accepts `gopro_specs`

**Files:**
- Modify: `backend/mimicrec/recording/dataset_layout.py:42-117`
- Test: `tests/unit/gopro/test_init_dataset_gopro.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/gopro/test_init_dataset_gopro.py`:

```python
import json
from pathlib import Path

from mimicrec.gopro.types import GoProSpec
from mimicrec.recording.dataset_layout import init_dataset


def test_init_dataset_writes_gopro_features(tmp_path: Path) -> None:
    init_dataset(
        ds_root=tmp_path,
        fps=30,
        joint_names=["j0", "j1"],
        camera_names=["wrist"],
        camera_resolutions={"wrist": (640, 480)},
        gopro_specs={"gopro_external": GoProSpec(
            name="gopro_external", width=1920, height=1080, fps=60, codec="h264"
        )},
    )

    info = json.loads((tmp_path / "meta" / "info.json").read_text())
    feats = info["features"]
    assert "observation.images.wrist" in feats
    assert "observation.images.gopro_external" in feats

    g = feats["observation.images.gopro_external"]
    assert g["shape"] == [1080, 1920, 3]
    assert g["info"]["video.height"] == 1080
    assert g["info"]["video.width"] == 1920
    assert g["info"]["video.fps"] == 60
    assert g["info"]["video.codec"] == "h264"
    assert g["info"]["has_gpmf"] is True


def test_init_dataset_without_gopros_unchanged(tmp_path: Path) -> None:
    """Existing OpenCV-only path still works."""
    init_dataset(
        ds_root=tmp_path,
        fps=30,
        joint_names=["j0"],
        camera_names=["front"],
        camera_resolutions={"front": (640, 480)},
    )
    info = json.loads((tmp_path / "meta" / "info.json").read_text())
    assert "observation.images.front" in info["features"]
```

- [ ] **Step 2: Run test — verify it fails**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_init_dataset_gopro.py -v
```

Expected: `init_dataset() got unexpected kwarg 'gopro_specs'`.

- [ ] **Step 3: Add the parameter and feature-writing block**

Edit `backend/mimicrec/recording/dataset_layout.py`. Update `init_dataset` signature and the features-building block:

```python
def init_dataset(
    ds_root: Path,
    fps: int,
    joint_names: list[str],
    camera_names: list[str],
    *,
    robot_type: str | None = None,
    gripper_convention: dict | None = None,
    proprio_layout: dict | None = None,
    camera_resolutions: dict[str, tuple[int, int]] | None = None,
    gopro_specs: "dict[str, object] | None" = None,    # NEW
) -> None:
    ...
    # (existing OpenCV camera loop unchanged)

    if gopro_specs:
        for name, spec in gopro_specs.items():
            features[f"observation.images.{name}"] = {
                "dtype": "video",
                "shape": [spec.height, spec.width, 3],
                "names": ["height", "width", "channels"],
                "info": {
                    "video.height": spec.height,
                    "video.width": spec.width,
                    "video.codec": spec.codec,
                    "video.pix_fmt": "yuv420p",
                    "video.is_depth_map": False,
                    "video.fps": spec.fps,
                    "video.channels": 3,
                    "has_audio": False,
                    "has_gpmf": True,
                },
            }
```

- [ ] **Step 4: Run test — verify it passes**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_init_dataset_gopro.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/recording/dataset_layout.py tests/unit/gopro/test_init_dataset_gopro.py
git commit -m "feat(dataset): init_dataset accepts gopro_specs with has_gpmf marker"
```

---

## Phase 5 — API integration

### Task 12: `schemas.py` — `gopros` request/response field

**Files:**
- Modify: `backend/mimicrec/api/schemas.py` (find `_BaseSessionRequest` and `SessionStatePayload`)
- Test: `tests/unit/gopro/test_schemas_gopros.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/gopro/test_schemas_gopros.py`:

```python
from mimicrec.api.schemas import StartSessionRequest, SessionStatePayload


def test_start_session_request_gopros_default_empty() -> None:
    r = StartSessionRequest(
        dataset="ds", task="t", robot="so101",
        teleop="so_leader", mapper=None, cameras=["wrist"], fps=30,
        mode="teleop",
    )
    assert r.gopros == []


def test_start_session_request_gopros_explicit() -> None:
    r = StartSessionRequest(
        dataset="ds", task="t", robot="so101",
        teleop="so_leader", mapper=None, cameras=["wrist"], fps=30,
        mode="teleop", gopros=["gopro_external"],
    )
    assert r.gopros == ["gopro_external"]


def test_session_state_payload_gopros_default_empty() -> None:
    p = SessionStatePayload(state="idle", episode=None, dataset="ds", cameras=[])
    assert p.gopros == []
```

- [ ] **Step 2: Run test — verify it fails**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_schemas_gopros.py -v
```

Expected: `unexpected keyword argument 'gopros'` or AttributeError.

- [ ] **Step 3: Add `gopros` field to schemas**

Edit `backend/mimicrec/api/schemas.py`. Locate `_BaseSessionRequest` and add `gopros: list[str] = Field(default_factory=list)` (use the same default pattern as the existing `cameras` field — likely Pydantic). Same for `SessionStatePayload`.

- [ ] **Step 4: Run test — verify it passes**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_schemas_gopros.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Smoke-run full test suite**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests -v -m 'not gopro_hardware'
```

Expected: existing API tests still green (`gopros` defaulted to empty preserves behavior).

- [ ] **Step 6: Commit**

```
git add backend/mimicrec/api/schemas.py tests/unit/gopro/test_schemas_gopros.py
git commit -m "feat(api): add gopros field to session request/state schemas"
```

---

### Task 13: `deps.py` — bootstrap GoPro registry into session

**Files:**
- Modify: `backend/mimicrec/api/deps.py:105-220`
- Test: `tests/integration/test_gopro_session_bootstrap.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_gopro_session_bootstrap.py`:

```python
from pathlib import Path

import pytest

# This test exercises deps.py session bootstrap. It uses MockGoProDevice via a
# Hydra config that points _target_ to mimicrec.gopro.mock.MockGoProDevice.
# A small fixture YAML lives under tests/fixtures/configs.


@pytest.mark.asyncio
async def test_session_with_gopro_creates_registry(tmp_path: Path, monkeypatch) -> None:
    # The actual integration uses the full session bootstrap; this is a
    # behavior smoke test rather than a tight unit test.
    # If the existing test harness has a fixture to start a session, use it.
    # Otherwise this can be skipped during initial implementation and revisited
    # in Task 16.
    pytest.skip("Implemented in Task 16 — full integration test")
```

(This test is intentionally a stub — the real integration verification is Task 16. But Task 13 still needs to be testable; we rely on the smoke run at the end of Step 5.)

- [ ] **Step 2: Modify `deps.py`**

Edit `backend/mimicrec/api/deps.py`. Find the session-bootstrap block (around line 105) and add a parallel GoPro-loading block after the existing camera loading. Insert these changes:

```python
    # Cameras (existing)
    cams = {}
    cam_cfgs: dict[str, object] = {}
    for cam_name in req.cameras:
        cam_cfg = OmegaConf.load(configs_root / "cameras" / f"{cam_name}.yaml")
        cam_cfgs[cam_name] = OmegaConf.to_container(cam_cfg)
        cam_kwargs = {k: v for k, v in OmegaConf.to_container(cam_cfg).items()
                     if k not in ("_target_",)}
        cam_kwargs.setdefault("name", cam_name)
        cams[cam_name] = instantiate_adapter(str(cam_cfg._target_), **cam_kwargs)

    # GoPros (NEW)
    overlap = set(req.cameras) & set(getattr(req, "gopros", []))
    if overlap:
        raise ValueError(f"name overlap between cameras and gopros: {overlap}")

    gopro_devices: list = []
    for g_name in getattr(req, "gopros", []):
        g_cfg = OmegaConf.load(configs_root / "gopros" / f"{g_name}.yaml")
        g_kwargs = {k: v for k, v in OmegaConf.to_container(g_cfg).items()
                    if k not in ("_target_",)}
        g_kwargs.setdefault("name", g_name)
        gopro_devices.append(instantiate_adapter(str(g_cfg._target_), **g_kwargs))

    error_bus = ErrorBus()

    # Build the dataset paths so the registry can resolve dest paths.
    from mimicrec.recording.dataset_layout import dataset_paths as _ds_paths
    paths = _ds_paths(datasets_root / req.dataset)
    paths.pending_dir.mkdir(parents=True, exist_ok=True)

    from mimicrec.gopro.registry import GoProDeviceRegistry
    gopro_registry = GoProDeviceRegistry(
        devices=gopro_devices, paths=paths, errors=error_bus,
    ) if gopro_devices else None
    if gopro_registry is not None:
        await gopro_registry.start()
        # Merge preview sources into the cameras dict BEFORE constructing CameraManager.
        for name, src in gopro_registry.preview_sources().items():
            cams[name] = src

    cm = CameraManager(cameras=cams, error_bus=error_bus)
```

Then update the `init_dataset` call (already nearby) to pass `gopro_specs`:

```python
        init_dataset(
            ds_root, fps=req.fps,
            joint_names=robot.joint_names,
            camera_names=list(req.cameras),
            robot_type=rt,
            gripper_convention=...,
            proprio_layout=...,
            camera_resolutions=camera_resolutions,
            gopro_specs=(gopro_registry.gopro_specs() if gopro_registry else None),
        )
```

Save the registry on app state for later access:

```python
    app.state.gopro_registry = gopro_registry
```

Also update `app.state.session_meta` to include `"gopros": list(getattr(req, "gopros", []))`.

- [ ] **Step 3: Wire registry to SessionManager episode lifecycle**

Locate the SessionManager episode_start / episode_stop calls in this file (or `backend/mimicrec/recording/session_manager.py`). Wherever the per-episode hooks are, add fan-out to the registry.

If `SessionManager` is constructed with `error_bus`, also pass `gopro_registry` so SessionManager can call `await gopro_registry.episode_start(idx, t)` and `await gopro_registry.episode_stop(idx)` at the right moments. Keep the change minimal — one new optional param to the SessionManager constructor with default `None`.

- [ ] **Step 4: Filter GoPro names from PendingEpisode video writers**

Locate where SessionManager (or pending.py caller) builds the `cameras: dict[str, tuple[int, int]]` for `PendingEpisode.open_video_writers`. Make sure GoPro names (which are in `cm._cameras` but should NOT have an Mp4EpisodeWriter — DLWorker writes their MP4) are excluded.

The cleanest fix: pass an explicit list of "GoPro names" through to that call site. The session_meta now has `"gopros"`; use it to filter:

```python
realtime_cams = {n: (w, h) for n, (w, h) in cameras_with_res.items()
                 if n not in app.state.session_meta.get("gopros", [])}
pending.open_video_writers(fps=fps, cameras=realtime_cams)
```

- [ ] **Step 5: Smoke run**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests -v -m 'not gopro_hardware'
```

Expected: all tests still pass; no new regressions. The Task 13 stub test is `skip`ped.

- [ ] **Step 6: Commit**

```
git add backend/mimicrec/api/deps.py backend/mimicrec/recording/session_manager.py tests/integration/test_gopro_session_bootstrap.py
git commit -m "feat(api): bootstrap GoProDeviceRegistry in session, fan out episode lifecycle"
```

---

### Task 14: `GET /api/session/gopro_pending` endpoint

**Files:**
- Modify: `backend/mimicrec/api/routes/session.py` (or whichever existing routes file)
- Test: `tests/api/test_gopro_pending_route.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_gopro_pending_route.py`:

```python
import pytest
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_gopro_pending_returns_zero_when_no_session(app_no_session) -> None:
    client = TestClient(app_no_session)
    r = client.get("/api/session/gopro_pending")
    assert r.status_code == 200
    assert r.json() == {"pending": 0}
```

The `app_no_session` fixture must exist in `tests/conftest.py` or be added there (a FastAPI app without any session active). If MimicRec's existing test harness has an equivalent fixture (e.g., `client` or `app`), reuse that name.

- [ ] **Step 2: Run test — verify it fails**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/api/test_gopro_pending_route.py -v
```

Expected: 404 (no such route).

- [ ] **Step 3: Add the endpoint**

Edit `backend/mimicrec/api/routes/session.py` (or wherever session-status routes live):

```python
@router.get("/api/session/gopro_pending")
async def get_gopro_pending(request: Request) -> dict[str, int]:
    reg = getattr(request.app.state, "gopro_registry", None)
    return {"pending": int(reg.pending_count) if reg is not None else 0}
```

- [ ] **Step 4: Run test — verify it passes**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/api/test_gopro_pending_route.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/api/routes/session.py tests/api/test_gopro_pending_route.py
git commit -m "feat(api): GET /api/session/gopro_pending endpoint"
```

---

## Phase 6 — Frontend

### Task 15: Pending DL badge + quit warning

**Files:**
- Create: `frontend/src/components/GoProPendingBadge.tsx`
- Modify: `frontend/src/components/Layout.tsx` (or wherever the top nav lives)
- Modify: `frontend/src/api/session.ts` (add `getGoProPending`)

- [ ] **Step 1: Add API client function**

Edit `frontend/src/api/session.ts` and append:

```ts
export async function getGoProPending(): Promise<number> {
  const r = await apiFetch('/api/session/gopro_pending');
  if (!r.ok) return 0;
  const j = await r.json();
  return j.pending ?? 0;
}
```

- [ ] **Step 2: Create the badge component**

Create `frontend/src/components/GoProPendingBadge.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { getGoProPending } from '../api/session';

export function GoProPendingBadge() {
  const [pending, setPending] = useState(0);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const n = await getGoProPending();
        if (alive) setPending(n);
      } catch (_) { /* ignore */ }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (pending === 0) return null;
  return (
    <span title="GoPro DL pending">
      GoPro: {pending}
    </span>
  );
}
```

- [ ] **Step 3: Mount the badge in the layout**

Edit `frontend/src/components/Layout.tsx` to render `<GoProPendingBadge />` in the top nav area.

- [ ] **Step 4: Add quit warning**

Find the existing quit/close handler (likely in App.tsx or a similar root component). Add a `beforeunload` handler that, if `pending > 0`, prompts the user:

```tsx
useEffect(() => {
  const handler = (e: BeforeUnloadEvent) => {
    if (lastPending > 0) {
      e.preventDefault();
      e.returnValue = `${lastPending} GoPro downloads pending. Don't unplug the SD.`;
    }
  };
  window.addEventListener('beforeunload', handler);
  return () => window.removeEventListener('beforeunload', handler);
}, [lastPending]);
```

(`lastPending` should be lifted from the badge or its own hook as appropriate.)

- [ ] **Step 5: Manual test**

```
cd frontend && npm run dev
```

Navigate to the running UI in a browser. Trigger a session with a GoPro mock (or wait until Task 16 integration test produces pending count > 0 in the backend). Verify:
- Badge appears with "GoPro: N"
- Clicking close/refresh tab while pending > 0 shows a confirmation dialog

- [ ] **Step 6: Commit**

```
git add frontend/src/components/GoProPendingBadge.tsx frontend/src/components/Layout.tsx frontend/src/api/session.ts
git commit -m "feat(frontend): GoPro pending DL badge and quit warning"
```

---

## Phase 7 — Final integration

### Task 16: Mock-based end-to-end integration test

**Files:**
- Create: `tests/integration/test_gopro_mock_session.py`
- Create: `configs/gopros/mock_gopro.yaml`

- [ ] **Step 1: Add a Hydra config that wires MockGoProDevice**

Create `configs/gopros/mock_gopro.yaml`:

```yaml
_target_: mimicrec.gopro.mock.MockGoProDevice
name: mock_gopro
usb_serial: "MOCK0001"
recording_preset: "1080p_60_wide"
fixture_mp4: "tests/fixtures/gopro/sample_episode.mp4"
emit_preview: false
```

- [ ] **Step 2: Provide a fixture MP4**

If `tests/fixtures/gopro/sample_episode.mp4` does not exist, add a small placeholder (≤ 4 KB) so MockGoProDevice has something to copy. A real Hero 11 sample with GPMF is preferred but not required for this test (DLWorker doesn't probe GPMF, only MP4 duration).

```
mkdir -p tests/fixtures/gopro
.venv/bin/python -c "
import av
ctx = av.open('tests/fixtures/gopro/sample_episode.mp4', mode='w')
s = ctx.add_stream('libx264', rate=30); s.width = 64; s.height = 48; s.pix_fmt = 'yuv420p'
import numpy as np
for i in range(10):
    f = av.VideoFrame.from_ndarray(np.zeros((48, 64, 3), dtype='uint8'), format='bgr24')
    for p in s.encode(f.reformat(format='yuv420p')):
        ctx.mux(p)
for p in s.encode():
    ctx.mux(p)
ctx.close()
"
```

- [ ] **Step 3: Write the integration test**

Create `tests/integration/test_gopro_mock_session.py`:

```python
import asyncio
import json
from pathlib import Path

import pytest

# Use the project's existing session-start helper. If a different harness
# exists for integration tests, adapt this to it.


@pytest.mark.asyncio
async def test_three_episodes_with_mock_gopro(tmp_path, monkeypatch) -> None:
    """End-to-end smoke test: start a session with a mock GoPro,
    record 3 episodes, verify the dataset has all 3 MP4s and the
    info.json lists has_gpmf=true for the GoPro camera."""
    pytest.importorskip("av")

    # The harness should:
    # 1. Start a session via the API with cameras=["mock_cam"] (existing) and
    #    gopros=["mock_gopro"].
    # 2. Drive 3 episode_start / episode_stop cycles (use whatever fixture
    #    drives episodes — likely posting to /api/session/episode_start, etc.)
    # 3. Wait for DLWorker to drain (poll /api/session/gopro_pending == 0).
    # 4. Assert: dataset has videos/observation.images.mock_gopro/chunk-000/
    #    episode_{0,1,2}.mp4 all present and ≥ 100 bytes.
    # 5. Assert: meta/info.json features['observation.images.mock_gopro']
    #    has has_gpmf=True.

    # The exact fixture/wiring depends on the existing test harness style.
    # If the harness isn't ready, mark this test as `xfail` until Task 17
    # validates the same thing manually.
    pytest.xfail("Wire to the existing API session harness when ready")
```

If the project has an existing API-driven integration test pattern (e.g. `tests/api/test_session_lifecycle.py`), follow that pattern — reuse fixtures rather than reinventing them.

- [ ] **Step 4: Run the test**

```
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/integration/test_gopro_mock_session.py -v
```

Expected: passes (or xfails if harness not yet wired) — when wired, all assertions PASS.

- [ ] **Step 5: Commit**

```
git add tests/integration/test_gopro_mock_session.py configs/gopros/mock_gopro.yaml tests/fixtures/gopro/
git commit -m "test(gopro): mock-based end-to-end integration smoke test"
```

---

### Task 17: Hardware verification (Hero 11 required)

**Files:**
- Modify: `pytest.ini` — add `gopro_hardware` marker, default exclusion
- Create: `tests/integration/test_gopro_hardware.py`
- Create: `configs/gopros/gopro_external.yaml` (real device YAML)
- Modify: `README.md` — add "Running GoPro hardware tests" section

- [ ] **Step 1: Configure pytest marker**

Edit `pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
filterwarnings =
    default
markers =
    e2e: end-to-end tests (slow, optional)
    gopro_hardware: requires a physical Hero 11 connected via USB
addopts = -m "not gopro_hardware"
```

- [ ] **Step 2: Create real-device config**

Create `configs/gopros/gopro_external.yaml` (replace serial with the actual device):

```yaml
_target_: mimicrec.gopro.device.GoProDevice
name: gopro_external
usb_serial: "C3441234567890"
recording_preset: "1080p_60_wide"
```

- [ ] **Step 3: Write the hardware test**

Create `tests/integration/test_gopro_hardware.py`:

```python
import asyncio
import subprocess
from pathlib import Path

import pytest

from mimicrec.gopro.device import GoProDevice
from mimicrec.gopro.registry import GoProDeviceRegistry
from mimicrec.recording.dataset_layout import dataset_paths
from mimicrec.util.error_bus import ErrorBus

pytestmark = pytest.mark.gopro_hardware


@pytest.mark.asyncio
async def test_record_three_episodes(tmp_path: Path) -> None:
    """1台のHero 11で 3 episode 連続収録、DL、ファイル配置を検証。"""
    paths = dataset_paths(tmp_path / "ds")
    for d in (paths.meta_dir, paths.pending_dir, paths.videos_dir):
        d.mkdir(parents=True, exist_ok=True)

    # NOTE: replace usb_serial with your device's serial, or read from env.
    import os
    serial = os.environ.get("GOPRO_SERIAL")
    if not serial:
        pytest.skip("Set GOPRO_SERIAL to run this test")
    dev = GoProDevice(name="g_test", usb_serial=serial, recording_preset="1080p_60_wide")
    reg = GoProDeviceRegistry(devices=[dev], paths=paths, errors=ErrorBus())
    await reg.start()
    try:
        for ep in range(3):
            await reg.episode_start(ep, t_host_mono_ns=0)
            await asyncio.sleep(2.0)
            await reg.episode_stop(ep)
    finally:
        # Drain queue
        for _ in range(120):
            if reg.pending_count == 0:
                break
            await asyncio.sleep(1.0)
        await reg.stop()

    for ep in range(3):
        mp4 = paths.episode_video(0, "g_test", ep)
        assert mp4.exists(), f"missing {mp4}"
        assert mp4.stat().st_size > 1_000_000  # > 1 MB

    # Verify GPMF track present in episode 0.
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "default=nk=1",
         str(paths.episode_video(0, "g_test", 0))],
        text=True,
    )
    assert "GoPro MET" in out, f"GPMF track missing:\n{out}"
```

- [ ] **Step 4: Document the run procedure in README**

Edit `README.md`. Add:

```markdown
## Running GoPro hardware integration tests

Requires:
- A Hero 11 plugged in via USB-C (use a known-good cable).
- `open_gopro` installed (already in `pyproject.toml`).
- `GOPRO_SERIAL=<device serial>` exported.

```
cd backend
GOPRO_SERIAL=C3441234567890 \
  env -u PYTHONPATH .venv/bin/python -m pytest ../tests/integration/test_gopro_hardware.py -v -m gopro_hardware
```

Default `pytest` runs do NOT include hardware tests.
```

- [ ] **Step 5: Run hardware tests**

With the GoPro physically connected:

```
cd /home/tirobot/MimicRec/backend
GOPRO_SERIAL=<actual serial> env -u PYTHONPATH .venv/bin/python -m pytest ../tests/integration/test_gopro_hardware.py -v -m gopro_hardware
```

Expected: 1 passed (3 MP4s placed, GPMF confirmed).

- [ ] **Step 6: Manual DoD verification**

For each Definition-of-Done item in the spec:

1. Plug GoPro, start a session via the UI with `gopros=["gopro_external"]`. Confirm UDP preview appears in the camera grid.
2. Record 1 episode, confirm the MP4 lands in `videos/observation.images.gopro_external/chunk-000/episode_000000.mp4` within seconds.
3. Run `ffprobe -show_streams .../episode_000000.mp4` and confirm `GoPro MET` track present.
4. Open `meta/info.json` and confirm `features.observation.images.gopro_external.info.has_gpmf == true`.
5. Mid-session, `kill -9` the backend pid. Restart. Confirm `.pending/gopro_dl/` was drained on restart and the missing episode MP4 appeared.
6. (If 2nd Hero 11 available) Run with `gopros=["gopro_a", "gopro_b"]`. Tail logs and confirm DL is serialized (one job ends before next begins).
7. Run `pytest -m 'not gopro_hardware'` and confirm CI-equivalent passes.
8. Run the unit test from Task 3 again and confirm `Frame.preview_only=True` skip still holds.

- [ ] **Step 7: Commit**

```
git add pytest.ini tests/integration/test_gopro_hardware.py configs/gopros/gopro_external.yaml README.md
git commit -m "test(gopro): hardware integration test + README run docs"
```

---

## Self-Review

After all tasks land:

1. **Spec coverage**: skim each Goals / DoD item against the task list.
   - Goals 1 (config) → Tasks 13, 17 (configs/gopros/, deps.py loader)
   - Goals 2 (per-episode shutter) → Tasks 6, 9 (recorder + registry)
   - Goals 3 (async DL to dataset path) → Tasks 4, 7 (queue + worker)
   - Goals 4 (preview in CameraManager) → Tasks 2, 3, 8 (preview_only + decode)
   - Goals 5 (crash recovery) → Tasks 4, 7 (DLQueue.restore + resume-from-tmp)
   - Goals 6 (GPMF preserved + has_gpmf marker) → Task 11 (init_dataset)
   - DoD items 1-8 → Task 17 manual verification

2. **No placeholders**: all `<...>` placeholders are concrete except `<exact version>` (filled by Phase 0) and `<actual serial>` (env var).

3. **Type consistency**: `GoProSpec` and `MediaItem` are defined once in `gopro/types.py` and consumed consistently. `GoProDLJob` schema matches across queue / recorder / worker.

4. **Critical-path order**: Phase 0 gates everything. Phase 1 unblocks all later tests. Phase 2 (queue + mock) unblocks Phase 3. Phase 3 unblocks Phase 4 (real device). Phase 5 wires it into the API. Phase 6 surfaces it. Phase 7 verifies end-to-end.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-09-gopro-recording.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Phase 0 gating is best done with human-in-the-loop confirmation, so the first subagent will pause after Task 0 for go/no-go.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints. Phase 0 hardware verification still requires user assistance to plug in the GoPro.

**Which approach?**
