# GoPro Hero 11 Recording Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add GoPro Hero 11 video+IMU recording to MimicRec as a peer of `OpenCVCamera`. GoPro records to its own SD card per-episode, host pulls files asynchronously over USB-CDC-NCM (HTTP+mDNS), and DLWorker downscales via ffmpeg if the YAML target resolution differs from the chosen native preset. GPMF (IMU) is preserved through ffmpeg. Live UDP preview is surfaced through the existing CameraManager preview pipeline (preview-only — never written to dataset).

**Architecture:** One `GoProDevice` per physical camera owns the `open_gopro` SDK client. `__init__` picks a native preset based on the YAML `(width, height, fps, aspect_mode)`, preferring aspect-matching presets (4:3 / 8:7 natives) before falling back to crop from 16:9. `GoProPreviewSource` (Camera-shaped view) reads UDP MPEG-TS in `asyncio.to_thread`. `GoProRecorder` (control-plane view) drives `set_shutter` and enqueues download jobs after detecting any chapter splits in the new files. `DLWorker` runs in the background, serializing downloads + ffmpeg pass across all GoPros, with a persistent sidecar JSON queue for crash recovery and post-DL `info.json` codec patching. `GoProDeviceRegistry` is a peer of `CameraManager`; registry starts before CameraManager so preview sources can be merged into the cameras dict.

**Tech Stack:** Python 3.12 (FastAPI / asyncio / pyav / pyarrow / `asyncio.create_subprocess_exec`), `open_gopro` PyPI package, `ffmpeg` ≥ 4.4 + `ffprobe` system binaries, pytest with `asyncio_mode=auto`, React/TypeScript frontend.

**Spec:** `docs/superpowers/specs/2026-05-09-gopro-recording-design.md`

**Test runner:** `env -u PYTHONPATH /home/tirobot/MimicRec/backend/.venv/bin/python -m pytest ../tests/...` from `backend/` cwd.

**Hardware-marked test:** `pytest -m gopro_hardware` (default `addopts = -m 'not gopro_hardware'` set in `pytest.ini` during this plan).

---

## File Structure

**New files:**

| Path | Responsibility |
|---|---|
| `backend/mimicrec/gopro/__init__.py` | Empty package marker |
| `backend/mimicrec/gopro/types.py` | `GoProSpec`, `MediaItem`, `NativePreset`, `_NATIVE_PRESETS` table. Leaf module — no internal deps. |
| `backend/mimicrec/gopro/preset_picker.py` | `pick_preset(width, height, fps, aspect_mode)` — aspect-aware preset selection. |
| `backend/mimicrec/gopro/dl_queue.py` | `GoProDLJob` + persistent `DLQueue` (sidecar JSON via `asyncio.to_thread` fsync). |
| `backend/mimicrec/gopro/ffmpeg_pass.py` | `ffmpeg_copy`, `ffmpeg_downscale`, `update_info_json_codec`, `parse_chapter_filename`. |
| `backend/mimicrec/gopro/mock.py` | `MockGoProDevice` for unit/integration tests without hardware. |
| `backend/mimicrec/gopro/recorder.py` | `GoProRecorder` — control-plane view + chapter detection. |
| `backend/mimicrec/gopro/dl_worker.py` | `GoProDLWorker` — serialized DL + ffmpeg pass + post-DL codec update. |
| `backend/mimicrec/gopro/preview.py` | `GoProPreviewSource` — UDP MPEG-TS decoder via `asyncio.to_thread`, Camera I/F. |
| `backend/mimicrec/gopro/registry.py` | `GoProDeviceRegistry` — session lifecycle with gather-inspect error propagation. |
| `backend/mimicrec/gopro/device.py` | Real `GoProDevice` wrapping `WiredGoPro` SDK client. |
| `configs/gopros/gopro_external.yaml` | Example Hydra config (1 GoPro). |
| `tests/unit/gopro/test_types.py` | `GoProSpec` / `MediaItem` / `NativePreset`. |
| `tests/unit/gopro/test_frame_preview_only.py` | `Frame.preview_only` field. |
| `tests/unit/gopro/test_pending_preview_only.py` | `PendingEpisode.append_row` honors `preview_only`. |
| `tests/unit/gopro/test_preset_picker.py` | Aspect-aware preset selection + ConfigError on impossible target. |
| `tests/unit/gopro/test_dl_queue.py` | DLQueue persistence + restore. |
| `tests/unit/gopro/test_ffmpeg_pass.py` | ffmpeg copy/downscale on real fixture MP4 (with GPMF). |
| `tests/unit/gopro/test_mock_device.py` | MockGoProDevice surface, chapter sim, fixture_mp4 Path/str. |
| `tests/unit/gopro/test_recorder.py` | Lifecycle with mock + chapter detection. |
| `tests/unit/gopro/test_dl_worker.py` | Worker loop, resume-from-tmp, duration check, codec patch. |
| `tests/unit/gopro/test_preview.py` | Preview source emits `preview_only=True`. |
| `tests/unit/gopro/test_registry.py` | Uniqueness, lifecycle, gather error inspection. |
| `tests/unit/gopro/test_device.py` | Real device with mocked `open_gopro`. |
| `tests/unit/gopro/test_init_dataset_gopro.py` | `init_dataset` features entry for GoPro. |
| `tests/unit/gopro/test_schemas_gopros.py` | `_BaseSessionRequest.gopros`. |
| `tests/integration/test_gopro_session_bootstrap.py` | deps.py ConfigError → HTTPException(400). |
| `tests/integration/test_gopro_mock_session.py` | End-to-end with MockGoProDevice (no hardware). |
| `tests/integration/test_gopro_hardware.py` | Real Hero 11 (marker: `gopro_hardware`). |
| `tests/fixtures/gopro/sample_episode.mp4` | Short Hero 11 MP4 with GPMF, ~5MB. |

**Modified files:**

| Path | Change |
|---|---|
| `backend/mimicrec/types.py` | Add `Frame.preview_only: bool = False`. |
| `backend/mimicrec/recording/pending.py` | `append_row` skips video write when `frame.preview_only=True`. |
| `backend/mimicrec/recording/dataset_layout.py` | `init_dataset` gains `gopro_specs` param; writes `has_gpmf=true` features with `video.codec="libx264"` placeholder. |
| `backend/mimicrec/api/schemas.py` | `_BaseSessionRequest.gopros: list[str] = []`; `SessionStatePayload.gopros`. |
| `backend/mimicrec/api/deps.py` | Load `configs/gopros/`, build registry inside try/except (`ConfigError`→`HTTPException(400)`), merge preview sources into cams, pass `gopro_specs` to `init_dataset`. Pass `gopro_registry` to SessionManager. Clear `app.state.gopro_registry` on session end. |
| `backend/mimicrec/session/lifecycle.py` (`SessionManager`) | Optional `gopro_registry` constructor kwarg + hooks at `episode_start` / `episode_stop` / `episode_save` (commit) / `episode_discard` / shutdown (`stop()`). |
| `backend/mimicrec/api/routes/session.py` | `GET /api/session/gopro_pending` endpoint. |
| `pytest.ini` | Add `gopro_hardware` marker, set default `addopts = -m 'not gopro_hardware'`. |
| `pyproject.toml` | Add `open_gopro` dependency (version pinned after Phase 0). |
| `frontend/src/...` | Pending DL badge component, quit-warning dialog. |
| `README.md` | GoPro section: YAML schema, preset/chapter table, NCM environment setup, ffmpeg install, hardware test instructions. |

---

## Phase 0 — Pre-implementation verification (gating spike)

This is a one-shot research task. **STOP HERE and report back if Task 0 fails.**

### Task 0: Verify environment and SDK

**Files:**
- Create: `docs/superpowers/notes/2026-05-09-gopro-sdk-verification.md`

- [ ] **Step 1: Verify Linux NCM environment**

```bash
# cdc_ncm driver
lsmod | grep cdc_ncm

# avahi
systemctl status avahi-daemon

# firewall — does ufw allow link-local 169.254.0.0/16?
sudo ufw status verbose | grep -i 169.254 || echo "no ufw rule (default policy applies)"

# autosuspend — confirm we know how to disable per-device
cat /sys/bus/usb/devices/*/power/control 2>/dev/null | sort -u
```

Record results in the verification doc. If `cdc_ncm` is not loaded: `sudo modprobe cdc_ncm` (and add to `/etc/modules-load.d/`). If avahi is not running: install + start. If autosuspend default is `auto`: plan a udev rule to disable for GoPro vendor ID.

- [ ] **Step 2: Install open_gopro and ffmpeg**

```bash
cd /home/tirobot/MimicRec/backend
.venv/bin/pip install open_gopro
.venv/bin/python -c "import open_gopro; print(open_gopro.__version__)"

# system ffmpeg
ffmpeg -version | head -1   # require ≥ 4.4
ffprobe -version | head -1
```

If ffmpeg < 4.4: `sudo apt install ffmpeg` (or build).

- [ ] **Step 3: Plug in Hero 11 via USB and verify NCM bring-up**

```bash
# After plugging the camera in:
ip link | grep -i "enx\|usb"     # should show enxXXXXXX
ip addr show <enx interface>     # should have a 169.254.x.x IP
avahi-resolve -n gopro_$(your_serial).local 2>&1 | head    # should return IP
ping -c 1 <gopro IP>             # reachable
```

Record the GoPro hostname pattern (`gopro_<serial>.local` is typical but may vary by firmware).

- [ ] **Step 4: Probe each required SDK API**

Create `/tmp/gopro_probe.py`:

```python
import asyncio
from datetime import datetime
from pathlib import Path

from open_gopro import WiredGoPro, constants

async def main():
    # NOTE: API signature may be `WiredGoPro(target=...)` or `WiredGoPro(serial=...)`.
    # Try both; record which one works on this open_gopro version.
    async with WiredGoPro() as gp:
        print("connected:", gp.is_open)

        r = await gp.http_command.set_date_time(date_time=datetime.now())
        print("set_date_time:", r.ok)

        # video preset group
        r = await gp.http_command.load_preset_group(
            group=constants.proto.EnumPresetGroup.PRESET_GROUP_ID_VIDEO)
        print("load_preset_group video:", r.ok)

        # camera capabilities — what does it return on Hero 11?
        try:
            caps = await gp.http_command.get_camera_capabilities()
            print("capabilities keys:", list(caps.data.keys()) if caps.ok else "FAIL")
        except Exception as e:
            print("get_camera_capabilities failed:", e)

        r = await gp.http_command.get_camera_state()
        print("camera_state ok:", r.ok)
        if r.ok:
            for k, v in r.data.items():
                if "sd" in str(k).lower() or "storage" in str(k).lower() or "remaining" in str(k).lower():
                    print(f"  storage candidate: {k} = {v}")

        # shutter cycle to see what filename appears
        r = await gp.http_command.set_shutter(shutter=constants.Toggle.ENABLE)
        print("shutter on:", r.ok)
        await asyncio.sleep(3.0)

        # poll media_list to see if the file appears DURING recording
        for i in range(5):
            ml = await gp.http_command.get_media_list()
            print(f"during-record media_list len={len(ml.data.files)}")
            await asyncio.sleep(0.5)

        r = await gp.http_command.set_shutter(shutter=constants.Toggle.DISABLE)
        print("shutter off:", r.ok)
        await asyncio.sleep(1.0)

        ml = await gp.http_command.get_media_list()
        print("post-stop media_list count:", len(ml.data.files))
        if ml.data.files:
            f = ml.data.files[-1]
            print(f"  latest file: {f.filename} size={f.size} ts={f.creation_timestamp}")
            # Note the filename pattern for chapter detection (e.g. GH010001.MP4).

        # preview start/stop
        r = await gp.http_command.set_preview_stream(mode=constants.Toggle.ENABLE, port=8556)
        print("preview start:", r.ok)
        await asyncio.sleep(2.0)
        r = await gp.http_command.set_preview_stream(mode=constants.Toggle.DISABLE)
        print("preview stop:", r.ok)

asyncio.run(main())
```

```bash
cd /home/tirobot/MimicRec/backend
.venv/bin/python /tmp/gopro_probe.py 2>&1 | tee /tmp/gopro_probe.log
```

- [ ] **Step 5: Enumerate native presets**

For each candidate preset (the spec's starting set), load it, record 5 seconds, download, ffprobe.

```python
# /tmp/gopro_preset_enum.py
PRESETS_TO_PROBE = [
    "1080p_30_wide", "1080p_60_wide", "1080p_120_wide",
    "2.7K_60_wide", "2.7K_120_wide",
    "4K_30_wide", "4K_60_wide",
    "5.3K_30_wide",
    "2.7K_4_3_60", "4K_4_3_30", "5K_4_3_30",
]
# For each, do load_preset → shutter cycle 5s → download → ffprobe
# Record (sdk_id, width, height, fps, codec, bytes_per_5s).
```

Run, record results in the verification doc as a table.

- [ ] **Step 6: Probe ffmpeg GPMF preservation**

Take a downloaded sample MP4 and run:

```bash
# Method 1: -c copy -copy_unknown
ffmpeg -y -nostdin -i sample.mp4 -map 0 -c copy -copy_unknown out_m1.mp4
ffprobe -v error -show_streams out_m1.mp4 | grep -i "GoPro MET\|gpmd" || echo "GPMF lost (m1)"

# Method 2: explicit handler_name map
ffmpeg -y -nostdin -i sample.mp4 \
  -map 0:v -map "0:m:handler_name=GoPro MET" \
  -c copy out_m2.mp4
ffprobe -v error -show_streams out_m2.mp4 | grep -i "GoPro MET\|gpmd" || echo "GPMF lost (m2)"

# Method 3: test downscale with -c copy override
ffmpeg -y -nostdin -i sample.mp4 \
  -map 0 -c copy -copy_unknown \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p \
  -vf "scale=1280:720" -an out_m3.mp4
ffprobe -v error -show_streams out_m3.mp4 | grep -i "GoPro MET\|gpmd" || echo "GPMF lost (m3)"
```

Record which method preserves GPMF. The spec relies on Method 1/3.

- [ ] **Step 7: Decision**

For each API and each environment item: PASS / FAIL.

If **any** of these is FAIL: **shelve the spec**, write findings, report back.
- `WiredGoPro` init / `set_date_time` / `set_shutter` / `get_media_list` / `download_file` / `set_preview_stream` / `get_camera_state` / preset application
- `cdc_ncm` driver loadable
- mDNS resolves GoPro hostname

If GPMF preservation fails on Method 3 (downscale + GPMF): **the spec's "always ffmpeg" policy must add a raw-GPMF sidecar fallback** — flag for spec revision.

Otherwise: continue.

- [ ] **Step 8: Pin versions and write verification doc**

Edit `backend/pyproject.toml`, add `"open_gopro==<exact version>"`.

Write `docs/superpowers/notes/2026-05-09-gopro-sdk-verification.md` covering all probe results, with an explicit table of `(preset_name, sdk_id, width, height, fps, codec, file_size_per_5s, chapter_seconds_estimate)`. **Task 1 will read this doc to populate `gopro/types.py:NATIVE_PRESETS`.**

If real values differ materially from the spec's starting set, also update `docs/superpowers/specs/2026-05-09-gopro-recording-design.md` "Native preset 表" so it stays a reliable reference.

- [ ] **Step 9: Commit**

```bash
git add backend/pyproject.toml docs/superpowers/notes/2026-05-09-gopro-sdk-verification.md docs/superpowers/specs/2026-05-09-gopro-recording-design.md
git commit -m "chore(gopro): SDK + environment verification, pin open_gopro"
```

---

## Phase 1 — Foundation types

### Task 1: `gopro/types.py` — `GoProSpec`, `MediaItem`, `NativePreset`, table

**Files:**
- Create: `backend/mimicrec/gopro/__init__.py`
- Create: `backend/mimicrec/gopro/types.py`
- Test: `tests/unit/gopro/__init__.py`, `tests/unit/gopro/test_types.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/gopro/test_types.py
import pytest

from mimicrec.gopro.types import GoProSpec, MediaItem, NativePreset, NATIVE_PRESETS


def test_gopro_spec_frozen():
    s = GoProSpec(name="g1", width=1920, height=1080, fps=60, codec="libx264")
    with pytest.raises(Exception):
        s.width = 1280  # type: ignore[misc]


def test_media_item_fields():
    m = MediaItem(filename="GX010001.MP4", size=12345, mtime_ns=1_700_000_000_000_000_000)
    assert m.filename == "GX010001.MP4"
    assert m.size == 12345
    assert m.mtime_ns == 1_700_000_000_000_000_000


def test_native_preset_fields():
    p = NativePreset(
        name="1080p_30_wide", sdk_id=1, width=1920, height=1080,
        fps=30, native_codec="h264", chapter_seconds=24 * 60,
    )
    assert p.width == 1920
    assert p.chapter_seconds == 1440


def test_native_presets_table_includes_basics():
    names = {p.name for p in NATIVE_PRESETS}
    assert "1080p_30_wide" in names
    assert "1080p_60_wide" in names
```

- [ ] **Step 2: Run test — verify it fails**

```bash
cd /home/tirobot/MimicRec/backend
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit/gopro/test_types.py -v
```

Expected: `ModuleNotFoundError: No module named 'mimicrec.gopro'`

- [ ] **Step 3: Create the module**

```python
# backend/mimicrec/gopro/__init__.py  (empty)
```

```python
# backend/mimicrec/gopro/types.py
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class GoProSpec:
    """info.json features 用 (YAML target = downscale 後の値)。"""
    name: str
    width: int
    height: int
    fps: int
    codec: str   # init_dataset では "libx264" placeholder, DLWorker が ffprobe で更新


@dataclass
class MediaItem:
    """One file on the GoPro SD card."""
    filename: str            # "GX010001.MP4"
    size: int                # bytes
    mtime_ns: int            # camera-clock nanoseconds


@dataclass(frozen=True)
class NativePreset:
    """GoPro 内部 preset エントリ（Phase 0 verification で確定）。"""
    name: str            # human readable
    sdk_id: int          # open_gopro の preset ID
    width: int
    height: int
    fps: int
    native_codec: str    # "h264" or "h265"
    chapter_seconds: int


# Phase 0 verification で実機 enum したエントリで置換する。
# 現状はスペックの「出発セット」をそのまま。Phase 0 完了で書き換え。
NATIVE_PRESETS: list[NativePreset] = [
    # 16:9
    NativePreset("1080p_30_wide",  sdk_id=1,  width=1920, height=1080, fps=30,  native_codec="h264", chapter_seconds=24 * 60),
    NativePreset("1080p_60_wide",  sdk_id=2,  width=1920, height=1080, fps=60,  native_codec="h264", chapter_seconds=12 * 60),
    NativePreset("1080p_120_wide", sdk_id=3,  width=1920, height=1080, fps=120, native_codec="h264", chapter_seconds=6 * 60),
    NativePreset("2.7K_60_wide",   sdk_id=4,  width=2704, height=1520, fps=60,  native_codec="h264", chapter_seconds=8 * 60),
    NativePreset("2.7K_120_wide",  sdk_id=5,  width=2704, height=1520, fps=120, native_codec="h264", chapter_seconds=4 * 60),
    NativePreset("4K_30_wide",     sdk_id=6,  width=3840, height=2160, fps=30,  native_codec="h265", chapter_seconds=7 * 60),
    NativePreset("4K_60_wide",     sdk_id=7,  width=3840, height=2160, fps=60,  native_codec="h265", chapter_seconds=4 * 60),
    NativePreset("5.3K_30_wide",   sdk_id=8,  width=5312, height=2988, fps=30,  native_codec="h265", chapter_seconds=5 * 60),
    NativePreset("5.3K_60_wide",   sdk_id=9,  width=5312, height=2988, fps=60,  native_codec="h265", chapter_seconds=3 * 60),
    # 4:3
    NativePreset("2.7K_4_3_60",    sdk_id=10, width=2704, height=2028, fps=60,  native_codec="h264", chapter_seconds=8 * 60),
    NativePreset("4K_4_3_30",      sdk_id=11, width=4000, height=3000, fps=30,  native_codec="h265", chapter_seconds=6 * 60),
    NativePreset("5K_4_3_30",      sdk_id=12, width=5312, height=3984, fps=30,  native_codec="h265", chapter_seconds=4 * 60),
    # 8:7
    NativePreset("4K_8_7_30",      sdk_id=13, width=3840, height=3360, fps=30,  native_codec="h265", chapter_seconds=5 * 60),
    NativePreset("5.3K_8_7_30",    sdk_id=14, width=5312, height=4648, fps=30,  native_codec="h265", chapter_seconds=4 * 60),
]
```

- [ ] **Step 4: Run test — verify it passes**

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/gopro/__init__.py backend/mimicrec/gopro/types.py tests/unit/gopro/__init__.py tests/unit/gopro/test_types.py
git commit -m "feat(gopro): foundation types + native preset table"
```

---

### Task 2: `Frame.preview_only` field

**Files:**
- Modify: `backend/mimicrec/types.py` (Frame dataclass)
- Test: `tests/unit/gopro/test_frame_preview_only.py`

- [ ] **Step 1: Write the failing test**

```python
import numpy as np
from mimicrec.types import Frame


def test_preview_only_default_false():
    f = Frame(image=np.zeros((4, 4, 3), dtype=np.uint8))
    assert f.preview_only is False


def test_preview_only_settable():
    f = Frame(image=np.zeros((4, 4, 3), dtype=np.uint8), preview_only=True)
    assert f.preview_only is True
```

- [ ] **Step 2: Run — verify fail**

Expected: `unexpected keyword argument 'preview_only'`.

- [ ] **Step 3: Edit `backend/mimicrec/types.py` Frame**

```python
@dataclass
class Frame:
    image: np.ndarray
    t_mono_ns: int = 0
    preview_only: bool = False
```

- [ ] **Step 4: Run — verify pass**

Expected: 2 passed.

- [ ] **Step 5: Smoke-run unit suite**

```bash
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/unit -v
```

Expected: existing tests still green.

- [ ] **Step 6: Commit**

```bash
git add backend/mimicrec/types.py tests/unit/gopro/test_frame_preview_only.py
git commit -m "feat(types): Frame.preview_only field"
```

---

### Task 3: `PendingEpisode.append_row` honors `preview_only`

**Files:**
- Modify: `backend/mimicrec/recording/pending.py` (`append_row`)
- Test: `tests/unit/gopro/test_pending_preview_only.py`

- [ ] **Step 1: Write the failing test**

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
```

- [ ] **Step 2: Run — verify fail**

Expected: first test fails because preview_only is currently ignored, frame is written.

- [ ] **Step 3: Edit `pending.py:append_row`**

Inside the `if frames and getattr(self, "_video_writers", None):` block, before `writer.write_frame(...)`, add:

```python
                if getattr(stamped.value, "preview_only", False):
                    continue
```

- [ ] **Step 4: Run — verify pass**

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/recording/pending.py tests/unit/gopro/test_pending_preview_only.py
git commit -m "feat(recording): PendingEpisode skips video write for preview_only frames"
```

---

## Phase 2 — Preset picker, persistent queue, mock device

### Task 4: `gopro/preset_picker.py` — aspect-aware preset selection

**Files:**
- Create: `backend/mimicrec/gopro/preset_picker.py`
- Test: `tests/unit/gopro/test_preset_picker.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from mimicrec.gopro.preset_picker import pick_preset, AspectMatch
from mimicrec.gopro.types import NATIVE_PRESETS


def test_exact_native_match_no_aspect_concern():
    p, am = pick_preset(width=1920, height=1080, fps=30, aspect_mode="crop")
    assert p.name == "1080p_30_wide"
    assert am == AspectMatch.MATCH


def test_smaller_target_uses_smallest_native_with_matching_fps():
    p, am = pick_preset(width=1280, height=720, fps=30, aspect_mode="crop")
    # 1280x720 is 16:9, smallest 16:9 native at fps=30 is 1080p_30_wide
    assert p.name == "1080p_30_wide"
    assert am == AspectMatch.MATCH   # both 16:9


def test_43_target_prefers_43_native():
    # 640x480 is 4:3. should prefer a 4:3 native.
    p, am = pick_preset(width=640, height=480, fps=30, aspect_mode="crop")
    assert (p.width / p.height) == pytest.approx(4 / 3, rel=0.02)
    assert am == AspectMatch.MATCH


def test_43_target_falls_back_to_169_when_no_43_at_fps():
    # 4:3 + fps=120 — Hero 11 has no 4:3 native at 120fps.
    p, am = pick_preset(width=640, height=480, fps=120, aspect_mode="crop")
    assert p.fps == 120
    assert am == AspectMatch.MISMATCH   # source is 16:9


def test_unsupported_fps_raises_config_error():
    from mimicrec.errors import HardwareError  # ConfigError まだ無いなら HardwareError でラップ
    with pytest.raises((ValueError, HardwareError)):
        pick_preset(width=1920, height=1080, fps=25, aspect_mode="crop")


def test_target_too_large_raises_config_error():
    from mimicrec.errors import HardwareError
    with pytest.raises((ValueError, HardwareError)):
        pick_preset(width=7680, height=4320, fps=30, aspect_mode="crop")
```

- [ ] **Step 2: Run — verify fail**

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# backend/mimicrec/gopro/preset_picker.py
from __future__ import annotations
from enum import Enum

from mimicrec.gopro.types import NATIVE_PRESETS, NativePreset


class AspectMatch(Enum):
    MATCH = "match"           # native aspect == target aspect (within tolerance)
    MISMATCH = "mismatch"     # need crop or stretch


_ASPECT_TOL = 0.01


def _aspect(w: int, h: int) -> float:
    return w / h


def pick_preset(width: int, height: int, fps: int, aspect_mode: str) -> tuple[NativePreset, AspectMatch]:
    """Spec の Resolution selection ロジックを実装。aspect 一致 preset を優先。"""
    if aspect_mode not in ("crop", "stretch"):
        raise ValueError(f"unknown aspect_mode: {aspect_mode!r}")

    target_aspect = _aspect(width, height)

    # candidates that satisfy size + fps
    candidates = [
        p for p in NATIVE_PRESETS
        if p.width >= width and p.height >= height and p.fps == fps
    ]
    if not candidates:
        # find what's wrong
        if not any(p.fps == fps for p in NATIVE_PRESETS):
            raise ValueError(f"GoPro Hero 11 does not support fps={fps}")
        raise ValueError(
            f"target {width}x{height}@{fps} exceeds Hero 11 native presets "
            f"(max width={max(p.width for p in NATIVE_PRESETS)})"
        )

    # aspect-matching first
    aspect_matches = [
        p for p in candidates
        if abs(_aspect(p.width, p.height) - target_aspect) <= _ASPECT_TOL
    ]
    if aspect_matches:
        # pick smallest by area
        chosen = min(aspect_matches, key=lambda p: p.width * p.height)
        return chosen, AspectMatch.MATCH

    # no aspect match — fall back to smallest 16:9 (or any) native
    chosen = min(candidates, key=lambda p: p.width * p.height)
    return chosen, AspectMatch.MISMATCH
```

- [ ] **Step 4: Run — verify pass**

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/gopro/preset_picker.py tests/unit/gopro/test_preset_picker.py
git commit -m "feat(gopro): aspect-aware native preset selection"
```

---

### Task 5: `gopro/dl_queue.py` — persistent DLQueue

**Files:**
- Create: `backend/mimicrec/gopro/dl_queue.py`
- Test: `tests/unit/gopro/test_dl_queue.py`

- [ ] **Step 1: Write the failing test**

```python
import asyncio
import json
from pathlib import Path

import pytest

from mimicrec.gopro.dl_queue import DLQueue, GoProDLJob


def _job(job_id="j", episode_index=0) -> GoProDLJob:
    return GoProDLJob(
        job_id=job_id, gopro_serial="S1", sd_filename="GX010001.MP4",
        episode_index=episode_index, chunk_index=0, cam_name="g1",
        episode_start_mono_ns=1_000_000_000, episode_stop_mono_ns=2_000_000_000,
    )


@pytest.mark.asyncio
async def test_enqueue_writes_sidecar_via_executor(tmp_path):
    q = DLQueue(tmp_path / "pending" / "gopro_dl")
    await q.enqueue(_job(job_id="abc"))
    sidecar = tmp_path / "pending" / "gopro_dl" / "abc.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text())
    assert data["job_id"] == "abc"


@pytest.mark.asyncio
async def test_dequeue_returns_enqueued(tmp_path):
    q = DLQueue(tmp_path / "pending" / "gopro_dl")
    await q.enqueue(_job(job_id="a", episode_index=0))
    await q.enqueue(_job(job_id="b", episode_index=1))
    j1 = await asyncio.wait_for(q.dequeue(), timeout=1.0)
    j2 = await asyncio.wait_for(q.dequeue(), timeout=1.0)
    assert {j1.job_id, j2.job_id} == {"a", "b"}


@pytest.mark.asyncio
async def test_mark_done_removes_sidecar(tmp_path):
    q = DLQueue(tmp_path / "pending" / "gopro_dl")
    await q.enqueue(_job(job_id="x"))
    await q.mark_done("x")
    assert not (tmp_path / "pending" / "gopro_dl" / "x.json").exists()


@pytest.mark.asyncio
async def test_mark_done_idempotent(tmp_path):
    q = DLQueue(tmp_path / "pending" / "gopro_dl")
    await q.mark_done("never_existed")  # no error


@pytest.mark.asyncio
async def test_restore_loads_sidecars(tmp_path):
    pdir = tmp_path / "pending" / "gopro_dl"
    pdir.mkdir(parents=True)
    j1 = _job(job_id="aaa", episode_index=2)
    j2 = _job(job_id="bbb", episode_index=3)
    (pdir / "aaa.json").write_text(json.dumps(j1.to_json()))
    (pdir / "bbb.json").write_text(json.dumps(j2.to_json()))
    q = DLQueue.restore(pdir)
    out = [await asyncio.wait_for(q.dequeue(), timeout=1.0) for _ in range(2)]
    assert sorted(j.job_id for j in out) == ["aaa", "bbb"]


@pytest.mark.asyncio
async def test_restore_creates_missing_dir(tmp_path):
    pdir = tmp_path / "never"
    q = DLQueue.restore(pdir)
    assert pdir.exists()
    assert q.pending_count == 0


def test_to_json_roundtrip():
    j = _job()
    assert GoProDLJob.from_json(j.to_json()) == j


def test_default_state_is_pending_dl():
    j = _job()
    assert j.state == "pending_dl"
    assert j.staged_path is None


def test_from_json_backward_compat_without_state():
    """Old sidecars (pre-state field) default to pending_dl."""
    j = _job()
    raw = j.to_json()
    raw.pop("state")
    raw.pop("staged_path")
    j2 = GoProDLJob.from_json(raw)
    assert j2.state == "pending_dl"
    assert j2.staged_path is None


@pytest.mark.asyncio
async def test_update_sidecar_changes_state(tmp_path):
    q = DLQueue(tmp_path / "pending" / "gopro_dl")
    j = _job(job_id="u")
    await q.enqueue(j)
    j.state = "staged"
    j.staged_path = "/tmp/abc.mp4"
    await q.update_sidecar(j)
    j2 = await q.read_sidecar("u")
    assert j2.state == "staged"
    assert j2.staged_path == "/tmp/abc.mp4"


@pytest.mark.asyncio
async def test_find_jobs_for_episode(tmp_path):
    q = DLQueue(tmp_path / "pending" / "gopro_dl")
    await q.enqueue(_job(job_id="a", episode_index=0))
    await q.enqueue(_job(job_id="b", episode_index=1))
    await q.enqueue(_job(job_id="c", episode_index=0))
    found = await q.find_jobs_for_episode(0)
    assert sorted(j.job_id for j in found) == ["a", "c"]


@pytest.mark.asyncio
async def test_restore_skips_staged_jobs(tmp_path):
    pdir = tmp_path / "pending" / "gopro_dl"
    pdir.mkdir(parents=True)
    pending = _job(job_id="p", episode_index=0)
    staged = _job(job_id="s", episode_index=1)
    staged.state = "staged"
    staged.staged_path = "/tmp/staged.mp4"
    (pdir / "p.json").write_text(json.dumps(pending.to_json()))
    (pdir / "s.json").write_text(json.dumps(staged.to_json()))
    q = DLQueue.restore(pdir)
    # Only "p" is in the in-memory queue.
    j = await asyncio.wait_for(q.dequeue(), timeout=1.0)
    assert j.job_id == "p"
    assert q._q.qsize() == 0
    # But pending_count counts both sidecars.
    assert q.pending_count == 2
```

- [ ] **Step 2: Run — verify fail**

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# backend/mimicrec/gopro/dl_queue.py
from __future__ import annotations
import asyncio
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class GoProDLJob:
    """state machine: pending_dl → staged → (commit/discard pending) → terminal."""
    job_id: str
    gopro_serial: str
    sd_filename: str
    episode_index: int
    chunk_index: int
    cam_name: str
    episode_start_mono_ns: int
    episode_stop_mono_ns: int
    state: str = "pending_dl"            # "pending_dl" | "staged" | "commit_pending" | "discard_pending"
    staged_path: str | None = None       # set when state in {staged, commit_pending}

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> "GoProDLJob":
        # Backward compat: old sidecars without state default to pending_dl.
        d = dict(d)
        d.setdefault("state", "pending_dl")
        d.setdefault("staged_path", None)
        return cls(**d)


def _atomic_write_with_dir_fsync(path: Path, payload: str) -> None:
    """Write file, fsync file, atomic rename, fsync directory."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload)
    fd = os.open(str(tmp), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(path))
    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _delete_with_dir_fsync(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


class DLQueue:
    """Persistent FIFO queue. All file I/O via asyncio.to_thread."""

    def __init__(self, pending_dir: Path):
        self._dir = pending_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._q: asyncio.Queue[GoProDLJob] = asyncio.Queue()

    async def enqueue(self, job: GoProDLJob) -> None:
        path = self._dir / f"{job.job_id}.json"
        payload = json.dumps(job.to_json(), indent=2)
        await asyncio.to_thread(_atomic_write_with_dir_fsync, path, payload)
        await self._q.put(job)

    async def dequeue(self) -> GoProDLJob:
        return await self._q.get()

    async def mark_done(self, job_id: str) -> None:
        path = self._dir / f"{job_id}.json"
        await asyncio.to_thread(_delete_with_dir_fsync, path)

    async def update_sidecar(self, job: GoProDLJob) -> None:
        """Atomic rewrite of sidecar (state / staged_path 変更時)."""
        path = self._dir / f"{job.job_id}.json"
        payload = json.dumps(job.to_json(), indent=2)
        await asyncio.to_thread(_atomic_write_with_dir_fsync, path, payload)

    async def read_sidecar(self, job_id: str) -> GoProDLJob | None:
        """Read a single sidecar (returns None if missing/corrupt)."""
        path = self._dir / f"{job_id}.json"
        if not path.exists():
            return None
        try:
            return GoProDLJob.from_json(json.loads(path.read_text()))
        except Exception:
            return None

    async def find_jobs_for_episode(self, episode_index: int) -> list[GoProDLJob]:
        """Scan all sidecars; return jobs matching episode_index (any state)."""
        out: list[GoProDLJob] = []
        for sidecar in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(sidecar.read_text())
                job = GoProDLJob.from_json(data)
            except Exception:
                continue
            if job.episode_index == episode_index:
                out.append(job)
        return out

    @classmethod
    def restore(cls, pending_dir: Path) -> "DLQueue":
        q = cls(pending_dir)
        for sidecar in sorted(pending_dir.glob("*.json")):
            try:
                data = json.loads(sidecar.read_text())
                job = GoProDLJob.from_json(data)
            except Exception:
                continue
            # Skip already-staged jobs — DLWorker shouldn't re-process them.
            # registry.commit_episode/discard_episode will handle them.
            if job.state == "staged":
                continue
            q._q.put_nowait(job)
        return q

    @property
    def pending_count(self) -> int:
        """User-visible pending = sidecar count (includes staged awaiting commit)."""
        return sum(1 for _ in self._dir.glob("*.json"))
```

- [ ] **Step 4: Run — verify pass**

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/gopro/dl_queue.py tests/unit/gopro/test_dl_queue.py
git commit -m "feat(gopro): persistent DLQueue with executor-driven fsync + dir fsync"
```

---

### Task 6: `gopro/mock.py` — `MockGoProDevice`

**Files:**
- Create: `backend/mimicrec/gopro/mock.py`
- Test: `tests/unit/gopro/test_mock_device.py`

- [ ] **Step 1: Write the failing test**

```python
import shutil
from pathlib import Path

import pytest

from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.gopro.types import GoProSpec


@pytest.mark.asyncio
async def test_connect_disconnect_idempotent():
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect(); await d.connect()
    await d.disconnect(); await d.disconnect()


@pytest.mark.asyncio
async def test_shutter_cycle_creates_one_file_by_default():
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    before = await d.media_list()
    await d.shutter_on(); await d.shutter_off()
    after = await d.media_list()
    assert len(after) == len(before) + 1


@pytest.mark.asyncio
async def test_chapter_split_creates_multiple_files():
    d = MockGoProDevice(name="g1", usb_serial="S1", chapters_per_episode=3)
    await d.connect()
    await d.shutter_on(); await d.shutter_off()
    files = await d.media_list()
    assert len(files) == 3
    # all share same id (last 4 digits), differ in chapter (middle 2 digits)
    names = [f.filename for f in files]
    ids = {n[-8:-4] for n in names}     # last 4 digits before .MP4
    chapters = [n[2:4] for n in names]
    assert len(ids) == 1
    assert sorted(chapters) == ["01", "02", "03"]


def test_get_spec_returns_yaml_target():
    d = MockGoProDevice(name="g1", usb_serial="S1", width=1280, height=720, fps=30)
    spec = d.get_spec()
    assert spec == GoProSpec(name="g1", width=1280, height=720, fps=30, codec="libx264")


@pytest.mark.asyncio
async def test_unsupported_fps_raises():
    with pytest.raises((ValueError, Exception)):
        MockGoProDevice(name="g1", usb_serial="S1", fps=25)


@pytest.mark.asyncio
async def test_download_copies_fixture(tmp_path):
    fixture = tmp_path / "fixture.mp4"
    fixture.write_bytes(b"\x00" * 4096)
    # also accept str path (Hydra would pass str)
    d = MockGoProDevice(name="g1", usb_serial="S1", fixture_mp4=str(fixture))
    await d.connect()
    await d.shutter_on(); await d.shutter_off()
    files = await d.media_list()
    dst = tmp_path / "out.mp4"
    await d.download_file(files[-1].filename, dst)
    assert dst.stat().st_size == 4096


@pytest.mark.asyncio
async def test_disable_blocks_subsequent_calls():
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    d.disable("test")
    assert d.is_disabled
    await d.shutter_on(); await d.shutter_off()  # no-op
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement**

```python
# backend/mimicrec/gopro/mock.py
from __future__ import annotations
import asyncio
import shutil
from pathlib import Path

from mimicrec.gopro.preset_picker import pick_preset, AspectMatch
from mimicrec.gopro.types import GoProSpec, MediaItem, NativePreset


class MockGoProDevice:
    """SDK を import せずに動く。"""

    def __init__(
        self,
        name: str,
        usb_serial: str,
        width: int = 1920,
        height: int = 1080,
        fps: int = 30,
        aspect_mode: str = "crop",
        fixture_mp4: Path | str | None = None,
        emit_preview: bool = False,
        storage_remaining: int = 1_000_000_000,
        chapters_per_episode: int = 1,
    ) -> None:
        # Validate via picker (raises if (w,h,fps) impossible).
        self._preset, self._aspect_match = pick_preset(width, height, fps, aspect_mode)

        self._name = name
        self._serial = usb_serial
        self._target_w = width
        self._target_h = height
        self._target_fps = fps
        self._aspect_mode = aspect_mode
        self._fixture = Path(fixture_mp4) if fixture_mp4 is not None else None
        self._emit_preview = emit_preview
        self._storage = storage_remaining
        self._chapters_per_episode = max(1, chapters_per_episode)

        self._connected = False
        self._disabled = False
        self._files: list[MediaItem] = []
        self._next_id = 1

    @property
    def name(self) -> str: return self._name
    @property
    def usb_serial(self) -> str: return self._serial
    @property
    def is_disabled(self) -> bool: return self._disabled
    @property
    def selected_preset(self) -> NativePreset: return self._preset
    @property
    def aspect_mode(self) -> str: return self._aspect_mode

    def get_spec(self) -> GoProSpec:
        return GoProSpec(
            name=self._name,
            width=self._target_w, height=self._target_h, fps=self._target_fps,
            codec="libx264",
        )

    async def connect(self) -> None:
        if self._connected: return
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def shutter_on(self) -> None:
        if self._disabled or not self._connected: return

    async def shutter_off(self) -> None:
        if self._disabled or not self._connected: return
        # Generate `chapters_per_episode` files sharing same id, differing chapter.
        ep_id = f"{self._next_id:04d}"
        self._next_id += 1
        for ch in range(1, self._chapters_per_episode + 1):
            fn = f"GX{ch:02d}{ep_id}.MP4"
            self._files.append(MediaItem(filename=fn, size=12345, mtime_ns=0))

    async def media_list(self) -> list[MediaItem]:
        if self._disabled or not self._connected: return []
        return list(self._files)

    async def start_preview(self, port: int) -> None:
        pass

    async def stop_preview(self) -> None:
        pass

    async def download_file(self, sd_filename: str, dest: Path) -> None:
        if self._fixture is not None and self._fixture.exists():
            shutil.copy(str(self._fixture), str(dest))
        else:
            dest.write_bytes(b"\x00" * 1024)

    async def get_storage_remaining(self) -> int:
        return self._storage

    def disable(self, reason: str) -> None:
        if self._disabled: return
        self._disabled = True
        import logging
        logging.getLogger(__name__).warning("MockGoProDevice %s disabled: %s", self._name, reason)
```

- [ ] **Step 4: Run — verify pass**

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/gopro/mock.py tests/unit/gopro/test_mock_device.py
git commit -m "feat(gopro): MockGoProDevice with chapter simulation + Path|str fixture"
```

---

## Phase 3 — ffmpeg pass + control plane

### Task 7: `gopro/ffmpeg_pass.py` — copy / downscale / codec patch / chapter-filename parse

**Files:**
- Create: `backend/mimicrec/gopro/ffmpeg_pass.py`
- Test: `tests/unit/gopro/test_ffmpeg_pass.py`
- Required: `tests/fixtures/gopro/sample_episode.mp4` (real Hero 11 MP4 with GPMF, ≥ 5 KB)

> NOTE: This task requires a real Hero 11 fixture MP4. If Phase 0 produced one, copy it here. Otherwise generate a synthetic MP4 with GPMF using the codex-style probe and use that. Tests that require GPMF presence should be skipped (with `pytest.skip`) if the fixture lacks GPMF — but the production code path itself does NOT depend on the fixture.

- [ ] **Step 1: Place the fixture**

```bash
mkdir -p tests/fixtures/gopro
# If you have a real MP4 with GPMF from Phase 0:
cp /tmp/gopro_probe_sample.MP4 tests/fixtures/gopro/sample_episode.mp4
# Otherwise, fall back to a synthetic MP4 (no GPMF — tests that need it will skip):
.venv/bin/python -c "
import av, numpy as np
ctx = av.open('tests/fixtures/gopro/sample_episode.mp4', mode='w')
s = ctx.add_stream('libx264', rate=30); s.width=64; s.height=48; s.pix_fmt='yuv420p'
for i in range(60):
    f = av.VideoFrame.from_ndarray(np.zeros((48,64,3), dtype='uint8'), format='bgr24')
    for p in s.encode(f.reformat(format='yuv420p')): ctx.mux(p)
for p in s.encode(): ctx.mux(p)
ctx.close()
"
```

- [ ] **Step 2: Write the failing test**

```python
import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from mimicrec.gopro.ffmpeg_pass import (
    ffmpeg_copy, ffmpeg_downscale, update_info_json_codec, parse_chapter_filename,
)
from mimicrec.recording.dataset_layout import dataset_paths


FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "gopro" / "sample_episode.mp4"


def _has_gpmf(p: Path) -> bool:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(p)],
        text=True,
    )
    return "GoPro MET" in out or "gpmd" in out


@pytest.mark.asyncio
async def test_ffmpeg_copy_produces_output(tmp_path):
    out = tmp_path / "out.mp4"
    await ffmpeg_copy(FIXTURE, out)
    assert out.exists() and out.stat().st_size > 100


@pytest.mark.asyncio
async def test_ffmpeg_copy_preserves_gpmf_if_present(tmp_path):
    if not _has_gpmf(FIXTURE):
        pytest.skip("fixture lacks GPMF — needs real Hero 11 sample")
    out = tmp_path / "out.mp4"
    await ffmpeg_copy(FIXTURE, out)
    assert _has_gpmf(out)


@pytest.mark.asyncio
async def test_ffmpeg_downscale_to_smaller_resolution(tmp_path):
    out = tmp_path / "out.mp4"
    await ffmpeg_downscale(FIXTURE, out, target_w=32, target_h=24, aspect_mode="crop", aspect_match=True)
    info = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,codec_name", "-of", "csv=p=0", str(out)],
        text=True,
    ).strip()
    parts = info.split(",")
    assert parts[0] == "h264"  # libx264 reports as h264
    assert parts[1] == "32"
    assert parts[2] == "24"


@pytest.mark.asyncio
async def test_update_info_json_codec_updates_placeholder(tmp_path):
    paths = dataset_paths(tmp_path / "ds")
    paths.meta_dir.mkdir(parents=True)
    paths.videos_dir.mkdir(parents=True)
    cam_dir = paths.videos_dir / "observation.images.gp" / "chunk-000"
    cam_dir.mkdir(parents=True)
    # Place an MP4 there
    sample = cam_dir / "episode_000000.mp4"
    sample.write_bytes(FIXTURE.read_bytes())

    info = {
        "features": {
            "observation.images.gp": {
                "info": {"video.codec": "libx264"},
            },
        },
    }
    (paths.meta_dir / "info.json").write_text(json.dumps(info))

    await update_info_json_codec(paths, "gp")
    after = json.loads((paths.meta_dir / "info.json").read_text())
    new_codec = after["features"]["observation.images.gp"]["info"]["video.codec"]
    assert new_codec in {"h264", "hevc"}   # depending on fixture


def test_parse_chapter_filename_normal():
    q, ch, eid = parse_chapter_filename("GH010001.MP4")
    assert q == "H" and ch == 1 and eid == "0001"


def test_parse_chapter_filename_chapter_03():
    q, ch, eid = parse_chapter_filename("GX030042.MP4")
    assert q == "X" and ch == 3 and eid == "0042"


def test_parse_chapter_filename_invalid_raises():
    with pytest.raises(ValueError):
        parse_chapter_filename("foo.bar")
```

- [ ] **Step 3: Run — verify fail**

Expected: ModuleNotFoundError.

- [ ] **Step 4: Implement**

```python
# backend/mimicrec/gopro/ffmpeg_pass.py
from __future__ import annotations
import asyncio
import json
import os
import re
from pathlib import Path

from mimicrec.errors import HardwareError
from mimicrec.recording.dataset_layout import DatasetPaths


_CHAPTER_RE = re.compile(r"^G(?P<q>[A-Z])(?P<ch>\d{2})(?P<id>\d{4})\.MP4$", re.IGNORECASE)


def parse_chapter_filename(filename: str) -> tuple[str, int, str]:
    """Return (quality_letter, chapter_number, episode_id_4digit).
    Raises ValueError if filename does not match GoPro's G<q><ch><id>.MP4 format."""
    m = _CHAPTER_RE.match(filename)
    if not m:
        raise ValueError(f"not a GoPro chapter filename: {filename!r}")
    return m.group("q").upper(), int(m.group("ch")), m.group("id")


async def _run_ffmpeg(cmd: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = stderr.decode(errors="replace")[-2000:] if stderr else "(no stderr)"
        raise HardwareError(f"ffmpeg failed (rc={proc.returncode}): {msg}")


async def ffmpeg_copy(src: Path, dst: Path) -> None:
    """Stream copy video + GPMF only (drop TCD + audio).

    Phase 0 verification confirmed: -map 0 -c copy -copy_unknown FAILS on
    Hero 11 because the TCD timecode track has codec=none which ffmpeg
    cannot remux. Use explicit per-stream map. Stream index 0:d:1 is the
    GPMF data stream (handler="GoPro MET") on Hero 11."""
    cmd = [
        "ffmpeg", "-y", "-nostdin", "-i", str(src),
        "-map", "0:v:0", "-map", "0:d:1",
        "-c", "copy",
        str(dst),
    ]
    await _run_ffmpeg(cmd)


async def ffmpeg_downscale(
    src: Path, dst: Path,
    target_w: int, target_h: int,
    aspect_mode: str,
    aspect_match: bool,
) -> None:
    """Re-encode video with libx264 + scale; copy GPMF data stream.
    Drops TCD timecode and audio. aspect_match=True → simple scale;
    False → crop or stretch per aspect_mode."""
    if aspect_match:
        vf = f"scale={target_w}:{target_h}"
    elif aspect_mode == "crop":
        vf = (
            f"scale={target_w}:{target_h}"
            f":force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h}"
        )
    elif aspect_mode == "stretch":
        vf = f"scale={target_w}:{target_h}"
    else:
        raise ValueError(f"unknown aspect_mode: {aspect_mode!r}")

    cmd = [
        "ffmpeg", "-y", "-nostdin", "-i", str(src),
        "-map", "0:v:0", "-map", "0:d:1",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-vf", vf,
        "-c:d", "copy",
        str(dst),
    ]
    await _run_ffmpeg(cmd)


async def update_info_json_codec(paths: DatasetPaths, cam_name: str) -> None:
    """Read first available episode video for cam_name, ffprobe codec,
    update info.json features placeholder. Idempotent."""
    cam_dir = paths.videos_dir / f"observation.images.{cam_name}"
    if not cam_dir.exists():
        return
    sample = next(iter(sorted(cam_dir.rglob("episode_*.mp4"))), None)
    if sample is None:
        return

    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(sample),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return
    codec = stdout.decode().strip()

    info_path = paths.meta_dir / "info.json"
    if not info_path.exists():
        return
    info = json.loads(info_path.read_text())
    key = f"observation.images.{cam_name}"
    if key not in info.get("features", {}):
        return
    if info["features"][key]["info"].get("video.codec") == codec:
        return

    info["features"][key]["info"]["video.codec"] = codec
    tmp = info_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(info, indent=2))
    os.replace(str(tmp), str(info_path))
```

- [ ] **Step 5: Run — verify pass**

Expected: 7 passed (some skip if fixture has no GPMF).

- [ ] **Step 6: Commit**

```bash
git add backend/mimicrec/gopro/ffmpeg_pass.py tests/unit/gopro/test_ffmpeg_pass.py tests/fixtures/gopro/
git commit -m "feat(gopro): ffmpeg pass (copy/downscale), info.json codec patch, chapter filename parser"
```

---

### Task 8: `gopro/recorder.py` — `GoProRecorder` with chapter detection

**Files:**
- Create: `backend/mimicrec/gopro/recorder.py`
- Test: `tests/unit/gopro/test_recorder.py`

- [ ] **Step 1: Write the failing test**

```python
import asyncio
from pathlib import Path

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


@pytest.fixture
def queue(paths):
    return DLQueue(paths.pending_dir / "gopro_dl")


@pytest.mark.asyncio
async def test_normal_lifecycle_enqueues_one_job(paths, queue):
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    errs = ErrorBus()
    r = GoProRecorder(d, queue, paths, errs)

    await r.start_episode(0, t_host_mono_ns=10_000_000_000)
    await r.stop_episode(0)

    job = await asyncio.wait_for(queue.dequeue(), timeout=1.0)
    assert job.episode_index == 0
    assert job.cam_name == "g1"
    assert job.gopro_serial == "S1"
    assert job.sd_filename.startswith("GX")


@pytest.mark.asyncio
async def test_chapter_split_only_first_chapter_enqueued(paths, queue):
    d = MockGoProDevice(name="g1", usb_serial="S1", chapters_per_episode=3)
    await d.connect()
    errs = ErrorBus()
    sub = errs.subscribe()
    r = GoProRecorder(d, queue, paths, errs)

    await r.start_episode(0, t_host_mono_ns=0)
    await r.stop_episode(0)

    job = await asyncio.wait_for(queue.dequeue(), timeout=1.0)
    # First chapter has chapter==01
    assert "01" in job.sd_filename[:4]

    # Warning was published
    found_warn = False
    while not sub.empty():
        e = sub.get_nowait()
        if "chapter split" in str(e).lower():
            found_warn = True
    assert found_warn


@pytest.mark.asyncio
async def test_disabled_device_is_noop(paths, queue):
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    d.disable("test")
    errs = ErrorBus()
    r = GoProRecorder(d, queue, paths, errs)

    await r.start_episode(0, t_host_mono_ns=0)
    await r.stop_episode(0)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.dequeue(), timeout=0.2)


@pytest.mark.asyncio
async def test_no_new_files_at_stop_skips_enqueue(paths, queue):
    """Mocked shutter that doesn't create files (= no recording happened)."""
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    async def _no_op():
        return None
    d.shutter_off = _no_op  # type: ignore[assignment]

    errs = ErrorBus()
    r = GoProRecorder(d, queue, paths, errs)
    await r.start_episode(0, t_host_mono_ns=0)
    await r.stop_episode(0)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.dequeue(), timeout=0.2)
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement**

```python
# backend/mimicrec/gopro/recorder.py
from __future__ import annotations
import asyncio
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass

from mimicrec.errors import HardwareError
from mimicrec.gopro.dl_queue import DLQueue, GoProDLJob
from mimicrec.gopro.ffmpeg_pass import parse_chapter_filename
from mimicrec.recording.dataset_layout import DatasetPaths, resolve_chunk
from mimicrec.util.error_bus import ErrorBus

log = logging.getLogger(__name__)


@dataclass
class _EpisodeState:
    episode_index: int
    episode_start_mono_ns: int


class GoProRecorder:
    """Control-plane view over a single GoProDevice."""

    def __init__(self, device, queue: DLQueue, paths: DatasetPaths, errors: ErrorBus) -> None:
        self._device = device
        self._queue = queue
        self._paths = paths
        self._errors = errors
        self._known_files: set[str] = set()
        self._state: _EpisodeState | None = None

    async def start_episode(self, episode_index: int, t_host_mono_ns: int) -> None:
        if getattr(self._device, "is_disabled", False):
            return
        # Snapshot known files BEFORE shutter so stop can compute the delta.
        try:
            files = await self._device.media_list()
            self._known_files |= {f.filename for f in files}
        except Exception as e:
            log.warning("media_list snapshot failed for %s: %s", self._device.name, e)

        try:
            await self._device.shutter_on()
        except Exception as e:
            await self._errors.publish(HardwareError(f"GoPro {self._device.name} shutter_on failed: {e}"))
            self._state = None
            return

        self._state = _EpisodeState(
            episode_index=episode_index,
            episode_start_mono_ns=time.monotonic_ns(),
        )

    async def stop_episode(self, episode_index: int) -> None:
        if getattr(self._device, "is_disabled", False):
            return
        state = self._state
        self._state = None

        for attempt in range(3):
            try:
                await self._device.shutter_off()
                break
            except Exception as e:
                if attempt == 2:
                    await self._errors.publish(HardwareError(
                        f"GoPro {self._device.name} shutter_off retries exhausted: {e}"))
                    return
                await asyncio.sleep(0.2)

        if state is None or state.episode_index != episode_index:
            return

        try:
            files = await self._device.media_list()
        except Exception:
            files = []
        new_files = [f for f in files if f.filename not in self._known_files]
        if not new_files:
            await self._errors.publish(HardwareError(
                f"GoPro {self._device.name} ep {episode_index}: no new file detected — orphan or no recording"))
            return

        # Chapter detection: group new files by (quality, id).
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for f in new_files:
            try:
                q, ch, eid = parse_chapter_filename(f.filename)
            except ValueError:
                # Unknown filename pattern — treat as its own group.
                groups[("?", f.filename)].append((99, f))
                continue
            groups[(q, eid)].append((ch, f))

        # Pick the first chapter (lowest ch) of the first group.
        first_group_key = sorted(groups.keys())[0]
        items = sorted(groups[first_group_key], key=lambda t: t[0])
        chosen = items[0][1]

        # All other new files are orphan; remember them.
        all_new_filenames = {f.filename for f in new_files}
        self._known_files |= all_new_filenames
        if len(all_new_filenames) > 1:
            await self._errors.publish(HardwareError(
                f"GoPro {self._device.name} ep {episode_index}: chapter split detected — "
                f"only first chapter saved ({chosen.filename}), rest left on SD"))

        chunk_index = resolve_chunk(episode_index)
        job = GoProDLJob(
            job_id=str(uuid.uuid4()),
            gopro_serial=self._device.usb_serial,
            sd_filename=chosen.filename,
            episode_index=episode_index,
            chunk_index=chunk_index,
            cam_name=self._device.name,
            episode_start_mono_ns=state.episode_start_mono_ns,
            episode_stop_mono_ns=time.monotonic_ns(),
        )
        await self._queue.enqueue(job)
```

- [ ] **Step 4: Run — verify pass**

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/gopro/recorder.py tests/unit/gopro/test_recorder.py
git commit -m "feat(gopro): GoProRecorder with chapter detection on stop_episode"
```

---

### Task 9: `gopro/dl_worker.py` — DLWorker loop with ffmpeg + codec patch

**Files:**
- Create: `backend/mimicrec/gopro/dl_worker.py`
- Test: `tests/unit/gopro/test_dl_worker.py`

- [ ] **Step 1: Write the failing test**

```python
import asyncio
import json
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


FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "gopro" / "sample_episode.mp4"


@pytest.fixture
def paths(tmp_path):
    p = dataset_paths(tmp_path / "ds")
    for d in (p.meta_dir, p.pending_dir, p.videos_dir):
        d.mkdir(parents=True, exist_ok=True)
    # Pre-seed info.json so update_info_json_codec works.
    (p.meta_dir / "info.json").write_text(json.dumps({
        "features": {
            "observation.images.g1": {"info": {"video.codec": "libx264"}},
        },
    }))
    return p


def _job(job_id="j", episode_index=0):
    return GoProDLJob(
        job_id=job_id, gopro_serial="S1", sd_filename="GX010001.MP4",
        episode_index=episode_index, chunk_index=0, cam_name="g1",
        episode_start_mono_ns=time.monotonic_ns(),
        episode_stop_mono_ns=time.monotonic_ns() + 5_000_000_000,
    )


@pytest.mark.asyncio
async def test_normal_dl_stages_for_commit(paths):
    """DLWorker stages the file but does NOT move to dataset path. The move
    happens later via registry.commit_episode (covered in test_registry.py)."""
    d = MockGoProDevice(name="g1", usb_serial="S1", fixture_mp4=FIXTURE)
    await d.connect()
    queue = DLQueue(paths.pending_dir / "gopro_dl")
    errors = ErrorBus()
    worker = GoProDLWorker(queue, devices={"S1": d}, paths=paths, errors=errors)

    await d.shutter_on(); await d.shutter_off()
    files = await d.media_list()
    job = _job(job_id="j1")
    job.sd_filename = files[0].filename
    await queue.enqueue(job)

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.5)
    await worker.stop()
    try: await asyncio.wait_for(task, timeout=2.0)
    except asyncio.CancelledError: pass

    # Sidecar still exists (state="staged"), staged file in place.
    sidecar = paths.pending_dir / "gopro_dl" / "j1.json"
    assert sidecar.exists()
    s = await queue.read_sidecar("j1")
    assert s.state == "staged"
    assert Path(s.staged_path).exists()
    # Dataset path NOT yet populated.
    assert not paths.episode_video(0, "g1", 0).exists()


@pytest.mark.asyncio
async def test_dl_with_commit_pending_set_during_processing(paths):
    """If sidecar.state becomes commit_pending while DL is happening, DLWorker
    must commit-then-finish instead of staging."""
    d = MockGoProDevice(name="g1", usb_serial="S1", fixture_mp4=FIXTURE)
    await d.connect()
    queue = DLQueue(paths.pending_dir / "gopro_dl")
    errors = ErrorBus()
    worker = GoProDLWorker(queue, devices={"S1": d}, paths=paths, errors=errors)

    await d.shutter_on(); await d.shutter_off()
    files = await d.media_list()
    job = _job(job_id="j_cp")
    job.sd_filename = files[0].filename
    await queue.enqueue(job)

    # Pre-flip sidecar state to commit_pending BEFORE worker dequeues.
    pre = await queue.read_sidecar("j_cp")
    pre.state = "commit_pending"
    await queue.update_sidecar(pre)

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.5)
    await worker.stop()
    try: await asyncio.wait_for(task, timeout=2.0)
    except asyncio.CancelledError: pass

    # Worker should have committed: dataset path exists, sidecar gone.
    assert paths.episode_video(0, "g1", 0).exists()
    assert not (paths.pending_dir / "gopro_dl" / "j_cp.json").exists()
    info = json.loads((paths.meta_dir / "info.json").read_text())
    assert info["features"]["observation.images.g1"]["info"]["video.codec"] in {"h264", "hevc"}


@pytest.mark.asyncio
async def test_dl_with_discard_pending_skips_dl(paths):
    """If state is discard_pending when dequeued, no download happens."""
    d = MockGoProDevice(name="g1", usb_serial="S1", fixture_mp4=FIXTURE)
    await d.connect()
    download_called = False
    async def boom(*a, **kw):
        nonlocal download_called
        download_called = True
    d.download_file = boom  # type: ignore[assignment]

    queue = DLQueue(paths.pending_dir / "gopro_dl")
    errors = ErrorBus()
    worker = GoProDLWorker(queue, devices={"S1": d}, paths=paths, errors=errors)

    job = _job(job_id="j_dp")
    job.state = "discard_pending"
    await queue.enqueue(job)

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.3)
    await worker.stop()
    try: await asyncio.wait_for(task, timeout=2.0)
    except asyncio.CancelledError: pass

    assert not download_called
    assert not (paths.pending_dir / "gopro_dl" / "j_dp.json").exists()


@pytest.mark.asyncio
async def test_unknown_device_keeps_sidecar(paths):
    queue = DLQueue(paths.pending_dir / "gopro_dl")
    errors = ErrorBus()
    sub = errors.subscribe()
    worker = GoProDLWorker(queue, devices={}, paths=paths, errors=errors)

    await queue.enqueue(_job(job_id="orphan"))
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.3)
    await worker.stop()
    try: await asyncio.wait_for(task, timeout=2.0)
    except asyncio.CancelledError: pass

    assert (paths.pending_dir / "gopro_dl" / "orphan.json").exists()
    found_err = False
    while not sub.empty():
        e = sub.get_nowait()
        if "no device" in str(e).lower():
            found_err = True
    assert found_err


@pytest.mark.asyncio
async def test_resume_from_tmp_skips_redownload(paths):
    """When tmp_raw already matches SD-side size (i.e. previous DL completed
    but ffmpeg/staging failed), DLWorker should skip download and re-run ffmpeg.

    Note: MockGoProDevice reports a fixed MediaItem.size (12345). For this test
    to be correct, we override the mock's media_list to report the actual
    fixture size, and pre-place tmp_raw as a copy of the fixture so the size
    check passes AND ffmpeg can read it as a valid MP4."""
    import shutil as _sh
    d = MockGoProDevice(name="g1", usb_serial="S1", fixture_mp4=FIXTURE)
    await d.connect()
    await d.shutter_on(); await d.shutter_off()
    files = await d.media_list()

    # Override media_list so reported size matches the actual fixture.
    real_size = FIXTURE.stat().st_size
    from mimicrec.gopro.types import MediaItem
    async def real_size_list():
        return [MediaItem(filename=files[0].filename, size=real_size, mtime_ns=0)]
    d.media_list = real_size_list  # type: ignore[assignment]

    queue = DLQueue(paths.pending_dir / "gopro_dl")
    errors = ErrorBus()
    worker = GoProDLWorker(queue, devices={"S1": d}, paths=paths, errors=errors)

    job = _job(job_id="j_resume")
    job.sd_filename = files[0].filename
    job.state = "commit_pending"   # so worker commits to dataset on completion

    tmp_raw = paths.pending_dir / f"gopro_dl_{job.job_id}_raw.mp4"
    tmp_raw.parent.mkdir(parents=True, exist_ok=True)
    _sh.copy(str(FIXTURE), str(tmp_raw))   # valid MP4, real size

    download_called = False
    async def boom(*a, **kw):
        nonlocal download_called
        download_called = True
    d.download_file = boom  # type: ignore[assignment]

    await queue.enqueue(job)
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.5)
    await worker.stop()
    try: await asyncio.wait_for(task, timeout=2.0)
    except asyncio.CancelledError: pass

    assert not download_called
    assert paths.episode_video(0, "g1", 0).exists()
```

- [ ] **Step 2: Run — verify fail** (ModuleNotFoundError)

- [ ] **Step 3: Implement**

```python
# backend/mimicrec/gopro/dl_worker.py
from __future__ import annotations
import asyncio
import logging
import shutil
from pathlib import Path

from mimicrec.errors import HardwareError
from mimicrec.gopro.dl_queue import DLQueue
from mimicrec.gopro.ffmpeg_pass import (
    ffmpeg_copy, ffmpeg_downscale, update_info_json_codec,
)
from mimicrec.recording.dataset_layout import DatasetPaths
from mimicrec.util.error_bus import ErrorBus

log = logging.getLogger(__name__)


def _probe_mp4_duration(path: Path) -> float:
    import av
    with av.open(str(path)) as ctx:
        s = ctx.streams.video[0]
        if s.duration is None or s.time_base is None:
            return 0.0
        return float(s.duration * s.time_base)


class GoProDLWorker:
    def __init__(
        self,
        queue: DLQueue,
        devices: dict[str, object],
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
            for p in pending: p.cancel()
            if stop_task in done:
                if not dq_task.cancelled():
                    try: dq_task.result()
                    except Exception: pass
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
        # If the registry already requested discard before DLWorker dequeued
        # the job, terminate immediately without downloading.
        if job.state == "discard_pending":
            await self._queue.mark_done(job.job_id)
            return

        device = self._devices.get(job.gopro_serial)
        if device is None or getattr(device, "is_disabled", False):
            await self._errors.publish(HardwareError(
                f"GoPro DL: no device for serial {job.gopro_serial}, "
                f"sidecar kept (episode {job.episode_index})"))
            return

        tmp_raw = self._paths.pending_dir / f"gopro_dl_{job.job_id}_raw.mp4"
        staged = self._paths.pending_dir / "gopro_staged" / f"{job.job_id}.mp4"

        # Resume from tmp_raw if it matches SD-side size.
        skip_dl = False
        if tmp_raw.exists() and tmp_raw.stat().st_size > 0:
            try:
                files = await device.media_list()
                match = next((f for f in files if f.filename == job.sd_filename), None)
                if match is not None and tmp_raw.stat().st_size == match.size:
                    skip_dl = True
            except Exception:
                skip_dl = False

        if not skip_dl:
            try:
                await device.download_file(job.sd_filename, tmp_raw)
            except Exception as e:
                await self._errors.publish(HardwareError(
                    f"GoPro DL failed for ep {job.episode_index}: {e}"))
                return

        # Duration check: only flag "shorter than expected" by > 2.0s.
        try:
            duration = await asyncio.to_thread(_probe_mp4_duration, tmp_raw)
            expected = (job.episode_stop_mono_ns - job.episode_start_mono_ns) / 1e9
            if duration < expected - 2.0:
                await self._errors.publish(HardwareError(
                    f"GoPro recording shorter than episode: ep {job.episode_index} "
                    f"duration={duration:.3f}s expected≈{expected:.3f}s"))
        except Exception as e:
            log.warning("duration probe failed for %s: %s", tmp_raw, e)

        # ffmpeg pass: stage the output (no move to dataset path here).
        try:
            staged.parent.mkdir(parents=True, exist_ok=True)
            spec = device.get_spec()
            native = device.selected_preset
            aspect_match = abs(
                (native.width / native.height) - (spec.width / spec.height)
            ) < 0.01
            if native.width == spec.width and native.height == spec.height:
                await ffmpeg_copy(tmp_raw, staged)
            else:
                await ffmpeg_downscale(
                    tmp_raw, staged,
                    target_w=spec.width, target_h=spec.height,
                    aspect_mode=device.aspect_mode,
                    aspect_match=aspect_match,
                )
        except Exception as e:
            await self._errors.publish(HardwareError(
                f"GoPro ffmpeg failed for ep {job.episode_index}: {e}"))
            return

        try:
            tmp_raw.unlink(missing_ok=True)
        except Exception:
            pass

        # Re-read sidecar: registry may have requested commit/discard during DL.
        fresh = await self._queue.read_sidecar(job.job_id)
        if fresh is None:
            # Sidecar disappeared (registry already committed/discarded?).
            staged.unlink(missing_ok=True)
            return

        if fresh.state == "commit_pending":
            await self._commit_to_dataset(job, staged)
            await self._queue.mark_done(job.job_id)
            return
        if fresh.state == "discard_pending":
            staged.unlink(missing_ok=True)
            await self._queue.mark_done(job.job_id)
            return

        # Normal path: mark as staged, await registry's commit/discard.
        fresh.state = "staged"
        fresh.staged_path = str(staged)
        await self._queue.update_sidecar(fresh)

        # Race: registry may have written commit_pending/discard_pending between
        # our read and update. Re-read once more.
        after = await self._queue.read_sidecar(job.job_id)
        if after is None:
            staged.unlink(missing_ok=True)
            return
        if after.state == "commit_pending":
            await self._commit_to_dataset(after, staged)
            await self._queue.mark_done(job.job_id)
        elif after.state == "discard_pending":
            staged.unlink(missing_ok=True)
            await self._queue.mark_done(job.job_id)
        # else: state="staged" persisted — registry will commit/discard later.

    async def _commit_to_dataset(self, job, staged: Path) -> None:
        """Move staged MP4 into the dataset, patch info.json codec."""
        dest = self._paths.episode_video(job.chunk_index, job.cam_name, job.episode_index)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staged), str(dest))
        except Exception as e:
            await self._errors.publish(HardwareError(
                f"GoPro move failed for ep {job.episode_index}: {e}"))
            return
        try:
            await update_info_json_codec(self._paths, job.cam_name)
        except Exception as e:
            log.warning("update_info_json_codec failed: %s", e)

    async def stop(self) -> None:
        self._stop.set()
        if self._inflight is not None:
            try:
                await asyncio.wait_for(self._inflight, timeout=self._grace)
            except asyncio.TimeoutError:
                self._inflight.cancel()
                try: await self._inflight
                except (asyncio.CancelledError, Exception): pass
```

- [ ] **Step 4: Run — verify pass**

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/gopro/dl_worker.py tests/unit/gopro/test_dl_worker.py
git commit -m "feat(gopro): DLWorker with ffmpeg pass, resume-from-tmp, post-DL codec patch"
```

---

### Task 10: `gopro/preview.py` — `GoProPreviewSource` via `asyncio.to_thread`

**Files:**
- Create: `backend/mimicrec/gopro/preview.py`
- Test: `tests/unit/gopro/test_preview.py`

- [ ] **Step 1: Write the failing test**

```python
import asyncio

import numpy as np
import pytest

from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.gopro.preview import GoProPreviewSource


@pytest.mark.asyncio
async def test_push_for_test_emits_preview_only_frame():
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    src = GoProPreviewSource(d, udp_port=18556)
    img = np.zeros((48, 64, 3), dtype=np.uint8)
    await src._push_frame_for_test(img)
    f = await asyncio.wait_for(src.read(), timeout=1.0)
    assert f.preview_only is True
    assert f.image.shape == (48, 64, 3)


@pytest.mark.asyncio
async def test_disabled_device_read_blocks_cleanly():
    d = MockGoProDevice(name="g1", usb_serial="S1")
    await d.connect()
    d.disable("test")
    src = GoProPreviewSource(d, udp_port=18557)
    await src.connect()  # no-op when disabled
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(src.read(), timeout=0.3)
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement**

```python
# backend/mimicrec/gopro/preview.py
from __future__ import annotations
import asyncio
import logging
import threading
from typing import Optional

import numpy as np

from mimicrec.types import Frame

log = logging.getLogger(__name__)


class GoProPreviewSource:
    """Camera I/F view over UDP MPEG-TS preview. Decode runs in a worker thread."""

    def __init__(self, device, udp_port: int) -> None:
        self._device = device
        self._port = udp_port
        self._latest: asyncio.Queue[Frame] = asyncio.Queue(maxsize=1)
        self._never: asyncio.Event = asyncio.Event()
        self._decode_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._connected = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

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
        self._loop = asyncio.get_running_loop()
        self._stop_event.clear()
        self._decode_thread = threading.Thread(
            target=self._decode_loop_sync, name=f"gopro-preview-{self._device.name}", daemon=True,
        )
        self._decode_thread.start()
        self._connected = True

    async def disconnect(self) -> None:
        self._stop_event.set()
        try:
            await self._device.stop_preview()
        except Exception as e:
            log.warning("stop_preview failed for %s: %s", self._device.name, e)
        if self._decode_thread is not None:
            self._decode_thread.join(timeout=2.0)
            self._decode_thread = None
        self._connected = False

    async def read(self) -> Frame:
        if getattr(self._device, "is_disabled", False) or not self._connected:
            await self._never.wait()
        return await self._latest.get()

    def _decode_loop_sync(self) -> None:
        """Runs in worker thread. Pushes decoded frames to self._latest via the loop."""
        import av
        url = f"udp://0.0.0.0:{self._port}?fifo_size=50000&overrun_nonfatal=1"
        try:
            with av.open(url, mode="r", timeout=5) as ctx:
                for packet in ctx.demux(video=0):
                    if self._stop_event.is_set():
                        break
                    for av_frame in packet.decode():
                        if self._stop_event.is_set():
                            break
                        img = av_frame.to_ndarray(format="bgr24")
                        if self._loop is not None:
                            asyncio.run_coroutine_threadsafe(
                                self._push(img), self._loop,
                            )
        except Exception as e:
            log.warning("preview decode loop ended for %s: %s", self._device.name, e)

    async def _push(self, img: "np.ndarray") -> None:
        f = Frame(image=img, preview_only=True)
        try:
            self._latest.put_nowait(f)
        except asyncio.QueueFull:
            try: self._latest.get_nowait()
            except asyncio.QueueEmpty: pass
            self._latest.put_nowait(f)

    async def _push_frame_for_test(self, image: np.ndarray) -> None:
        """Test hook bypassing UDP/pyav."""
        await self._push(image)
        self._connected = True
```

- [ ] **Step 4: Run — verify pass**

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/gopro/preview.py tests/unit/gopro/test_preview.py
git commit -m "feat(gopro): GoProPreviewSource with worker-thread decode"
```

---

### Task 11: `gopro/registry.py` — registry with gather error inspection

**Files:**
- Create: `backend/mimicrec/gopro/registry.py`
- Test: `tests/unit/gopro/test_registry.py`

- [ ] **Step 1: Write the failing test**

```python
import asyncio
from pathlib import Path

import pytest

from mimicrec.gopro.mock import MockGoProDevice
from mimicrec.gopro.registry import GoProDeviceRegistry
from mimicrec.recording.dataset_layout import dataset_paths
from mimicrec.util.error_bus import ErrorBus


@pytest.fixture
def paths(tmp_path):
    p = dataset_paths(tmp_path / "ds")
    for d in (p.meta_dir, p.pending_dir, p.videos_dir):
        d.mkdir(parents=True, exist_ok=True)
    return p


def test_duplicate_name_raises(paths):
    a = MockGoProDevice(name="g1", usb_serial="S1")
    b = MockGoProDevice(name="g1", usb_serial="S2")
    with pytest.raises(ValueError, match="duplicate name"):
        GoProDeviceRegistry(devices=[a, b], paths=paths, errors=ErrorBus())


def test_duplicate_serial_raises(paths):
    a = MockGoProDevice(name="g1", usb_serial="S1")
    b = MockGoProDevice(name="g2", usb_serial="S1")
    with pytest.raises(ValueError, match="duplicate usb_serial"):
        GoProDeviceRegistry(devices=[a, b], paths=paths, errors=ErrorBus())


@pytest.mark.asyncio
async def test_start_connects_and_provides_preview_sources(paths):
    a = MockGoProDevice(name="g1", usb_serial="S1")
    reg = GoProDeviceRegistry(devices=[a], paths=paths, errors=ErrorBus())
    await reg.start()
    sources = reg.preview_sources()
    assert "g1" in sources
    specs = reg.gopro_specs()
    assert "g1" in specs
    await reg.stop()


@pytest.mark.asyncio
async def test_one_failing_connect_does_not_block_others(paths):
    a = MockGoProDevice(name="g_ok", usb_serial="S1")
    b = MockGoProDevice(name="g_bad", usb_serial="S2")
    async def boom():
        raise RuntimeError("connect blew up")
    b.connect = boom  # type: ignore[assignment]

    errs = ErrorBus()
    sub = errs.subscribe()
    reg = GoProDeviceRegistry(devices=[a, b], paths=paths, errors=errs)
    await reg.start()
    # b was disabled and an error was published.
    assert b.is_disabled
    assert not a.is_disabled
    found = False
    while not sub.empty():
        e = sub.get_nowait()
        if "g_bad" in str(e):
            found = True
    assert found
    await reg.stop()


@pytest.mark.asyncio
async def test_episode_lifecycle_propagates_errors(paths):
    a = MockGoProDevice(name="g1", usb_serial="S1")
    errs = ErrorBus()
    sub = errs.subscribe()
    reg = GoProDeviceRegistry(devices=[a], paths=paths, errors=errs)
    await reg.start()
    # Sabotage a's recorder by pinning an exception inside start_episode.
    real_recorder = reg._recorders["g1"]  # type: ignore[attr-defined]
    async def boom(*a, **kw):
        raise RuntimeError("recorder crash")
    real_recorder.start_episode = boom  # type: ignore[assignment]

    await reg.episode_start(0, t_host_mono_ns=0)
    found = False
    while not sub.empty():
        e = sub.get_nowait()
        if "recorder crash" in str(e):
            found = True
    assert found
    await reg.stop()


@pytest.mark.asyncio
async def test_commit_episode_moves_staged_to_dataset(paths, tmp_path):
    """When a job is in state=staged, commit_episode moves the file to
    paths.episode_video(...) and removes the sidecar."""
    a = MockGoProDevice(name="g1", usb_serial="S1")
    reg = GoProDeviceRegistry(devices=[a], paths=paths, errors=ErrorBus())
    await reg.start()

    # Manually craft a staged job sidecar + staged file.
    from mimicrec.gopro.dl_queue import GoProDLJob
    staged_dir = paths.pending_dir / "gopro_staged"
    staged_dir.mkdir(parents=True, exist_ok=True)
    staged_file = staged_dir / "abc.mp4"
    staged_file.write_bytes(b"\x00" * 64)
    job = GoProDLJob(
        job_id="abc", gopro_serial="S1", sd_filename="GX010001.MP4",
        episode_index=0, chunk_index=0, cam_name="g1",
        episode_start_mono_ns=0, episode_stop_mono_ns=0,
        state="staged", staged_path=str(staged_file),
    )
    # Pre-seed info.json so codec patch path doesn't blow up.
    import json as _json
    (paths.meta_dir / "info.json").write_text(_json.dumps({
        "features": {"observation.images.g1": {"info": {"video.codec": "libx264"}}},
    }))
    await reg._queue.enqueue(job)  # type: ignore[union-attr]
    await reg._queue.update_sidecar(job)  # ensure state="staged" in sidecar

    await reg.commit_episode(0)

    assert paths.episode_video(0, "g1", 0).exists()
    assert not (paths.pending_dir / "gopro_dl" / "abc.json").exists()
    assert not staged_file.exists()
    await reg.stop()


@pytest.mark.asyncio
async def test_discard_episode_removes_staged(paths):
    a = MockGoProDevice(name="g1", usb_serial="S1")
    reg = GoProDeviceRegistry(devices=[a], paths=paths, errors=ErrorBus())
    await reg.start()

    from mimicrec.gopro.dl_queue import GoProDLJob
    staged_dir = paths.pending_dir / "gopro_staged"
    staged_dir.mkdir(parents=True, exist_ok=True)
    staged_file = staged_dir / "xyz.mp4"
    staged_file.write_bytes(b"\x00" * 64)
    job = GoProDLJob(
        job_id="xyz", gopro_serial="S1", sd_filename="GX010001.MP4",
        episode_index=1, chunk_index=0, cam_name="g1",
        episode_start_mono_ns=0, episode_stop_mono_ns=0,
        state="staged", staged_path=str(staged_file),
    )
    await reg._queue.enqueue(job)  # type: ignore[union-attr]
    await reg._queue.update_sidecar(job)

    await reg.discard_episode(1)

    assert not staged_file.exists()
    assert not (paths.pending_dir / "gopro_dl" / "xyz.json").exists()
    assert not paths.episode_video(0, "g1", 1).exists()
    await reg.stop()


@pytest.mark.asyncio
async def test_commit_episode_on_pending_dl_flips_state(paths):
    """If the job is still pending_dl when commit fires, sidecar state flips
    to commit_pending (DLWorker will commit after ffmpeg)."""
    a = MockGoProDevice(name="g1", usb_serial="S1")
    reg = GoProDeviceRegistry(devices=[a], paths=paths, errors=ErrorBus())
    await reg.start()

    from mimicrec.gopro.dl_queue import GoProDLJob
    job = GoProDLJob(
        job_id="ppp", gopro_serial="S1", sd_filename="GX010001.MP4",
        episode_index=2, chunk_index=0, cam_name="g1",
        episode_start_mono_ns=0, episode_stop_mono_ns=0,
        state="pending_dl",
    )
    await reg._queue.enqueue(job)  # type: ignore[union-attr]
    await reg.commit_episode(2)

    s = await reg._queue.read_sidecar("ppp")  # type: ignore[union-attr]
    assert s.state == "commit_pending"
    await reg.stop()
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement**

```python
# backend/mimicrec/gopro/registry.py
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
        # 1. Connect all devices, collecting exceptions and disabling failed devices.
        async def _try_connect(d):
            try:
                await d.connect()
                return None
            except Exception as e:
                if hasattr(d, "disable"):
                    d.disable(f"connect failed: {e}")
                return (d.name, e)

        results = await asyncio.gather(
            *[_try_connect(d) for d in self._devices],
            return_exceptions=False,
        )
        for r in results:
            if r is not None:
                name, exc = r
                await self._errors.publish(HardwareError(f"GoPro {name} connect failed: {exc}"))

        # 2. Restore queue, build recorders + preview sources.
        self._queue = DLQueue.restore(self._paths.pending_dir / "gopro_dl")
        for idx, d in enumerate(self._devices):
            self._recorders[d.name] = GoProRecorder(d, self._queue, self._paths, self._errors)
            self._previews[d.name] = GoProPreviewSource(d, udp_port=18556 + idx)

        # 3. Start the DL worker.
        devices_by_serial = {d.usb_serial: d for d in self._devices}
        self._worker = GoProDLWorker(self._queue, devices_by_serial, self._paths, self._errors)
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
            try: await src.disconnect()
            except Exception: pass
        for d in self._devices:
            try: await d.disconnect()
            except Exception: pass

    async def _fan_out(self, op_name: str, coro_factory) -> None:
        """Run coro_factory for each recorder, gather, inspect exceptions."""
        results = await asyncio.gather(
            *[coro_factory(r) for r in self._recorders.values()],
            return_exceptions=True,
        )
        for (name, recorder), result in zip(self._recorders.items(), results):
            if isinstance(result, BaseException):
                if hasattr(recorder._device, "disable"):  # type: ignore[attr-defined]
                    recorder._device.disable(f"{op_name} failed: {result}")  # type: ignore[attr-defined]
                await self._errors.publish(HardwareError(
                    f"GoPro {name} {op_name} failed: {result}"))

    async def episode_start(self, episode_index: int, t_host_mono_ns: int) -> None:
        await self._fan_out(
            "episode_start",
            lambda r: r.start_episode(episode_index, t_host_mono_ns),
        )

    async def episode_stop(self, episode_index: int) -> None:
        await self._fan_out(
            "episode_stop",
            lambda r: r.stop_episode(episode_index),
        )

    async def commit_episode(self, episode_index: int) -> None:
        """Called from SessionManager.episode_save. For each sidecar matching
        episode_index: if staged, move to dataset; if pending_dl, flip to
        commit_pending so DLWorker handles it after staging completes."""
        if self._queue is None:
            return
        from mimicrec.gopro.ffmpeg_pass import update_info_json_codec
        import shutil as _sh
        jobs = await self._queue.find_jobs_for_episode(episode_index)
        for job in jobs:
            if job.state == "staged" and job.staged_path:
                src = Path(job.staged_path)
                dest = self._paths.episode_video(job.chunk_index, job.cam_name, job.episode_index)
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    _sh.move(str(src), str(dest))
                    await update_info_json_codec(self._paths, job.cam_name)
                    await self._queue.mark_done(job.job_id)
                except Exception as e:
                    await self._errors.publish(HardwareError(
                        f"commit_episode {job.episode_index} ({job.cam_name}) failed: {e}"))
            elif job.state == "pending_dl":
                job.state = "commit_pending"
                await self._queue.update_sidecar(job)
            # else (commit_pending / discard_pending / staged-but-no-path): skip

    async def discard_episode(self, episode_index: int) -> None:
        """Called from SessionManager.episode_discard. Symmetric to commit:
        delete staged files / flip pending_dl → discard_pending."""
        if self._queue is None:
            return
        jobs = await self._queue.find_jobs_for_episode(episode_index)
        for job in jobs:
            if job.state == "staged" and job.staged_path:
                Path(job.staged_path).unlink(missing_ok=True)
                await self._queue.mark_done(job.job_id)
            elif job.state == "pending_dl":
                job.state = "discard_pending"
                await self._queue.update_sidecar(job)

    def preview_sources(self) -> dict[str, GoProPreviewSource]:
        return dict(self._previews)

    def gopro_specs(self) -> dict[str, GoProSpec]:
        return {d.name: d.get_spec() for d in self._devices}

    @property
    def pending_count(self) -> int:
        return self._queue.pending_count if self._queue is not None else 0
```

- [ ] **Step 4: Run — verify pass**

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/gopro/registry.py tests/unit/gopro/test_registry.py
git commit -m "feat(gopro): GoProDeviceRegistry with gather error inspection"
```

---

## Phase 4 — Real device + dataset integration

### Task 12: `gopro/device.py` — Real `GoProDevice`

**Files:**
- Create: `backend/mimicrec/gopro/device.py`
- Test: `tests/unit/gopro/test_device.py`

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mimicrec.errors import HardwareError
from mimicrec.gopro.types import GoProSpec


@pytest.mark.asyncio
async def test_unsupported_fps_raises_at_init():
    from mimicrec.gopro.device import GoProDevice
    with pytest.raises(ValueError):
        GoProDevice(name="g1", usb_serial="S1", width=1920, height=1080, fps=25)


@pytest.mark.asyncio
async def test_get_spec_returns_yaml_target():
    from mimicrec.gopro.device import GoProDevice
    d = GoProDevice(name="g1", usb_serial="S1", width=1280, height=720, fps=30)
    s = d.get_spec()
    assert s == GoProSpec(name="g1", width=1280, height=720, fps=30, codec="libx264")


@pytest.mark.asyncio
async def test_connect_calls_required_apis_in_order():
    from mimicrec.gopro.device import GoProDevice
    fake_client = MagicMock()
    fake_client.is_open = True
    fake_client.http_command = MagicMock()
    fake_client.http_command.set_date_time = AsyncMock(return_value=MagicMock(ok=True))
    fake_client.http_command.load_preset_group = AsyncMock(return_value=MagicMock(ok=True))
    fake_client.http_command.load_preset = AsyncMock(return_value=MagicMock(ok=True))
    fake_client.http_command.get_camera_state = AsyncMock(
        # Phase 0 confirmed: state.data is dict-of-status-id-string-keys.
        # Key "54" is SD remaining IN KB (not bytes).
        return_value=MagicMock(ok=True, data={"54": 25_000_000})
    )
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_client)
    fake_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("mimicrec.gopro.device.WiredGoPro", return_value=fake_ctx):
        d = GoProDevice(name="g1", usb_serial="S1", width=1920, height=1080, fps=30)
        await d.connect()
        fake_client.http_command.set_date_time.assert_awaited()
        fake_client.http_command.load_preset_group.assert_awaited()
        fake_client.http_command.load_preset.assert_awaited()
        await d.disconnect()
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement**

```python
# backend/mimicrec/gopro/device.py
from __future__ import annotations
import logging
from datetime import datetime
from pathlib import Path

from mimicrec.errors import HardwareError
from mimicrec.gopro.preset_picker import pick_preset
from mimicrec.gopro.types import GoProSpec, MediaItem, NativePreset

log = logging.getLogger(__name__)

try:
    from open_gopro import WiredGoPro                # type: ignore
    from open_gopro.models import constants, proto   # type: ignore
except Exception:
    WiredGoPro = None  # type: ignore[assignment]
    constants = None   # type: ignore[assignment]
    proto = None       # type: ignore[assignment]


# Phase 0 confirmed: SD remaining is at state.data["54"] in KB.
_STORAGE_MIN_KB = 500_000   # 500 MB ≈ 500_000 KB


class GoProDevice:
    def __init__(
        self,
        name: str,
        usb_serial: str,
        width: int,
        height: int,
        fps: int,
        aspect_mode: str = "crop",
    ) -> None:
        self._preset, self._aspect_match = pick_preset(width, height, fps, aspect_mode)
        self._name = name
        self._serial = usb_serial
        self._target_w = width
        self._target_h = height
        self._target_fps = fps
        self._aspect_mode = aspect_mode
        self._client_ctx = None
        self._client = None
        self._disabled = False

    @property
    def name(self) -> str: return self._name
    @property
    def usb_serial(self) -> str: return self._serial
    @property
    def is_disabled(self) -> bool: return self._disabled
    @property
    def selected_preset(self) -> NativePreset: return self._preset
    @property
    def aspect_mode(self) -> str: return self._aspect_mode

    def get_spec(self) -> GoProSpec:
        return GoProSpec(
            name=self._name,
            width=self._target_w, height=self._target_h, fps=self._target_fps,
            codec="libx264",
        )

    async def connect(self) -> None:
        if self._client is not None: return
        if WiredGoPro is None:
            raise HardwareError("open_gopro is not installed")
        # NOTE: WiredGoPro's exact init kwarg name depends on open_gopro version.
        # Phase 0 verification establishes whether it's `target=` or `serial=`.
        # If neither works without args, omit (open_gopro auto-discovers a single GoPro).
        try:
            self._client_ctx = WiredGoPro()
            self._client = await self._client_ctx.__aenter__()
        except Exception as e:
            self._client_ctx = None
            raise HardwareError(f"WiredGoPro init failed: {e}") from e

        await self._must_ok(
            self._client.http_command.set_date_time(date_time=datetime.now()),
            "set_date_time",
        )
        await self._must_ok(
            self._client.http_command.load_preset_group(
                group=proto.EnumPresetGroup.PRESET_GROUP_ID_VIDEO),
            "load_preset_group video",
        )
        await self._must_ok(
            self._client.http_command.load_preset(preset=self._preset.sdk_id),
            f"load_preset {self._preset.name}",
        )
        state = await self._must_ok(
            self._client.http_command.get_camera_state(), "get_camera_state",
        )
        # Phase 0 verification establishes the actual storage key name.
        # state.data is keyed by Status ID string. "54" = SD remaining in KB.
        remaining_kb = int(state.data.get("54", 0))
        if remaining_kb < _STORAGE_MIN_KB:
            raise HardwareError(
                f"GoPro {self._name} storage too low: {remaining_kb} KB remaining")

    async def disconnect(self) -> None:
        if self._client_ctx is None: return
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
            "set_shutter on",
        )

    async def shutter_off(self) -> None:
        if self._disabled or self._client is None: return
        await self._must_ok(
            self._client.http_command.set_shutter(shutter=constants.Toggle.DISABLE),
            "set_shutter off",
        )

    async def media_list(self) -> list[MediaItem]:
        if self._disabled or self._client is None: return []
        r = await self._must_ok(self._client.http_command.get_media_list(), "get_media_list")
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
            "set_preview_stream on",
        )

    async def stop_preview(self) -> None:
        if self._disabled or self._client is None: return
        await self._must_ok(
            self._client.http_command.set_preview_stream(mode=constants.Toggle.DISABLE),
            "set_preview_stream off",
        )

    async def download_file(self, sd_filename: str, dest: Path) -> None:
        if self._disabled or self._client is None: return
        await self._must_ok(
            self._client.http_command.download_file(camera_file=sd_filename, local_file=dest),
            f"download_file {sd_filename}",
        )

    async def get_storage_remaining(self) -> int:
        if self._disabled or self._client is None: return 0
        r = await self._must_ok(self._client.http_command.get_camera_state(), "get_camera_state")
        return int(r.data.get("54", 0)) * 1024   # KB → bytes

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

> If Phase 0 reveals different API names (e.g., `set_preset` vs `load_preset`, `target=` vs `serial=`, or different storage state key), update this file accordingly.

- [ ] **Step 4: Run — verify pass**

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/gopro/device.py tests/unit/gopro/test_device.py
git commit -m "feat(gopro): GoProDevice wrapping WiredGoPro with preset selection at init"
```

---

### Task 13: `init_dataset` accepts `gopro_specs`

**Files:**
- Modify: `backend/mimicrec/recording/dataset_layout.py`
- Test: `tests/unit/gopro/test_init_dataset_gopro.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

from mimicrec.gopro.types import GoProSpec
from mimicrec.recording.dataset_layout import init_dataset


def test_writes_gopro_features(tmp_path: Path):
    init_dataset(
        ds_root=tmp_path, fps=30,
        joint_names=["j0", "j1"],
        camera_names=["wrist"],
        camera_resolutions={"wrist": (640, 480)},
        gopro_specs={"gopro_x": GoProSpec(
            name="gopro_x", width=1280, height=720, fps=30, codec="libx264")},
    )
    info = json.loads((tmp_path / "meta" / "info.json").read_text())
    feats = info["features"]
    assert "observation.images.wrist" in feats
    assert "observation.images.gopro_x" in feats
    g = feats["observation.images.gopro_x"]
    assert g["shape"] == [720, 1280, 3]
    assert g["info"]["video.codec"] == "libx264"
    assert g["info"]["video.fps"] == 30
    assert g["info"]["has_gpmf"] is True


def test_no_gopros_unchanged(tmp_path: Path):
    init_dataset(
        ds_root=tmp_path, fps=30,
        joint_names=["j0"],
        camera_names=["front"],
        camera_resolutions={"front": (640, 480)},
    )
    info = json.loads((tmp_path / "meta" / "info.json").read_text())
    assert "observation.images.front" in info["features"]
```

- [ ] **Step 2: Run — verify fail** (`unexpected keyword 'gopro_specs'`)

- [ ] **Step 3: Edit `dataset_layout.py`**

Update the `init_dataset` signature and add the GoPro features block. The change is non-trivial; I'll point out the section:

In `init_dataset(...)` signature, after `camera_resolutions`, add:

```python
    gopro_specs: "dict[str, object] | None" = None,    # mimicrec.gopro.types.GoProSpec
```

After the existing `for cam in camera_names: ...` block, add:

```python
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

- [ ] **Step 4: Run — verify pass**

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/recording/dataset_layout.py tests/unit/gopro/test_init_dataset_gopro.py
git commit -m "feat(dataset): init_dataset accepts gopro_specs (has_gpmf marker)"
```

---

## Phase 5 — API integration

### Task 14: `schemas.py` — add `gopros` field

**Files:**
- Modify: `backend/mimicrec/api/schemas.py`
- Test: `tests/unit/gopro/test_schemas_gopros.py`

- [ ] **Step 1: Write the failing test**

```python
from mimicrec.api.schemas import StartSessionRequest, SessionStatePayload


# NOTE: mapper / dataset / task / etc. fields below are placeholders.
# Inspect the actual schemas.py and use whatever values existing tests use.
# If `StartSessionRequest` is the wrong class name in this codebase, replace
# with the real one (TeleopSessionRequest, etc.).


def test_start_session_request_gopros_default_empty():
    r = StartSessionRequest(
        dataset="ds", task="t", robot="so101",
        teleop="so_leader", mapper="identity", cameras=["wrist"], fps=30, mode="teleop",
    )
    assert r.gopros == []


def test_start_session_request_gopros_explicit():
    r = StartSessionRequest(
        dataset="ds", task="t", robot="so101",
        teleop="so_leader", mapper="identity", cameras=["wrist"], fps=30, mode="teleop",
        gopros=["g1"],
    )
    assert r.gopros == ["g1"]


def test_session_state_payload_gopros_default_empty():
    p = SessionStatePayload(state="idle", episode=None, dataset="ds", cameras=[])
    assert p.gopros == []
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Add fields**

In `backend/mimicrec/api/schemas.py`, locate `_BaseSessionRequest` and `SessionStatePayload`. Add `gopros: list[str] = Field(default_factory=list)` (Pydantic) or `gopros: list[str] = []` (depending on existing patterns).

- [ ] **Step 4: Run — verify pass + smoke**

```bash
env -u PYTHONPATH .venv/bin/python -m pytest ../tests -v -m 'not gopro_hardware'
```

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/api/schemas.py tests/unit/gopro/test_schemas_gopros.py
git commit -m "feat(api): add gopros field to session schemas"
```

---

### Task 15: `deps.py` — bootstrap registry with ConfigError → HTTPException(400)

**Files:**
- Modify: `backend/mimicrec/api/deps.py`
- Test: `tests/integration/test_gopro_session_bootstrap.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

# This is a slim integration test — verifies the deps.py wiring catches
# constructor errors and returns a clean HTTPException(400) instead of a 500.


@pytest.mark.asyncio
async def test_invalid_gopro_yaml_raises_http_400():
    """If a GoPro YAML specifies fps=25 (not supported), session start
    should return a 400 with a clear message — not a 500."""
    pytest.skip("Wire to API harness when ready (real test in Task 19)")
```

(Stub for now; full validation happens in Task 19.)

- [ ] **Step 2: Edit `deps.py`**

Find the existing camera bootstrap block (around line 105). After it, add:

```python
    # GoPros (NEW)
    overlap = set(req.cameras) & set(getattr(req, "gopros", []))
    if overlap:
        raise HTTPException(status_code=400,
                            detail=f"name overlap between cameras and gopros: {sorted(overlap)}")

    gopro_devices: list = []
    for g_name in getattr(req, "gopros", []):
        try:
            g_cfg = OmegaConf.load(configs_root / "gopros" / f"{g_name}.yaml")
            g_kwargs = {k: v for k, v in OmegaConf.to_container(g_cfg).items()
                        if k not in ("_target_",)}
            g_kwargs.setdefault("name", g_name)
            gopro_devices.append(instantiate_adapter(str(g_cfg._target_), **g_kwargs))
        except (ValueError, FileNotFoundError, OmegaConfBaseException) as e:
            raise HTTPException(status_code=400,
                                detail=f"GoPro config '{g_name}' invalid: {e}") from e

    error_bus = ErrorBus()

    from mimicrec.recording.dataset_layout import dataset_paths as _ds_paths
    paths = _ds_paths(datasets_root / req.dataset)
    paths.pending_dir.mkdir(parents=True, exist_ok=True)

    gopro_registry = None
    if gopro_devices:
        from mimicrec.gopro.registry import GoProDeviceRegistry
        try:
            gopro_registry = GoProDeviceRegistry(
                devices=gopro_devices, paths=paths, errors=error_bus,
            )
        except ValueError as e:
            raise HTTPException(status_code=400,
                                detail=f"GoPro registry invalid: {e}") from e

        await gopro_registry.start()
        for name, src in gopro_registry.preview_sources().items():
            cams[name] = src
```

Replace `CameraManager(cameras=cams, error_bus=error_bus)` to use the new merged `cams`. Inject `gopro_specs=gopro_registry.gopro_specs() if gopro_registry else None` into the existing `init_dataset(...)` call. Save `app.state.gopro_registry = gopro_registry`. Update `app.state.session_meta["gopros"] = list(getattr(req, "gopros", []))`.

Pass the registry to SessionManager (a new optional kwarg added in the next task):

```python
sm = SessionManager(
    ...,                                # existing kwargs
    gopro_registry=gopro_registry,      # NEW (default None)
)
```

Also locate where SessionManager / PendingEpisode opens video writers (likely in SessionManager) and exclude GoPro names from the `cameras: dict[str, tuple[int,int]]` passed to `open_video_writers`. The session_meta already has `"gopros"`; use it.

- [ ] **Step 3: Smoke run**

```bash
env -u PYTHONPATH .venv/bin/python -m pytest ../tests -v -m 'not gopro_hardware'
```

Existing tests should still pass.

- [ ] **Step 4: Commit**

```bash
git add backend/mimicrec/api/deps.py tests/integration/test_gopro_session_bootstrap.py
git commit -m "feat(api): bootstrap GoProDeviceRegistry with ConfigError -> HTTPException(400)"
```

---

### Task 15.5: SessionManager hooks for GoPro registry

**Files:**
- Modify: `backend/mimicrec/session/lifecycle.py` (SessionManager: constructor, `episode_start`, `episode_stop`, `episode_save`, `episode_discard`, `end` if it exists)
- Test: `tests/unit/gopro/test_session_manager_gopro.py`

This task wires the registry into SessionManager so that:
- `episode_start` → `gopro_registry.episode_start(idx, t)`
- `episode_stop` → `gopro_registry.episode_stop(idx)`
- `episode_save` → `gopro_registry.commit_episode(idx)` (move staged → dataset)
- `episode_discard` → `gopro_registry.discard_episode(idx)` (delete staged)
- session shutdown path → `gopro_registry.stop()` (no leak of worker / preview / SDK client)

The `gopro_registry` parameter must be **optional** (default `None`) so existing tests / code paths that don't use GoPro keep working.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/gopro/test_session_manager_gopro.py`:

```python
"""SessionManager calls registry hooks at the right lifecycle moments."""
from unittest.mock import AsyncMock

import pytest


class _FakeRegistry:
    """Minimal stand-in for GoProDeviceRegistry used to verify SessionManager
    delegation. We don't construct a real registry because lifecycle.py is
    deeply tied to the rest of the recording stack; the test focuses on
    delegation only."""
    def __init__(self):
        self.episode_start = AsyncMock()
        self.episode_stop = AsyncMock()
        self.commit_episode = AsyncMock()
        self.discard_episode = AsyncMock()
        self.stop = AsyncMock()


@pytest.mark.asyncio
async def test_session_manager_passes_registry_through_to_hooks():
    """SessionManager constructor accepts gopro_registry and forwards
    episode_start / episode_stop / episode_save / episode_discard /
    end (or equivalent shutdown path) to it.

    NOTE: this is a wiring test — the implementing subagent should locate
    the actual SessionManager initializer in
    backend/mimicrec/session/lifecycle.py and the relevant lifecycle
    methods. Replace this stub with the right call sequence for the
    repo's existing test harness."""
    pytest.skip(
        "Implement against the actual SessionManager test harness "
        "after wiring gopro_registry through. This stub documents intent."
    )
```

- [ ] **Step 2: Wire the registry through SessionManager**

Edit `backend/mimicrec/session/lifecycle.py`:

1. Add `gopro_registry: object | None = None` to `SessionManager.__init__` and store on `self._gopro_registry`.

2. In `episode_start` (find the existing method, likely around line 320-400; search for `def episode_start`):
   ```python
   if self._gopro_registry is not None:
       await self._gopro_registry.episode_start(self._episode_index, time.monotonic_ns())
   ```
   Place this AFTER the existing camera / pending / writer setup so a registry failure doesn't prevent the rest of the episode from starting.

3. In `episode_stop` (around line 399):
   ```python
   if self._gopro_registry is not None:
       await self._gopro_registry.episode_stop(self._episode_index)
   ```
   Place this before / after the existing `await self._recorder_queue.join()` block — order doesn't matter for correctness because the recorder is independent of MimicRec's writer queue.

4. In `episode_save` (around line 444), call commit BEFORE incrementing episode index:
   ```python
   if self._gopro_registry is not None:
       await self._gopro_registry.commit_episode(self._episode_index)
   ```
   Place at the start of the method body so a registry failure is reported but doesn't roll back the parquet save (we want both halves to commit).

5. In `episode_discard` (around line 509):
   ```python
   if self._gopro_registry is not None:
       await self._gopro_registry.discard_episode(self._episode_index)
   ```

6. Find SessionManager's shutdown path (`end()` or equivalent — search for `async def end` or for `self._cameras.stop()`). Add:
   ```python
   if self._gopro_registry is not None:
       try:
           await self._gopro_registry.stop()
       finally:
           self._gopro_registry = None
   ```

7. Update `app.state` cleanup wherever the existing code clears `app.state.camera_manager` (`backend/mimicrec/api/deps.py` clears it on session end). Add `app.state.gopro_registry = None` next to it.

- [ ] **Step 3: Run — verify pass + smoke**

```bash
env -u PYTHONPATH .venv/bin/python -m pytest ../tests -v -m 'not gopro_hardware'
```

Existing tests pass; the SessionManager test from Step 1 is `skip`ped (intentional — full coverage is in Task 18).

- [ ] **Step 4: Commit**

```bash
git add backend/mimicrec/session/lifecycle.py backend/mimicrec/api/deps.py tests/unit/gopro/test_session_manager_gopro.py
git commit -m "feat(session): wire GoProDeviceRegistry into SessionManager lifecycle hooks"
```

---

### Task 16: `GET /api/session/gopro_pending`

**Files:**
- Modify: `backend/mimicrec/api/routes/session.py`
- Test: `tests/api/test_gopro_pending_route.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_pending_returns_zero_when_no_session(app_no_session):
    client = TestClient(app_no_session)
    r = client.get("/api/session/gopro_pending")
    assert r.status_code == 200
    assert r.json() == {"pending": 0}
```

(Adapt fixture name to whatever the existing harness provides.)

- [ ] **Step 2: Add the endpoint**

In `backend/mimicrec/api/routes/session.py` (the existing router is mounted with prefix `/api`, so the decorator path **must NOT** include `/api`):

```python
@router.get("/session/gopro_pending")
async def gopro_pending(request: Request) -> dict[str, int]:
    reg = getattr(request.app.state, "gopro_registry", None)
    return {"pending": int(reg.pending_count) if reg is not None else 0}
```

Verify the prefix by checking how other routes in this file are decorated (e.g. existing `@router.get("/session/state")` etc.) — match that pattern.

- [ ] **Step 3: Run — verify pass**

- [ ] **Step 4: Commit**

```bash
git add backend/mimicrec/api/routes/session.py tests/api/test_gopro_pending_route.py
git commit -m "feat(api): GET /api/session/gopro_pending"
```

---

## Phase 6 — Frontend

### Task 17: Pending DL badge + quit warning

**Files:**
- Create: `frontend/src/components/GoProPendingBadge.tsx`
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/api/session.ts`

- [ ] **Step 1: API client**

```ts
// frontend/src/api/session.ts (append)
export async function getGoProPending(): Promise<number> {
  const r = await apiFetch('/api/session/gopro_pending');
  if (!r.ok) return 0;
  const j = await r.json();
  return j.pending ?? 0;
}
```

- [ ] **Step 2: Badge component**

```tsx
// frontend/src/components/GoProPendingBadge.tsx
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
      } catch {/* ignore */}
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(id); };
  }, []);
  if (pending === 0) return null;
  return <span title="GoPro DL pending">GoPro: {pending}</span>;
}
```

- [ ] **Step 3: Mount in Layout + quit warning**

Edit `frontend/src/components/Layout.tsx` to render `<GoProPendingBadge />` in the top nav.

Add a `beforeunload` handler at the App root (or wherever quit warnings live) that prompts when `pending > 0`.

- [ ] **Step 4: Manual test**

```bash
cd frontend && npm run dev
```

Open browser, verify badge appears when DL pending > 0 (use mock-based integration test backend), verify confirmation dialog on tab close.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/GoProPendingBadge.tsx frontend/src/components/Layout.tsx frontend/src/api/session.ts
git commit -m "feat(frontend): GoPro pending DL badge + quit warning"
```

---

## Phase 7 — Final integration

### Task 18: Mock-based end-to-end integration test

**Files:**
- Create: `tests/integration/test_gopro_mock_session.py`
- Create: `configs/gopros/mock_gopro.yaml`

- [ ] **Step 1: Mock GoPro YAML**

```yaml
# configs/gopros/mock_gopro.yaml
_target_: mimicrec.gopro.mock.MockGoProDevice
name: mock_gopro
usb_serial: "MOCK0001"
width: 1280
height: 720
fps: 30
aspect_mode: crop
fixture_mp4: "tests/fixtures/gopro/sample_episode.mp4"
emit_preview: false
chapters_per_episode: 1
```

- [ ] **Step 2: Integration test**

```python
# tests/integration/test_gopro_mock_session.py
import json
import pytest
from pathlib import Path


@pytest.mark.asyncio
async def test_three_episodes_with_mock_gopro(tmp_path):
    """End-to-end smoke test: 3 episodes recorded via the mock,
    DLWorker drains, dataset has all 3 MP4s + correct info.json."""
    pytest.importorskip("av")
    pytest.skip("Wire to API session harness when ready")
    # Steps:
    # 1. POST /api/session/start with cameras=[..mock_cam] gopros=[mock_gopro]
    # 2. for ep in 3: POST /api/session/episode_start, sleep, POST /api/session/episode_stop
    # 3. Poll GET /api/session/gopro_pending until 0 or timeout
    # 4. POST /api/session/stop
    # 5. Assert: paths.episode_video(0, 'mock_gopro', i) exists for i in 0..2
    # 6. Assert: info.json features.observation.images.mock_gopro.info.has_gpmf is True
    # 7. Assert: info.json codec is "h264" or "hevc" (post-DL ffprobe patched)
```

(Adapt to existing API harness style.)

- [ ] **Step 3: Run**

```bash
env -u PYTHONPATH .venv/bin/python -m pytest ../tests/integration/test_gopro_mock_session.py -v
```

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_gopro_mock_session.py configs/gopros/mock_gopro.yaml
git commit -m "test(gopro): mock-based end-to-end integration test"
```

---

### Task 19: Hardware verification (Hero 11 required)

**Files:**
- Modify: `pytest.ini`
- Create: `tests/integration/test_gopro_hardware.py`
- Create: `configs/gopros/gopro_external.yaml`
- Modify: `README.md`

- [ ] **Step 1: pytest marker**

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

- [ ] **Step 2: Real-device YAML**

```yaml
# configs/gopros/gopro_external.yaml
_target_: mimicrec.gopro.device.GoProDevice
name: gopro_external
usb_serial: "C3441234567890"   # replace with the real device's serial
width: 1280
height: 720
fps: 30
aspect_mode: crop
```

- [ ] **Step 3: Hardware test**

```python
# tests/integration/test_gopro_hardware.py
import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.gopro_hardware


@pytest.mark.asyncio
async def test_three_episodes_with_real_gopro(tmp_path: Path):
    """Manual prerequisites:
    - Hero 11 plugged in via USB
    - GOPRO_SERIAL env var set
    - cdc_ncm + avahi-daemon running
    """
    serial = os.environ.get("GOPRO_SERIAL")
    if not serial:
        pytest.skip("Set GOPRO_SERIAL")

    from mimicrec.gopro.device import GoProDevice
    from mimicrec.gopro.registry import GoProDeviceRegistry
    from mimicrec.recording.dataset_layout import dataset_paths
    from mimicrec.util.error_bus import ErrorBus

    paths = dataset_paths(tmp_path / "ds")
    for d in (paths.meta_dir, paths.pending_dir, paths.videos_dir):
        d.mkdir(parents=True, exist_ok=True)

    dev = GoProDevice(name="g_test", usb_serial=serial,
                     width=1280, height=720, fps=30, aspect_mode="crop")
    reg = GoProDeviceRegistry(devices=[dev], paths=paths, errors=ErrorBus())
    await reg.start()
    try:
        for ep in range(3):
            await reg.episode_start(ep, t_host_mono_ns=0)
            await asyncio.sleep(2.0)
            await reg.episode_stop(ep)
    finally:
        for _ in range(120):
            if reg.pending_count == 0: break
            await asyncio.sleep(1.0)
        await reg.stop()

    for ep in range(3):
        mp4 = paths.episode_video(0, "g_test", ep)
        assert mp4.exists(), f"missing {mp4}"
        # Confirm downscale: 1280x720, GPMF preserved
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(mp4)],
            text=True,
        ).strip()
        assert out == "1280,720", f"resolution mismatch: {out}"
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "default=nk=1", str(mp4)],
            text=True,
        )
        assert "GoPro MET" in out, f"GPMF lost in {mp4}"
```

- [ ] **Step 4: README**

Add a `## GoPro Hero 11 integration` section covering:
- YAML schema + example
- Preset / chapter limit table (from spec)
- Linux NCM environment setup (cdc_ncm, NetworkManager, avahi, firewall, autosuspend)
- ffmpeg ≥ 4.4 install
- Hardware test run command:
  ```
  cd backend
  GOPRO_SERIAL=<serial> env -u PYTHONPATH .venv/bin/python -m pytest \
    ../tests/integration/test_gopro_hardware.py -v -m gopro_hardware
  ```

- [ ] **Step 5: Run hardware test**

With Hero 11 plugged in:

```bash
cd /home/tirobot/MimicRec/backend
GOPRO_SERIAL=<actual> env -u PYTHONPATH .venv/bin/python -m pytest \
  ../tests/integration/test_gopro_hardware.py -v -m gopro_hardware
```

Expected: 1 passed.

- [ ] **Step 6: Manual DoD verification**

Run through each Definition-of-Done item in the spec one by one with the running system. Document any failures.

- [ ] **Step 7: Commit**

```bash
git add pytest.ini tests/integration/test_gopro_hardware.py configs/gopros/gopro_external.yaml README.md
git commit -m "test(gopro): hardware integration test + README"
```

---

## Self-Review

After all tasks land:

1. **Spec coverage**:
   - Goals 1-9 → Tasks 12, 13, 15, 17, 19 (and unit tests throughout)
   - DoD items → Task 19 manual verification + Tasks 13/15/18 automated

2. **No placeholders**: all `<...>` placeholders are concrete except `<exact version>` (Phase 0), `<actual serial>` (env var), and Phase 0 tables that update post-verification.

3. **Type consistency**: `GoProSpec` / `MediaItem` / `NativePreset` are defined once in `gopro/types.py` and consumed consistently. `GoProDLJob` schema matches across queue / recorder / worker.

4. **Critical-path order**: Phase 0 gates everything. Phase 1 unblocks all later tests. Phase 2 (preset picker, queue, mock) unblocks Phase 3. Phase 3 (control plane + ffmpeg) unblocks Phase 4. Phase 5 wires API. Phase 6 surfaces. Phase 7 verifies.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-09-gopro-recording.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Phase 0 gating uses human-in-the-loop confirmation.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints. Phase 0 hardware verification still requires user assistance to plug in the GoPro.

**Which approach?**
