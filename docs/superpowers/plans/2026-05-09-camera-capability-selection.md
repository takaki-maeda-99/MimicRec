# Camera Capability Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Settings の Edit モーダルでカメラの V4L2 capability (pixel format / resolution / capture FPS) をドロップダウン選択して YAML に永続化、加えて `info.json` の解像度ハードコードを per-camera 値に修正する。

**Architecture:** v4l2-ctl をシェルアウトしてケイパビリティを列挙し JSON で返す API + cv2 readback で strict 検証する OpenCVCamera + Edit モーダルを `_target_` で分岐させて構造化フォームに切替。`init_dataset()` を optional `camera_resolutions` で後方互換のまま、production caller (`deps.py` + `datasets.py`) を更新して info.json バグを直す。`manager.start()` は connect を up-front 同期化して strict mismatch を session_start にフェールアウトさせる。

**Tech Stack:** FastAPI (asyncio + run_in_executor) / OpenCV (V4L2 backend) / v4l2-ctl / pytest + httpx / React 19 + TypeScript + Vite

**Spec reference:** `docs/superpowers/specs/2026-05-09-camera-capability-selection-design.md`

---

## File Structure

| File | Purpose | Action |
|------|---------|--------|
| `backend/mimicrec/cameras/v4l2_caps.py` | v4l2-ctl 出力パーサ + dataclass + 列挙関数 | Create |
| `tests/unit/test_v4l2_caps.py` | パーサ単体テスト (fixture inline) | Create |
| `backend/mimicrec/recording/dataset_layout.py` | `init_dataset` に optional `camera_resolutions` 追加 | Modify |
| `tests/unit/test_recording_info_json.py` | per-camera resolution assert テスト追加 | Modify |
| `backend/mimicrec/api/deps.py` | `init_dataset` に `camera_resolutions` を渡す | Modify |
| `backend/mimicrec/api/routes/datasets.py` | `init_dataset` に `camera_resolutions` を渡す | Modify |
| `backend/mimicrec/cameras/opencv_camera.py` | `pixel_format` / `capture_fps` kwargs + readback 検証 + `_decode_fourcc` | Modify |
| `backend/mimicrec/cameras/manager.py` | `start()` で connect を up-front 同期化 | Modify |
| `tests/unit/test_camera_manager.py` | 新 connect セマンティクス検証 | Modify |
| `backend/mimicrec/api/routes/settings.py` | capabilities endpoint + PUT validation | Modify |
| `tests/api/test_settings_routes.py` | capabilities + PUT validation テスト | Modify |
| `frontend/src/api/cameras.ts` | capabilities API client | Create |
| `frontend/src/components/CameraConfigForm.tsx` | 構造化フォームコンポーネント | Create |
| `frontend/src/pages/SettingsPage.tsx` | Edit モーダル分岐 | Modify |

---

## Task 1: V4L2 capability parser

**Files:**
- Create: `backend/mimicrec/cameras/v4l2_caps.py`
- Create: `tests/unit/test_v4l2_caps.py`

- [ ] **Step 1: Write failing parser tests**

Create `tests/unit/test_v4l2_caps.py`:

```python
from unittest.mock import patch
from mimicrec.cameras.v4l2_caps import enumerate_capabilities, parse_v4l2_listfmts


SAMPLE_UVC = """ioctl: VIDIOC_ENUM_FMT
\tType: Video Capture

\t[0]: 'MJPG' (Motion-JPEG, compressed)
\t\tSize: Discrete 1280x720
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t\tSize: Discrete 640x480
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t[1]: 'YUYV' (YUYV 4:2:2)
\t\tSize: Discrete 1280x720
\t\t\tInterval: Discrete 0.100s (10.000 fps)
\t\tSize: Discrete 640x480
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t\t\tInterval: Discrete 0.067s (15.000 fps)
"""

SAMPLE_MPLANE = """ioctl: VIDIOC_ENUM_FMT
\tType: Video Capture Multiplanar

\t[0]: 'NV12M' (Y/CbCr 4:2:0 (N-C))
\t\tSize: Discrete 1920x1080
\t\t\tInterval: Discrete 0.033s (30.000 fps)
"""

SAMPLE_STEPWISE = """ioctl: VIDIOC_ENUM_FMT
\tType: Video Capture

\t[0]: 'H264' (H.264, compressed)
\t\tSize: Stepwise 320x240 - 1280x720 with step 320/240
\t[1]: 'MJPG' (Motion-JPEG, compressed)
\t\tSize: Discrete 640x480
\t\t\tInterval: Discrete 0.033s (30.000 fps)
"""


def test_parse_uvc_camera():
    formats = parse_v4l2_listfmts(SAMPLE_UVC)
    assert len(formats) == 2

    mjpg = formats[0]
    assert mjpg.fourcc == "MJPG"
    assert "Motion-JPEG" in mjpg.description
    assert len(mjpg.sizes) == 2
    assert mjpg.sizes[0].width == 1280 and mjpg.sizes[0].height == 720
    assert mjpg.sizes[0].fps == [30]

    yuyv = formats[1]
    assert yuyv.fourcc == "YUYV"
    # 640x480 has two intervals (30 fps and 15 fps)
    yuyv_640 = next(s for s in yuyv.sizes if s.width == 640)
    assert sorted(yuyv_640.fps, reverse=True) == [30, 15]


def test_skips_multiplane_format():
    # Multiplanar capture types are not supported by cv2's V4L2 backend.
    formats = parse_v4l2_listfmts(SAMPLE_MPLANE)
    assert formats == []


def test_skips_stepwise_size():
    # Stepwise sizes (typical for software H.264 encoders) are skipped;
    # discrete sizes from the next format are still returned.
    formats = parse_v4l2_listfmts(SAMPLE_STEPWISE)
    assert len(formats) == 1
    assert formats[0].fourcc == "MJPG"
    assert len(formats[0].sizes) == 1
    assert formats[0].sizes[0].width == 640


def test_enumerate_v4l2_ctl_missing_returns_empty():
    # subprocess raises FileNotFoundError when v4l2-ctl is not on PATH.
    with patch("mimicrec.cameras.v4l2_caps.subprocess.run", side_effect=FileNotFoundError):
        assert enumerate_capabilities("/dev/video0") == []


def test_enumerate_nonzero_exit_returns_empty():
    # subprocess returns non-zero on missing device or permission error.
    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "Cannot open device /dev/video99"
    with patch("mimicrec.cameras.v4l2_caps.subprocess.run", return_value=FakeResult()):
        assert enumerate_capabilities("/dev/video99") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_v4l2_caps.py -v`

Expected: FAIL — module `mimicrec.cameras.v4l2_caps` does not exist.

- [ ] **Step 3: Implement the parser module**

Create `backend/mimicrec/cameras/v4l2_caps.py`:

```python
"""V4L2 capability enumeration via `v4l2-ctl --list-formats-ext`.

Parses the textual output of v4l2-ctl into structured capability data.
Multiplane formats and stepwise/continuous frame sizes are skipped because
cv2's V4L2 backend does not support them.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


@dataclass
class FrameSize:
    width: int
    height: int
    fps: list[int]  # discrete frame rates available at this size


@dataclass
class FormatCaps:
    fourcc: str
    description: str
    sizes: list[FrameSize]


_FMT_RE = re.compile(r"^\s*\[\d+\]:\s+'([A-Z0-9]+)'\s+\((.+)\)\s*$")
_SIZE_DISCRETE_RE = re.compile(r"^\s*Size:\s+Discrete\s+(\d+)x(\d+)\s*$")
_INTERVAL_DISCRETE_RE = re.compile(
    r"^\s*Interval:\s+Discrete\s+[\d.]+s\s+\(([\d.]+)\s+fps\)\s*$"
)


def parse_v4l2_listfmts(stdout: str) -> list[FormatCaps]:
    """Parse the stdout of `v4l2-ctl --list-formats-ext` for a single device.

    Only `Type: Video Capture` blocks are considered; multiplanar blocks are
    dropped. Within a kept block, only Discrete sizes and Discrete intervals
    are kept; stepwise/continuous variants are dropped.
    """
    lines = stdout.splitlines()

    # Find the "Type: Video Capture" block (not Multiplanar).
    in_capture_block = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "Type: Video Capture":
            in_capture_block = True
            lines = lines[i + 1 :]
            break
        if stripped.startswith("Type: Video Capture Multiplanar"):
            return []
    if not in_capture_block:
        return []

    formats: list[FormatCaps] = []
    current_fmt: FormatCaps | None = None
    current_size: FrameSize | None = None

    for line in lines:
        m = _FMT_RE.match(line)
        if m:
            current_fmt = FormatCaps(fourcc=m.group(1), description=m.group(2), sizes=[])
            formats.append(current_fmt)
            current_size = None
            continue

        m = _SIZE_DISCRETE_RE.match(line)
        if m:
            if current_fmt is None:
                continue
            current_size = FrameSize(width=int(m.group(1)), height=int(m.group(2)), fps=[])
            current_fmt.sizes.append(current_size)
            continue

        m = _INTERVAL_DISCRETE_RE.match(line)
        if m:
            if current_size is None:
                continue
            current_size.fps.append(int(round(float(m.group(1)))))
            continue

        # Stepwise size resets current_size so subsequent intervals (if any) are dropped.
        if "Size: Stepwise" in line or "Size: Continuous" in line:
            current_size = None

    return formats


def enumerate_capabilities(device_path: str) -> list[FormatCaps]:
    """Run v4l2-ctl on the given device and return parsed capabilities.

    Returns [] if v4l2-ctl is not on PATH, returns non-zero, or output is empty.
    """
    try:
        result = subprocess.run(
            ["v4l2-ctl", "--list-formats-ext", "--device", device_path],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    if result.returncode != 0:
        return []
    return parse_v4l2_listfmts(result.stdout)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_v4l2_caps.py -v`

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/cameras/v4l2_caps.py tests/unit/test_v4l2_caps.py
git commit -m "$(cat <<'EOF'
feat(cameras): V4L2 capability parser via v4l2-ctl

Shells out to `v4l2-ctl --list-formats-ext` and parses the output into
FormatCaps / FrameSize dataclasses. Skips Multiplanar capture types
and stepwise/continuous frame sizes which cv2's V4L2 backend cannot use.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `init_dataset` — optional `camera_resolutions`

**Files:**
- Modify: `backend/mimicrec/recording/dataset_layout.py`
- Modify: `tests/unit/test_recording_info_json.py`

- [ ] **Step 1: Write failing test for per-camera resolution**

Append to `tests/unit/test_recording_info_json.py`:

```python
def test_init_dataset_writes_per_camera_resolution(tmp_path):
    init_dataset(
        tmp_path / "ds",
        fps=30,
        joint_names=["a", "b"],
        camera_names=["wrist", "front"],
        camera_resolutions={"wrist": (1920, 1080), "front": (640, 480)},
    )
    info = json.loads((tmp_path / "ds" / "meta" / "info.json").read_text())
    wrist = info["features"]["observation.images.wrist"]
    front = info["features"]["observation.images.front"]
    assert wrist["shape"] == [1080, 1920, 3]  # [height, width, channels]
    assert wrist["info"]["video.height"] == 1080
    assert wrist["info"]["video.width"] == 1920
    assert front["shape"] == [480, 640, 3]
    assert front["info"]["video.height"] == 480
    assert front["info"]["video.width"] == 640


def test_init_dataset_falls_back_to_default_resolution(tmp_path):
    # When camera_resolutions is not provided, the legacy 640x480 default applies.
    init_dataset(
        tmp_path / "ds",
        fps=30,
        joint_names=["a"],
        camera_names=["cam0"],
    )
    info = json.loads((tmp_path / "ds" / "meta" / "info.json").read_text())
    cam = info["features"]["observation.images.cam0"]
    assert cam["shape"] == [480, 640, 3]
    assert cam["info"]["video.height"] == 480
    assert cam["info"]["video.width"] == 640
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `pytest tests/unit/test_recording_info_json.py -v`

Expected: `test_init_dataset_writes_per_camera_resolution` FAIL (TypeError: unexpected keyword `camera_resolutions`). `test_init_dataset_falls_back_to_default_resolution` PASS (existing behavior).

- [ ] **Step 3: Add optional `camera_resolutions` to `init_dataset`**

Modify `backend/mimicrec/recording/dataset_layout.py`:

Change the signature (lines 42-51 currently):
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
) -> None:
```

To:
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
) -> None:
```

Replace the camera features block (lines 70-81 currently):
```python
    for cam in camera_names:
        features[f"observation.images.{cam}"] = {
            "dtype": "video",
            "shape": [480, 640, 3],
            "names": ["height", "width", "channels"],
            "info": {
                "video.height": 480, "video.width": 640,
                "video.codec": "libx264", "video.pix_fmt": "yuv420p",
                "video.is_depth_map": False, "video.fps": fps,
                "video.channels": 3, "has_audio": False,
            },
        }
```

With:
```python
    for cam in camera_names:
        if camera_resolutions and cam in camera_resolutions:
            w, h = camera_resolutions[cam]
        else:
            w, h = 640, 480
        features[f"observation.images.{cam}"] = {
            "dtype": "video",
            "shape": [h, w, 3],
            "names": ["height", "width", "channels"],
            "info": {
                "video.height": h, "video.width": w,
                "video.codec": "libx264", "video.pix_fmt": "yuv420p",
                "video.is_depth_map": False, "video.fps": fps,
                "video.channels": 3, "has_audio": False,
            },
        }
```

- [ ] **Step 4: Run tests to verify both pass**

Run: `pytest tests/unit/test_recording_info_json.py -v`

Expected: All tests PASS (including 4 existing + 2 new = 6).

- [ ] **Step 5: Run full unit suite to confirm no regressions**

Run: `pytest tests/unit/ -q`

Expected: green; if any new failure surfaces, it must be in a test that asserted on hardcoded 480/640 — investigate before committing.

- [ ] **Step 6: Commit**

```bash
git add backend/mimicrec/recording/dataset_layout.py tests/unit/test_recording_info_json.py
git commit -m "$(cat <<'EOF'
feat(recording): init_dataset accepts per-camera resolutions

Adds optional `camera_resolutions: dict[str, tuple[int, int]] | None`
keyword arg. When provided, writes the per-camera (width, height) into
info.json's `shape` and `video.height/width` fields. When omitted,
falls back to the legacy 640x480 default — keeping all existing
callers (51 callsites) working unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Production callers pass `camera_resolutions`

**Files:**
- Modify: `backend/mimicrec/api/deps.py`
- Modify: `backend/mimicrec/api/routes/datasets.py`

- [ ] **Step 1: Update `deps.py::create_session_from_request`**

In `backend/mimicrec/api/deps.py`, locate the `init_dataset(` call (around line 154). Just before that call, build the resolutions dict and pass it:

Find this block:
```python
    if not ds_root.exists():
        # Capture per-adapter declarations if available (None for mock adapters).
        rt = type(robot).__name__
        gc = (
            robot.default_gripper_convention()
            if hasattr(robot, "default_gripper_convention") else None
        )
        pl = (
            robot.proprio_layout()
            if hasattr(robot, "proprio_layout") else None
        )
        init_dataset(
            ds_root, fps=req.fps,
            joint_names=robot.joint_names,
            camera_names=list(req.cameras),
            robot_type=rt,
            gripper_convention=(
                {"closed_at": gc.closed_at, "open_at": gc.open_at} if gc else None
            ),
            proprio_layout=(
                {
                    "columns": list(pl.columns),
                    "output_names": list(pl.output_names),
                    "gripper_via_column": pl.gripper_via_column,
                    "gripper_index_in_column": pl.gripper_index_in_column,
                } if pl else None
            ),
        )
```

Change the `init_dataset(...)` call to:
```python
        camera_resolutions = {
            cam_name: (
                int(cam_cfgs[cam_name].get("width", 640)),
                int(cam_cfgs[cam_name].get("height", 480)),
            )
            for cam_name in req.cameras
        }
        init_dataset(
            ds_root, fps=req.fps,
            joint_names=robot.joint_names,
            camera_names=list(req.cameras),
            robot_type=rt,
            gripper_convention=(
                {"closed_at": gc.closed_at, "open_at": gc.open_at} if gc else None
            ),
            proprio_layout=(
                {
                    "columns": list(pl.columns),
                    "output_names": list(pl.output_names),
                    "gripper_via_column": pl.gripper_via_column,
                    "gripper_index_in_column": pl.gripper_index_in_column,
                } if pl else None
            ),
            camera_resolutions=camera_resolutions,
        )
```

`cam_cfgs` is already populated earlier in the function from camera YAMLs.

- [ ] **Step 2: Update `datasets.py::create_dataset` (POST /datasets)**

Find this in `backend/mimicrec/api/routes/datasets.py` (around line 68):

```python
    init_dataset(ds_root, fps=body.fps, joint_names=body.joint_names, camera_names=body.camera_names)
```

Replace with (read each camera YAML to derive resolutions; missing files fall through to default):

```python
    from omegaconf import OmegaConf
    configs_root = get_configs_root(request.app)
    camera_resolutions: dict[str, tuple[int, int]] = {}
    for cam_name in body.camera_names:
        cam_path = configs_root / "cameras" / f"{cam_name}.yaml"
        if cam_path.exists():
            cam_cfg = OmegaConf.to_container(OmegaConf.load(cam_path))
            if isinstance(cam_cfg, dict):
                camera_resolutions[cam_name] = (
                    int(cam_cfg.get("width", 640)),
                    int(cam_cfg.get("height", 480)),
                )
    init_dataset(
        ds_root,
        fps=body.fps,
        joint_names=body.joint_names,
        camera_names=body.camera_names,
        camera_resolutions=camera_resolutions,
    )
```

If `request` and `get_configs_root` are not already imported / available in scope, ensure they are. Check the existing imports at the top of `datasets.py`:
- `from fastapi import APIRouter, Request, ...` — should already include `Request`
- `from mimicrec.api.deps import get_configs_root, ...` — verify

The function signature must take `request: Request` (already does in similar routes). If not, add it.

- [ ] **Step 3: Run full backend test suite**

Run: `pytest tests/ -q --ignore=tests/api/test_settings_routes.py`

(The settings routes file has its own pytest run at the end of Task 7; skipping it here saves time on this checkpoint.)

Expected: 0 new regressions. Existing failures (lerobot[dataset], aiohttp_client) are pre-existing and acceptable.

- [ ] **Step 4: Commit**

```bash
git add backend/mimicrec/api/deps.py backend/mimicrec/api/routes/datasets.py
git commit -m "$(cat <<'EOF'
fix(recording): pass per-camera resolutions to init_dataset

Both production callers (session_start via deps.py, and POST /datasets)
now derive each camera's (width, height) from its YAML config and pass
them as `camera_resolutions` to init_dataset(). Fixes the long-standing
bug where info.json always recorded 480x640 regardless of the actual
camera resolution.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `OpenCVCamera` — `pixel_format`/`capture_fps` kwargs + readback validation

**Files:**
- Modify: `backend/mimicrec/cameras/opencv_camera.py`

There are no unit tests for `OpenCVCamera` today (only the manager). We add the kwargs and rely on Task 7's PUT-validation tests + manual hardware verification (Task 11) to exercise readback.

- [ ] **Step 1: Replace the file content**

Overwrite `backend/mimicrec/cameras/opencv_camera.py` with:

```python
from __future__ import annotations
import asyncio
import cv2
import numpy as np

from mimicrec.types import Frame


def _decode_fourcc(v: int) -> str:
    """Decode the 4-byte little-endian fourcc int returned by cv2 into a 4-char string."""
    return bytes(
        [v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF]
    ).decode("ascii", errors="replace")


class OpenCVCamera:
    def __init__(
        self,
        name: str,
        device_id: int = 0,
        width: int = 640,
        height: int = 480,
        pixel_format: str | None = None,
        capture_fps: int | None = None,
    ):
        self.name = name
        self._device_id = device_id
        self._width = width
        self._height = height
        self._pixel_format = pixel_format
        self._capture_fps = capture_fps
        self._cap = None

    def _open(self):
        # Use device path for reliability (index-based open fails on some V4L2 drivers)
        path = f"/dev/video{self._device_id}"
        self._cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
        if not self._cap.isOpened():
            # Fallback to index
            self._cap = cv2.VideoCapture(self._device_id)
        if not self._cap.isOpened():
            raise RuntimeError(f"cannot open camera {self._device_id} ({path})")

        # V4L2 typical property order: fourcc -> width/height -> fps.
        # Setting in reverse can cause silent driver-side fallbacks.
        if self._pixel_format is not None:
            self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self._pixel_format))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        if self._capture_fps is not None:
            self._cap.set(cv2.CAP_PROP_FPS, self._capture_fps)

        # Strict readback: cv2.VideoCapture.set() returns True even when the
        # driver clamps to a different format/size/fps. We compare what we
        # asked for to what the driver actually negotiated and raise on
        # mismatch. Skip the comparison for fields the user did not specify.
        actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fourcc = _decode_fourcc(int(self._cap.get(cv2.CAP_PROP_FOURCC)))
        actual_fps = int(round(self._cap.get(cv2.CAP_PROP_FPS)))

        mismatches: list[str] = []
        if actual_w != self._width or actual_h != self._height:
            mismatches.append(
                f"size: requested {self._width}x{self._height}, got {actual_w}x{actual_h}"
            )
        if self._pixel_format is not None and actual_fourcc != self._pixel_format:
            mismatches.append(
                f"fourcc: requested {self._pixel_format}, got {actual_fourcc}"
            )
        if self._capture_fps is not None and actual_fps != self._capture_fps:
            mismatches.append(
                f"fps: requested {self._capture_fps}, got {actual_fps}"
            )

        if mismatches:
            self._cap.release()
            self._cap = None
            raise RuntimeError(
                f"camera {self.name}: cv2 negotiated different parameters: "
                + "; ".join(mismatches)
            )

    def _close(self):
        if self._cap:
            self._cap.release()
            self._cap = None

    async def connect(self):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._open)

    async def disconnect(self):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._close)

    async def read(self) -> Frame:
        loop = asyncio.get_running_loop()
        ret, frame = await loop.run_in_executor(None, self._cap.read)
        if not ret or frame is None:
            raise TimeoutError(f"camera {self.name} read failed")
        return Frame(image=frame)
```

Notable changes from the previous version:
- New kwargs `pixel_format` / `capture_fps` (both default `None`)
- New `_decode_fourcc` helper at module level
- The early `isOpened()` check (before set calls) replaces the old post-set check, matching V4L2's expected property-set order
- Strict readback at the end of `_open()`; raises `RuntimeError` with diagnostic detail on mismatch

- [ ] **Step 2: Sanity-check via existing import paths**

Run: `python -c "from mimicrec.cameras.opencv_camera import OpenCVCamera, _decode_fourcc; assert _decode_fourcc(0x47504A4D) == 'MJPG'"`

Expected: no output, exit 0.

If `python -c` complains about imports, run from the repo root with `PYTHONPATH=backend`.

- [ ] **Step 3: Run camera-related unit tests**

Run: `pytest tests/unit/test_camera_manager.py -v`

Expected: PASS (existing tests should still pass — they use MockCamera, not OpenCVCamera).

- [ ] **Step 4: Commit**

```bash
git add backend/mimicrec/cameras/opencv_camera.py
git commit -m "$(cat <<'EOF'
feat(cameras): OpenCVCamera supports pixel_format / capture_fps + strict readback

Adds optional kwargs `pixel_format` (e.g. "MJPG") and `capture_fps`. After
opening, reads back CAP_PROP_FOURCC / FRAME_WIDTH / FRAME_HEIGHT / FPS
and raises RuntimeError if cv2 silently negotiated different values
than requested. None-valued kwargs skip their respective comparison so
existing camera YAMLs continue working unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `manager.start()` — up-front connect synchronization

**Files:**
- Modify: `backend/mimicrec/cameras/manager.py`
- Modify: `tests/unit/test_camera_manager.py`

- [ ] **Step 1: Read the existing test file and write a failing test**

Read `tests/unit/test_camera_manager.py` to learn the existing patterns (MockCamera, async test setup, error_bus fixture).

Append a new test (adapt the imports / fixtures to match the file's existing style):

```python
async def test_manager_start_aborts_when_a_camera_connect_fails():
    """If any camera's connect() raises, manager.start() must propagate the
    error and disconnect previously-connected cameras."""

    class FakeCam:
        def __init__(self, name, fail=False):
            self.name = name
            self.fail = fail
            self.connected = False
            self.disconnected = False

        async def connect(self):
            if self.fail:
                raise RuntimeError(f"{self.name} connect failed")
            self.connected = True

        async def disconnect(self):
            self.disconnected = True

        async def read(self):
            await asyncio.sleep(3600)  # never used
            raise AssertionError

    cam_a = FakeCam("a", fail=False)
    cam_b = FakeCam("b", fail=True)
    cam_c = FakeCam("c", fail=False)

    cm = CameraManager(cameras={"a": cam_a, "b": cam_b, "c": cam_c}, error_bus=ErrorBus())

    with pytest.raises(RuntimeError, match="b connect failed"):
        await cm.start()

    assert cam_a.disconnected, "previously-connected camera should be disconnected on rollback"
    assert not cam_c.connected, "later cameras should not be attempted after a failure"
    assert cm._tasks == [], "no read tasks should be spawned when start() aborts"
```

(Imports needed at top of file if missing: `import asyncio`, `import pytest`, `from mimicrec.cameras.manager import CameraManager`, `from mimicrec.util.error_bus import ErrorBus`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_camera_manager.py::test_manager_start_aborts_when_a_camera_connect_fails -v`

Expected: FAIL — current `start()` swallows connect errors inside `_run_camera`, so no exception propagates.

- [ ] **Step 3: Refactor `manager.start()` to up-front connect**

In `backend/mimicrec/cameras/manager.py`, replace the current `start` and adjust `_run_camera`:

Replace this:
```python
    async def start(self) -> None:
        for name, cam in self._cameras.items():
            self._tasks.append(asyncio.create_task(self._run_camera(name, cam)))
```

With:
```python
    async def start(self) -> None:
        # Connect every camera up-front so any failure aborts session_start
        # rather than silently dropping the camera mid-session.
        connected: list[str] = []
        try:
            for name, cam in self._cameras.items():
                if hasattr(cam, "connect"):
                    await cam.connect()
                connected.append(name)
        except Exception as e:
            for prev in connected:
                prev_cam = self._cameras[prev]
                if hasattr(prev_cam, "disconnect"):
                    try:
                        await prev_cam.disconnect()
                    except Exception:
                        pass
            raise RuntimeError(f"camera startup failed: {e}") from e

        for name, cam in self._cameras.items():
            self._tasks.append(asyncio.create_task(self._run_camera(name, cam)))
```

Then in the same file, modify `_run_camera` to remove the connect block (cameras are already connected by the time `_run_camera` runs):

Replace this:
```python
    async def _run_camera(self, name: str, cam) -> None:
        # Connect camera if it has a connect method (OpenCVCamera needs it, MockCamera doesn't)
        if hasattr(cam, "connect"):
            try:
                await cam.connect()
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"camera {name} connect failed: {e}")
                return  # Don't publish to ErrorBus — failed camera shouldn't kill the session
        while not self._stopped.is_set():
```

With:
```python
    async def _run_camera(self, name: str, cam) -> None:
        # Cameras are connected up-front in start() so any connect failure
        # aborts session_start. Here we just run the read loop.
        while not self._stopped.is_set():
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_camera_manager.py -v`

Expected: All PASS, including the new one.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/cameras/manager.py tests/unit/test_camera_manager.py
git commit -m "$(cat <<'EOF'
fix(cameras): connect all cameras up-front in CameraManager.start()

Previously _run_camera swallowed connect errors with a warning, leaving
sessions running with silently-missing cameras. Move connect to a
synchronous up-front loop in start() so any failure (including
OpenCVCamera's strict readback mismatch) aborts session_start cleanly,
disconnecting any cameras already connected during the rollback.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Capabilities API endpoint

**Files:**
- Modify: `backend/mimicrec/api/routes/settings.py`
- Modify: `tests/api/test_settings_routes.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/api/test_settings_routes.py`:

```python
import asyncio
from unittest.mock import patch

from mimicrec.cameras.v4l2_caps import FormatCaps, FrameSize


async def test_camera_capabilities_returns_parsed_list(app):
    fake = [
        FormatCaps(
            fourcc="MJPG",
            description="Motion-JPEG (compressed)",
            sizes=[FrameSize(width=1280, height=720, fps=[30])],
        )
    ]
    with patch(
        "mimicrec.api.routes.settings.enumerate_capabilities", return_value=fake
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/settings/devices/cameras/0/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body == [
        {
            "fourcc": "MJPG",
            "description": "Motion-JPEG (compressed)",
            "sizes": [{"width": 1280, "height": 720, "fps": [30]}],
        }
    ]


async def test_camera_capabilities_has_no_store_cache_control(app):
    with patch(
        "mimicrec.api.routes.settings.enumerate_capabilities", return_value=[]
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/settings/devices/cameras/0/capabilities")
    assert r.headers.get("cache-control") == "no-store"


async def test_camera_capabilities_returns_404_for_missing_device(app):
    # Patch glob to claim no /dev/video* exist.
    with patch("mimicrec.api.routes.settings.glob.glob", return_value=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/settings/devices/cameras/99/capabilities")
    assert r.status_code == 404


async def test_camera_capabilities_empty_list_when_v4l2_ctl_unavailable(app):
    # The endpoint returns 200 with [] when v4l2-ctl is missing — UI handles gracefully.
    with patch(
        "mimicrec.api.routes.settings.glob.glob", return_value=["/dev/video0"]
    ), patch(
        "mimicrec.api.routes.settings.enumerate_capabilities", return_value=[]
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/settings/devices/cameras/0/capabilities")
    assert r.status_code == 200
    assert r.json() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_settings_routes.py -v`

Expected: 4 new tests FAIL (route does not exist; 404 from default).

- [ ] **Step 3: Implement the endpoint**

In `backend/mimicrec/api/routes/settings.py`, add the import at the top:

```python
import asyncio
from dataclasses import asdict
from fastapi import HTTPException
from mimicrec.cameras.v4l2_caps import enumerate_capabilities
```

(Existing imports of `glob`, `Response`, `APIRouter`, `Request` should stay. Add `asyncio` / `asdict` / `HTTPException` / `enumerate_capabilities` if not already present.)

Then add the new route. Insert it after `list_camera_devices` (around line 51 of the current file):

```python
@router.get("/settings/devices/cameras/{device_id}/capabilities")
async def list_camera_capabilities(device_id: int, response: Response):
    """Enumerate V4L2 capabilities for /dev/video{device_id} via v4l2-ctl.

    Returns 200 with [] if v4l2-ctl is unavailable or returns nothing useful
    so the UI can render gracefully. Returns 404 only when /dev/video{N}
    does not exist on disk.
    """
    response.headers["Cache-Control"] = "no-store"
    path = f"/dev/video{device_id}"
    if path not in glob.glob("/dev/video*"):
        raise HTTPException(status_code=404, detail=f"device {path} not found")

    loop = asyncio.get_running_loop()
    caps = await loop.run_in_executor(None, enumerate_capabilities, path)
    return [asdict(c) for c in caps]
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/api/test_settings_routes.py -v`

Expected: All PASS (5 existing + 4 new = 9).

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/api/routes/settings.py tests/api/test_settings_routes.py
git commit -m "$(cat <<'EOF'
feat(api): camera capabilities endpoint

GET /api/settings/devices/cameras/{device_id}/capabilities returns
the parsed v4l2-ctl capability list (formats × sizes × fps) for the
given /dev/video{N}. Empty list when v4l2-ctl is missing or returns
nothing usable. 404 only when the device node doesn't exist. The
v4l2-ctl subprocess runs in run_in_executor to keep the FastAPI
event loop responsive.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: PUT validation for camera configs

**Files:**
- Modify: `backend/mimicrec/api/routes/settings.py`
- Modify: `tests/api/test_settings_routes.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/api/test_settings_routes.py`:

```python
async def test_put_camera_config_validates_and_writes(app, tmp_path):
    # Point the configs root at a tmp dir we control.
    cameras_dir = tmp_path / "cameras"
    cameras_dir.mkdir()
    (cameras_dir / "wrist.yaml").write_text(
        "_target_: mimicrec.cameras.opencv_camera.OpenCVCamera\n"
        "name: wrist\n"
        "device_id: 0\n"
        "width: 640\n"
        "height: 480\n"
    )
    app.state.configs_root = tmp_path

    # Pretend validation succeeds: the OpenCVCamera open returns matching values.
    class FakeCap:
        def isOpened(self):
            return True
        def get(self, prop):
            import cv2
            mapping = {
                cv2.CAP_PROP_FRAME_WIDTH: 1280,
                cv2.CAP_PROP_FRAME_HEIGHT: 720,
                cv2.CAP_PROP_FOURCC: int.from_bytes(b"MJPG", "little"),
                cv2.CAP_PROP_FPS: 30,
            }
            return mapping[prop]
        def set(self, *_):
            return True
        def release(self):
            pass

    with patch("mimicrec.api.routes.settings.cv2.VideoCapture", return_value=FakeCap()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.put(
                "/api/settings/configs/cameras/wrist",
                json={"content": {
                    "_target_": "mimicrec.cameras.opencv_camera.OpenCVCamera",
                    "name": "wrist",
                    "device_id": 0,
                    "width": 1280,
                    "height": 720,
                    "pixel_format": "MJPG",
                    "capture_fps": 30,
                }},
            )
    assert r.status_code == 200
    written = (cameras_dir / "wrist.yaml").read_text()
    assert "MJPG" in written
    assert "capture_fps: 30" in written


async def test_put_camera_config_returns_409_on_mismatch(app, tmp_path):
    cameras_dir = tmp_path / "cameras"
    cameras_dir.mkdir()
    (cameras_dir / "wrist.yaml").write_text(
        "_target_: mimicrec.cameras.opencv_camera.OpenCVCamera\n"
        "name: wrist\n"
        "device_id: 0\n"
        "width: 640\n"
        "height: 480\n"
    )
    app.state.configs_root = tmp_path

    # Driver returns YUYV/640x480/10fps even though we ask for MJPG/1920x1080/30
    class FakeCap:
        def isOpened(self):
            return True
        def get(self, prop):
            import cv2
            mapping = {
                cv2.CAP_PROP_FRAME_WIDTH: 640,
                cv2.CAP_PROP_FRAME_HEIGHT: 480,
                cv2.CAP_PROP_FOURCC: int.from_bytes(b"YUYV", "little"),
                cv2.CAP_PROP_FPS: 10,
            }
            return mapping[prop]
        def set(self, *_):
            return True
        def release(self):
            pass

    with patch("mimicrec.api.routes.settings.cv2.VideoCapture", return_value=FakeCap()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.put(
                "/api/settings/configs/cameras/wrist",
                json={"content": {
                    "_target_": "mimicrec.cameras.opencv_camera.OpenCVCamera",
                    "name": "wrist",
                    "device_id": 0,
                    "width": 1920,
                    "height": 1080,
                    "pixel_format": "MJPG",
                    "capture_fps": 30,
                }},
            )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "MJPG" in detail and "YUYV" in detail
    # YAML must NOT be overwritten on validation failure.
    assert "1920" not in (cameras_dir / "wrist.yaml").read_text()


async def test_put_camera_config_skips_validation_when_busy(app, tmp_path):
    cameras_dir = tmp_path / "cameras"
    cameras_dir.mkdir()
    (cameras_dir / "wrist.yaml").write_text(
        "_target_: mimicrec.cameras.opencv_camera.OpenCVCamera\n"
        "name: wrist\n"
        "device_id: 0\n"
        "width: 640\n"
        "height: 480\n"
    )
    app.state.configs_root = tmp_path

    # Simulate device-busy: VideoCapture instance reports not opened.
    class BusyCap:
        def isOpened(self):
            return False
        def release(self):
            pass

    with patch("mimicrec.api.routes.settings.cv2.VideoCapture", return_value=BusyCap()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.put(
                "/api/settings/configs/cameras/wrist",
                json={"content": {
                    "_target_": "mimicrec.cameras.opencv_camera.OpenCVCamera",
                    "name": "wrist",
                    "device_id": 0,
                    "width": 1920,
                    "height": 1080,
                    "pixel_format": "MJPG",
                    "capture_fps": 30,
                }},
            )
    assert r.status_code == 200
    assert r.headers.get("X-Validation-Skipped") == "device-busy"
    assert "1920" in (cameras_dir / "wrist.yaml").read_text()


async def test_put_non_camera_config_skips_validation(app, tmp_path):
    # PUT for robot configs etc. must not attempt camera validation.
    robot_dir = tmp_path / "robot"
    robot_dir.mkdir()
    (robot_dir / "mock.yaml").write_text("_target_: mimicrec.adapters.mock_robot.MockRobotAdapter\ndof: 6\n")
    app.state.configs_root = tmp_path

    # If the validation block is wrongly invoked, this would explode (no cv2 patch).
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.put(
            "/api/settings/configs/robot/mock",
            json={"content": {
                "_target_": "mimicrec.adapters.mock_robot.MockRobotAdapter",
                "dof": 7,
            }},
        )
    assert r.status_code == 200
    assert "dof: 7" in (robot_dir / "mock.yaml").read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_settings_routes.py -v -k "put_camera_config or put_non_camera"`

Expected: 4 new tests FAIL or behave incorrectly (the existing PUT writes the YAML without any validation).

- [ ] **Step 3: Implement PUT validation**

In `backend/mimicrec/api/routes/settings.py`, add `import cv2` near the top imports.

Locate the existing `update_config` route (currently around line 89-97) and rewrite it:

```python
@router.put("/settings/configs/{group}/{name}")
async def update_config(request: Request, group: str, name: str, body: ConfigUpdate, response: Response):
    """Update a config file. For OpenCVCamera configs, validate by opening
    the camera and reading back the negotiated parameters before writing.
    Returns 409 on mismatch. If the camera is busy (in use by another
    session), validation is skipped and an X-Validation-Skipped header is
    set so the UI can warn the user that final validation will happen at
    session_start.
    """
    response.headers["Cache-Control"] = "no-store"
    root = get_configs_root(request.app)
    path = root / group / f"{name}.yaml"

    if (
        group == "cameras"
        and isinstance(body.content, dict)
        and body.content.get("_target_") == "mimicrec.cameras.opencv_camera.OpenCVCamera"
    ):
        skipped_busy = await _validate_camera_config_or_409(body.content, response)
        if skipped_busy is None:
            # validation passed — fall through to write
            pass

    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = OmegaConf.create(body.content)
    OmegaConf.save(cfg, path)
    return {"name": name, "group": group, "content": body.content}


async def _validate_camera_config_or_409(content: dict, response: Response):
    """Open the camera with the requested parameters, read back, and either
    raise HTTPException(409) on mismatch or set X-Validation-Skipped on busy.
    Returns "busy" string if validation was skipped, None if validation passed.
    """
    device_id = int(content.get("device_id", 0))
    width = int(content.get("width", 640))
    height = int(content.get("height", 480))
    pixel_format = content.get("pixel_format")
    capture_fps = content.get("capture_fps")

    def _probe():
        cap = cv2.VideoCapture(f"/dev/video{device_id}", cv2.CAP_V4L2)
        if not cap.isOpened():
            return ("busy", None)
        try:
            if pixel_format is not None:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*pixel_format))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            if capture_fps is not None:
                cap.set(cv2.CAP_PROP_FPS, capture_fps)

            actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
            actual_fourcc = bytes([
                fourcc_int & 0xFF,
                (fourcc_int >> 8) & 0xFF,
                (fourcc_int >> 16) & 0xFF,
                (fourcc_int >> 24) & 0xFF,
            ]).decode("ascii", errors="replace")
            actual_fps = int(round(cap.get(cv2.CAP_PROP_FPS)))
        finally:
            cap.release()

        mismatches = []
        if actual_w != width or actual_h != height:
            mismatches.append(f"size: requested {width}x{height}, got {actual_w}x{actual_h}")
        if pixel_format is not None and actual_fourcc != pixel_format:
            mismatches.append(f"fourcc: requested {pixel_format}, got {actual_fourcc}")
        if capture_fps is not None and actual_fps != capture_fps:
            mismatches.append(f"fps: requested {capture_fps}, got {actual_fps}")
        return ("ok", mismatches)

    loop = asyncio.get_running_loop()
    status, mismatches = await loop.run_in_executor(None, _probe)
    if status == "busy":
        response.headers["X-Validation-Skipped"] = "device-busy"
        return "busy"
    if mismatches:
        raise HTTPException(
            status_code=409,
            detail="validation failed: " + "; ".join(mismatches),
        )
    return None
```

- [ ] **Step 4: Run all settings_routes tests**

Run: `pytest tests/api/test_settings_routes.py -v`

Expected: All PASS (existing 5 + capabilities 4 + PUT validation 4 = 13).

- [ ] **Step 5: Run full backend suite**

Run: `pytest tests/ -q`

Expected: 0 new regressions vs. main.

- [ ] **Step 6: Commit**

```bash
git add backend/mimicrec/api/routes/settings.py tests/api/test_settings_routes.py
git commit -m "$(cat <<'EOF'
feat(api): validate camera configs on PUT before writing YAML

When a PUT to /api/settings/configs/cameras/{name} carries an
OpenCVCamera config, open the camera with the requested fourcc /
size / fps and read back what cv2 actually negotiated. Return 409
with a diagnostic detail on mismatch (YAML stays untouched). When
the camera is in use elsewhere (cv2.VideoCapture not opened), skip
validation, set X-Validation-Skipped: device-busy, and write the
YAML — final validation will happen at session_start.

Non-camera configs and non-OpenCVCamera _target_'s skip validation.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Frontend `cameras.ts` API client

**Files:**
- Create: `frontend/src/api/cameras.ts`

- [ ] **Step 1: Create the API client module**

Create `frontend/src/api/cameras.ts`:

```ts
import { apiFetch } from "./client";

export interface FrameSize {
  width: number;
  height: number;
  fps: number[];
}

export interface FormatCaps {
  fourcc: string;
  description: string;
  sizes: FrameSize[];
}

export const fetchCameraCapabilities = (deviceId: number) =>
  apiFetch<FormatCaps[]>(`/api/settings/devices/cameras/${deviceId}/capabilities`);

export interface SaveCameraConfigArgs {
  name: string;
  content: {
    _target_: string;
    name: string;
    device_id: number;
    width: number;
    height: number;
    pixel_format?: string;
    capture_fps?: number;
  };
}

export interface SaveCameraConfigResult {
  ok: boolean;
  validationSkipped: boolean;  // true when backend set X-Validation-Skipped
}

export async function saveCameraConfig(args: SaveCameraConfigArgs): Promise<SaveCameraConfigResult> {
  // We need access to the response headers, so do a manual fetch instead of
  // routing through apiFetch (which only returns the parsed JSON body).
  const res = await fetch(`/api/settings/configs/cameras/${args.name}`, {
    method: "PUT",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: args.content }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(typeof body.detail === "string" ? body.detail : res.statusText);
  }
  return {
    ok: true,
    validationSkipped: res.headers.get("X-Validation-Skipped") === "device-busy",
  };
}
```

- [ ] **Step 2: Run typecheck**

Run from `/home/tirobot/MimicRec/frontend`: `pnpm exec tsc --noEmit`

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/cameras.ts
git commit -m "$(cat <<'EOF'
feat(frontend): cameras API client (capabilities + save with validation)

Adds typed wrappers for the new GET /api/settings/devices/cameras/{id}/capabilities
endpoint and a saveCameraConfig helper that surfaces the
X-Validation-Skipped header so the UI can warn when validation was
deferred to session_start.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `CameraConfigForm` component

**Files:**
- Create: `frontend/src/components/CameraConfigForm.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/CameraConfigForm.tsx`:

```tsx
import { useEffect, useMemo, useState } from "react";
import { Button } from "./ui/button";
import {
  fetchCameraCapabilities,
  saveCameraConfig,
  type FormatCaps,
} from "../api/cameras";

interface Props {
  name: string;
  currentContent: Record<string, unknown>;
  onSave: (validationSkipped: boolean) => void;
  onCancel: () => void;
}

const OPENCV_TARGET = "mimicrec.cameras.opencv_camera.OpenCVCamera";

export function CameraConfigForm({ name, currentContent, onSave, onCancel }: Props) {
  const [deviceId, setDeviceId] = useState<number>(
    Number(currentContent.device_id ?? 0),
  );
  const [capabilities, setCapabilities] = useState<FormatCaps[]>([]);
  const [loadingCaps, setLoadingCaps] = useState(false);
  const [capsError, setCapsError] = useState<string | null>(null);

  const [pixelFormat, setPixelFormat] = useState<string>(
    String(currentContent.pixel_format ?? ""),
  );
  const [width, setWidth] = useState<number>(Number(currentContent.width ?? 640));
  const [height, setHeight] = useState<number>(Number(currentContent.height ?? 480));
  const [captureFps, setCaptureFps] = useState<number>(
    Number(currentContent.capture_fps ?? 0),
  );

  const [staleWarning, setStaleWarning] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Fetch capabilities whenever deviceId changes.
  useEffect(() => {
    setLoadingCaps(true);
    setCapsError(null);
    fetchCameraCapabilities(deviceId)
      .then((caps) => {
        setCapabilities(caps);

        if (caps.length === 0) return;

        // Try to keep the current YAML values if they exist in the new caps.
        const formatMatch = caps.find((c) => c.fourcc === pixelFormat);
        const effectiveFormat = formatMatch ?? caps[0];
        const sizeMatch = effectiveFormat.sizes.find(
          (s) => s.width === width && s.height === height,
        );
        const effectiveSize = sizeMatch ?? effectiveFormat.sizes[0];
        const fpsMatch = effectiveSize.fps.includes(captureFps)
          ? captureFps
          : effectiveSize.fps[0];

        const allMatched =
          formatMatch !== undefined &&
          sizeMatch !== undefined &&
          effectiveSize.fps.includes(captureFps);

        if (!allMatched && (pixelFormat || width || height || captureFps)) {
          setStaleWarning(
            `⚠ Saved settings (${pixelFormat || "?"}/${width}x${height}@${captureFps}fps) ` +
              `not in this camera's current capabilities. Defaults selected — verify before saving.`,
          );
        }

        setPixelFormat(effectiveFormat.fourcc);
        setWidth(effectiveSize.width);
        setHeight(effectiveSize.height);
        setCaptureFps(fpsMatch);
      })
      .catch((e) => setCapsError(String(e)))
      .finally(() => setLoadingCaps(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceId]);

  // Cascading dropdown options.
  const currentFormat = useMemo(
    () => capabilities.find((c) => c.fourcc === pixelFormat),
    [capabilities, pixelFormat],
  );
  const sizeOptions = currentFormat?.sizes ?? [];
  const currentSize = useMemo(
    () => sizeOptions.find((s) => s.width === width && s.height === height),
    [sizeOptions, width, height],
  );
  const fpsOptions = currentSize?.fps ?? [];

  const onFormatChange = (newFmt: string) => {
    setPixelFormat(newFmt);
    const fmt = capabilities.find((c) => c.fourcc === newFmt);
    if (fmt && fmt.sizes.length > 0) {
      const first = fmt.sizes[0];
      setWidth(first.width);
      setHeight(first.height);
      setCaptureFps(first.fps[0] ?? 0);
    }
  };

  const onSizeChange = (idx: number) => {
    const s = sizeOptions[idx];
    if (!s) return;
    setWidth(s.width);
    setHeight(s.height);
    setCaptureFps(s.fps[0] ?? 0);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const result = await saveCameraConfig({
        name,
        content: {
          _target_: OPENCV_TARGET,
          name,
          device_id: deviceId,
          width,
          height,
          pixel_format: pixelFormat || undefined,
          capture_fps: captureFps || undefined,
        },
      });
      onSave(result.validationSkipped);
    } catch (e) {
      setSaveError(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold">Edit cameras/{name}</h3>

      {staleWarning && (
        <div className="bg-yellow-50 border border-yellow-200 rounded p-3 text-sm text-yellow-800">
          {staleWarning}
        </div>
      )}
      {capsError && (
        <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-800">
          Failed to load capabilities: {capsError}
        </div>
      )}
      {saveError && (
        <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-800">
          Save failed: {saveError}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <label className="block">
          <span className="text-sm text-gray-600">device_id</span>
          <input
            type="number"
            min={0}
            className="mt-1 w-full border rounded px-2 py-1 font-mono text-sm"
            value={deviceId}
            onChange={(e) => setDeviceId(Number(e.target.value))}
          />
        </label>

        <label className="block">
          <span className="text-sm text-gray-600">pixel_format</span>
          <select
            className="mt-1 w-full border rounded px-2 py-1 text-sm"
            value={pixelFormat}
            onChange={(e) => onFormatChange(e.target.value)}
            disabled={loadingCaps || capabilities.length === 0}
          >
            {capabilities.length === 0 && <option value="">(no formats)</option>}
            {capabilities.map((c) => (
              <option key={c.fourcc} value={c.fourcc}>
                {c.fourcc} — {c.description}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="text-sm text-gray-600">resolution</span>
          <select
            className="mt-1 w-full border rounded px-2 py-1 text-sm"
            value={sizeOptions.findIndex((s) => s.width === width && s.height === height)}
            onChange={(e) => onSizeChange(Number(e.target.value))}
            disabled={loadingCaps || sizeOptions.length === 0}
          >
            {sizeOptions.length === 0 && <option value={-1}>(no sizes)</option>}
            {sizeOptions.map((s, i) => (
              <option key={`${s.width}x${s.height}`} value={i}>
                {s.width} × {s.height}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="text-sm text-gray-600">capture_fps</span>
          <select
            className="mt-1 w-full border rounded px-2 py-1 text-sm"
            value={captureFps}
            onChange={(e) => setCaptureFps(Number(e.target.value))}
            disabled={loadingCaps || fpsOptions.length === 0}
          >
            {fpsOptions.length === 0 && <option value={0}>(no fps)</option>}
            {fpsOptions.map((fps) => (
              <option key={fps} value={fps}>
                {fps} fps
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="flex gap-3 justify-end pt-2">
        <Button variant="outline" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
        <Button onClick={handleSave} disabled={saving || loadingCaps}>
          {saving ? "Saving..." : "Save"}
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Run typecheck**

Run from `/home/tirobot/MimicRec/frontend`: `pnpm exec tsc --noEmit`

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/CameraConfigForm.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): structured CameraConfigForm with cascading dropdowns

Edit-modal-friendly component for OpenCVCamera YAMLs. Cascading
device_id → pixel_format → resolution → capture_fps dropdowns sourced
from the new capabilities endpoint. Initial values are matched
against current capabilities; on mismatch (e.g. camera was swapped
since the YAML was written), a warning banner appears and the form
falls back to the first available combination. Save calls the PUT
endpoint and reflects 409 (validation failed) and the
X-Validation-Skipped header in the UI.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: SettingsPage Edit modal branching

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Wire `CameraConfigForm` into the Edit modal**

In `frontend/src/pages/SettingsPage.tsx`, add the import at the top:

```tsx
import { CameraConfigForm } from "../components/CameraConfigForm";
```

Locate the existing Edit modal block (the JSX starting with `{editingConfig && (` and ending with the matching closing tags). Replace its inner `<div className="bg-white ...">` body with a conditional:

Replace this:
```tsx
      {editingConfig && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-[600px] max-h-[80vh] overflow-auto">
            <h3 className="text-lg font-semibold mb-2">
              Edit {editingConfig.group}/{editingConfig.name}
            </h3>
            <textarea
              className="w-full h-64 font-mono text-sm border rounded p-3 mb-4"
              value={editJson}
              onChange={(e) => setEditJson(e.target.value)}
            />
            <div className="flex gap-3 justify-end">
              <Button variant="outline" onClick={() => setEditingConfig(null)}>
                Cancel
              </Button>
              <Button onClick={handleSaveConfig}>Save</Button>
            </div>
          </div>
        </div>
      )}
```

With:
```tsx
      {editingConfig && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-[600px] max-h-[80vh] overflow-auto">
            {editingConfig.group === "cameras"
              && (editingConfig.content as Record<string, unknown>)._target_
                  === "mimicrec.cameras.opencv_camera.OpenCVCamera" ? (
              <CameraConfigForm
                name={editingConfig.name}
                currentContent={editingConfig.content as Record<string, unknown>}
                onSave={(validationSkipped) => {
                  setEditingConfig(null);
                  if (validationSkipped) {
                    alert(
                      "Saved. Camera was busy so the configured parameters " +
                        "will be validated when the next session starts.",
                    );
                  }
                  loadConfigs();
                }}
                onCancel={() => setEditingConfig(null)}
              />
            ) : (
              <>
                <h3 className="text-lg font-semibold mb-2">
                  Edit {editingConfig.group}/{editingConfig.name}
                </h3>
                <textarea
                  className="w-full h-64 font-mono text-sm border rounded p-3 mb-4"
                  value={editJson}
                  onChange={(e) => setEditJson(e.target.value)}
                />
                <div className="flex gap-3 justify-end">
                  <Button variant="outline" onClick={() => setEditingConfig(null)}>
                    Cancel
                  </Button>
                  <Button onClick={handleSaveConfig}>Save</Button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
```

The textarea path is preserved verbatim for non-camera configs and for non-OpenCVCamera adapters (MockCamera, SimCamera).

- [ ] **Step 2: Run typecheck**

Run from `/home/tirobot/MimicRec/frontend`: `pnpm exec tsc --noEmit`

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): branch SettingsPage Edit modal on camera _target_

For OpenCVCamera YAMLs the modal now renders the structured
CameraConfigForm (capability-driven dropdowns + save with validation).
All other configs — robot, teleop, mapper, MockCamera, SimCamera —
keep the existing JSON textarea editor unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Manual hardware verification

**Files:** N/A (verification only).

- [ ] **Step 1: Start backend and frontend dev servers**

Backend (one terminal):
```bash
uvicorn mimicrec.api.app:app --reload
```

Frontend (another terminal):
```bash
cd frontend && pnpm dev
```

- [ ] **Step 2: Verify capabilities endpoint by curl**

```bash
curl -s http://127.0.0.1:8000/api/settings/devices/cameras/0/capabilities | python3 -m json.tool | head -40
```

Expected: JSON list of formats × sizes × fps reflecting your real camera's `v4l2-ctl --list-formats-ext` output.

- [ ] **Step 3: Verify Edit modal — happy path**

1. Browse to `http://localhost:5173/settings`
2. In Configurations → cameras, click Edit on `wrist`
3. Modal shows the structured form (not textarea). Dropdowns populated from /dev/video0 capabilities
4. Pick MJPG / 1280×720 / 30 fps
5. Click Save — modal closes, no error

- [ ] **Step 4: Verify YAML persistence**

```bash
cat configs/cameras/wrist.yaml
```

Expected: file contains the new `pixel_format: MJPG` and `capture_fps: 30` plus the new resolution.

- [ ] **Step 5: Verify mismatch path — 409**

Manually edit `configs/cameras/wrist.yaml` and set an impossible combination (e.g. set `width: 9999` directly). Then in the UI hit Save with valid values — confirm the YAML reverts to the saved valid values when the server validates and writes. Alternatively, modify the form, then patch the backend code temporarily to force `actual_w != width`, save, expect a 409 visible in the modal as `Save failed: validation failed: ...`. (This is a smoke test — the unit tests prove the path.)

- [ ] **Step 6: Verify session start with new YAML**

Start a session via the Record page using the updated camera. Confirm:
- Session starts cleanly (no RuntimeError)
- Recorded mp4 has the chosen resolution (`ffprobe datasets/<ds>/videos/observation.images.wrist/.../episode_000000.mp4` shows the new size)
- `cat datasets/<ds>/meta/info.json` — `observation.images.wrist.shape` and `video.height/width` reflect the new resolution

- [ ] **Step 7: Verify strict-fail path**

Manually edit `configs/cameras/wrist.yaml` to use a combination v4l2-ctl never reports (e.g. `pixel_format: H264` if the camera doesn't list it). Start a session — confirm the session_start request fails with a clear error (camera startup failed: ... cv2 negotiated different parameters: ...).

Restore the YAML to a working state.

- [ ] **Step 8: Verify MockCamera config still uses textarea**

Click Edit on `mock_cam` — confirm the JSON textarea modal appears (not the structured form).

- [ ] **Step 9: Cleanup project memory**

After confirming the info.json fix works, remove the now-stale memory entry:

1. Delete `~/.claude/projects/-home-tirobot-MimicRec/memory/bug_info_json_resolution_hardcoded.md`
2. Edit `~/.claude/projects/-home-tirobot-MimicRec/memory/MEMORY.md` and remove the `info.json 解像度ハードコードバグ` line.

(These files live outside the repo so no git commit is needed.)

---

## Self-Review Checklist

- [x] **Spec coverage:**
  - Goal §1 (capability dropdown selection + persist) → Tasks 1, 6, 7, 8, 9, 10
  - Goal §2 (strict cv2 readback or RuntimeError) → Tasks 4, 5, 7
  - Goal §3 (info.json hardcode fix) → Tasks 2, 3
  - Non-goal items left out: confirmed (no exposure/gain controls, no hotplug, no multi-plane, no stepwise sizes — all explicit `# skip` in parser/spec)
  - Architecture / Components / Data flow → mapped 1:1 onto Tasks
  - Error handling table — all rows covered:
    - v4l2-ctl missing → Task 1 test + Task 6 endpoint behavior
    - device missing → Task 6 404
    - mismatch on Save → Task 7 409
    - busy on Save → Task 7 X-Validation-Skipped
    - mismatch on session_start → Tasks 4 + 5
    - YAML lacking new fields → Task 4 (None comparison skip)
  - Decision log items reflected as commit messages
- [x] **Placeholder scan:** all code blocks complete; no TBD; all paths absolute or repo-relative; commit messages spelled out
- [x] **Type consistency:** `FormatCaps` / `FrameSize` (parser dataclasses) match the TS interfaces in Task 8; `_decode_fourcc` defined once in Task 4 and reused via inline-equivalent in Task 7's PUT validator (chosen to avoid coupling the route module to the camera module's helper); `OPENCV_TARGET` constant in Task 9 matches the `_target_` string in Task 10's branch condition
