# Session Preview Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a session-start `preview_enabled` toggle that disables the JPEG fan-out for OpenCV cameras and skips the GoPro UDP preview pipeline entirely, without affecting recording. Default is `True` (no behavior change for existing clients).

**Architecture:** A single boolean flag on `_BaseSessionRequest` flows through `deps.create_session_from_request` into both `CameraManager` (gates the JPEG encode + WS fan-out branch of `_run_camera`) and `GoProDeviceRegistry` (skips `GoProPreviewSource` instantiation so the device-side `set_preview_stream` is never invoked). A new `PreviewDisabledError` lets `/ws/cameras/{name}` close with a distinct reason so the frontend can render a placeholder instead of reconnecting. The flag is echoed in REST `/api/session/state` and the WS `session_state` payload.

**Tech Stack:** Python 3.12 (FastAPI / asyncio / pydantic), pytest with `asyncio_mode=auto`, React 19 / TypeScript / Zustand / Vite.

**Spec:** `docs/superpowers/specs/2026-05-10-session-preview-toggle-design.md`

**Test runner (backend):** `env -u PYTHONPATH /home/tirobot/MimicRec/backend/.venv/bin/python -m pytest ../tests/...` from `backend/` cwd.

**Type-check (frontend):** `npm --prefix frontend run build` (`tsc && vite build`).

---

## File Structure

**New files:**

| Path | Responsibility |
|---|---|
| `tests/unit/test_preview_disabled_error.py` | `PreviewDisabledError` is a `MimicRecError` subclass. |
| `tests/unit/test_camera_manager_preview_toggle.py` | `CameraManager(preview_enabled=False)` skips JPEG fan-out + raises on subscribe; `latest()` still populated. |
| `tests/unit/gopro/test_registry_preview_toggle.py` | `GoProDeviceRegistry(preview_enabled=False)` produces empty `preview_sources()` while `gopro_specs()` is unchanged. |
| `tests/unit/test_schemas_preview_enabled.py` | `_BaseSessionRequest.preview_enabled` default + override + bool validation. |
| `tests/integration/test_session_preview_toggle.py` | End-to-end: start session with `preview_enabled=False`, REST + WS state echo it, `/ws/cameras/{name}` closes 1008. |

**Modified files:**

| Path | Change |
|---|---|
| `backend/mimicrec/errors.py` | Add `PreviewDisabledError(MimicRecError)`. |
| `backend/mimicrec/cameras/manager.py` | `__init__(..., preview_enabled: bool = True)`; gate JPEG encode + fan-out in `_run_camera`; `subscribe_preview` raises `PreviewDisabledError` when disabled. |
| `backend/mimicrec/gopro/registry.py` | `__init__(..., preview_enabled: bool = True)`; `start()` skips `GoProPreviewSource` construction when disabled. |
| `backend/mimicrec/api/schemas.py` | `_BaseSessionRequest.preview_enabled: bool = True`; `SessionStatePayload.preview_enabled: bool = True`. |
| `backend/mimicrec/api/deps.py` | Pass `req.preview_enabled` into `CameraManager` and `GoProDeviceRegistry`; persist into `session_meta`. |
| `backend/mimicrec/api/ws/camera_hub.py` | Catch `PreviewDisabledError` from `subscribe_preview` and close `code=1008, reason="preview disabled this session"`. |
| `backend/mimicrec/api/ws/session_hub.py` | Include `preview_enabled` in `_build_ws_state`. |
| `backend/mimicrec/api/routes/session.py` | Include `preview_enabled` in `build_state_payload`. |
| `frontend/src/state/record-form-store.ts` | Add `previewEnabled: boolean` (default `true`) to `RecordFormDraft` + `DEFAULTS`. |
| `frontend/src/state/session-store.ts` | Add `previewEnabled: boolean` to store + hydrate from `data.preview_enabled`. |
| `frontend/src/components/SessionConfigForm.tsx` | Add checkbox; include `preview_enabled` in `handleStart` body. |
| `frontend/src/pages/RecordPage.tsx` | When `previewEnabled === false`, render placeholder instead of `<CameraPreview>` tiles. |

---

## Task 1: Add `PreviewDisabledError`

**Files:**
- Modify: `backend/mimicrec/errors.py`
- Test: `tests/unit/test_preview_disabled_error.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_preview_disabled_error.py`:

```python
from mimicrec.errors import MimicRecError, PreviewDisabledError


def test_preview_disabled_error_is_mimicrec_error_subclass():
    err = PreviewDisabledError("preview disabled this session")
    assert isinstance(err, MimicRecError)
    assert str(err) == "preview disabled this session"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/tirobot/MimicRec/backend && env -u PYTHONPATH ./.venv/bin/python -m pytest ../tests/unit/test_preview_disabled_error.py -v
```

Expected: FAIL with `ImportError: cannot import name 'PreviewDisabledError'`.

- [ ] **Step 3: Implement**

Append to `backend/mimicrec/errors.py`:

```python
class PreviewDisabledError(MimicRecError):
    """Raised by CameraManager.subscribe_preview when the session was
    started with preview_enabled=False. The WS layer maps this to a 1008
    close with reason 'preview disabled this session' so clients can
    distinguish 'preview off by design' from 'no such camera'."""
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/tirobot/MimicRec/backend && env -u PYTHONPATH ./.venv/bin/python -m pytest ../tests/unit/test_preview_disabled_error.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/errors.py tests/unit/test_preview_disabled_error.py
git commit -m "feat(errors): add PreviewDisabledError for session-level preview toggle"
```

---

## Task 2: `CameraManager` honors `preview_enabled`

**Files:**
- Modify: `backend/mimicrec/cameras/manager.py`
- Test: `tests/unit/test_camera_manager_preview_toggle.py`

The fan-out block at `manager.py:88-97` must be gated. `cam.read()` and `LatestValue.set` must keep running so recording, FK, and replay-safety remain unaffected.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_camera_manager_preview_toggle.py`:

```python
import asyncio
import pytest

from mimicrec.cameras.manager import CameraManager
from mimicrec.cameras.mock_camera import MockCamera
from mimicrec.errors import PreviewDisabledError
from mimicrec.util.error_bus import ErrorBus


async def test_subscribe_preview_raises_when_disabled():
    cm = CameraManager(
        cameras={"front": MockCamera("front")},
        error_bus=ErrorBus(),
        preview_enabled=False,
    )
    with pytest.raises(PreviewDisabledError):
        cm.subscribe_preview("front")


async def test_disabled_preview_skips_jpeg_fanout_but_keeps_latest():
    cm = CameraManager(
        cameras={"front": MockCamera("front")},
        error_bus=ErrorBus(),
        preview_enabled=False,
    )

    encode_calls = 0
    import mimicrec.cameras.manager as mgr_mod
    real_encode = mgr_mod.encode_jpeg

    def spy_encode(img):
        nonlocal encode_calls
        encode_calls += 1
        return real_encode(img)

    mgr_mod.encode_jpeg = spy_encode  # type: ignore[assignment]
    try:
        await cm.start()
        # Wait for the read loop to populate latest at least once.
        for _ in range(20):
            if cm.latest("front").peek() is not None:
                break
            await asyncio.sleep(0.05)
        assert cm.latest("front").peek() is not None, "read loop must still populate latest"
        assert encode_calls == 0, "encode_jpeg must not be called when preview disabled"
    finally:
        mgr_mod.encode_jpeg = real_encode  # type: ignore[assignment]
        await cm.stop()


async def test_default_preview_enabled_is_true():
    cm = CameraManager(
        cameras={"front": MockCamera("front")},
        error_bus=ErrorBus(),
    )
    # Default-on path: subscribe_preview must work and return a queue.
    q = cm.subscribe_preview("front")
    assert isinstance(q, asyncio.Queue)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/tirobot/MimicRec/backend && env -u PYTHONPATH ./.venv/bin/python -m pytest ../tests/unit/test_camera_manager_preview_toggle.py -v
```

Expected: FAIL — `CameraManager.__init__()` does not accept `preview_enabled`.

- [ ] **Step 3: Implement**

Edit `backend/mimicrec/cameras/manager.py`. Update the import line for errors:

```python
from mimicrec.errors import HardwareError, PreviewDisabledError
```

Update `__init__` (replace existing body):

```python
def __init__(
    self,
    cameras: Mapping[str, object],
    error_bus: ErrorBus,
    preview_enabled: bool = True,
) -> None:
    self._cameras = dict(cameras)
    self._errors = error_bus
    self._latest: dict[str, LatestValue[Frame]] = {n: LatestValue() for n in cameras}
    self._preview_subs: dict[str, list[asyncio.Queue]] = {n: [] for n in cameras}
    self._tasks: list[asyncio.Task] = []
    self._stopped = asyncio.Event()
    self._preview_enabled = preview_enabled
```

Update `subscribe_preview`:

```python
def subscribe_preview(self, name: str, maxsize: int = 2) -> asyncio.Queue:
    if not self._preview_enabled:
        raise PreviewDisabledError(
            f"preview is disabled for this session (camera '{name}')"
        )
    q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
    self._preview_subs[name].append(q)
    return q
```

Update `_run_camera` so the JPEG fan-out only runs when previews are enabled. Replace the existing tail of the loop body (currently `manager.py:88-97`):

```python
        async def _run_camera(self, name: str, cam) -> None:
            while not self._stopped.is_set():
                try:
                    frame = await cam.read()
                except Exception as e:
                    await self._errors.publish(HardwareError(f"camera {name}: {e}"))
                    await asyncio.sleep(0.05)
                    continue
                stamped_ns = time.monotonic_ns()
                frame.t_mono_ns = stamped_ns
                self._latest[name].set(frame, t_mono_ns=stamped_ns)
                if not self._preview_enabled:
                    continue
                jpg: bytes | None = None
                for q in list(self._preview_subs[name]):
                    if q.full():
                        continue
                    if jpg is None:
                        jpg = encode_jpeg(downscale(frame.image))
                    try:
                        q.put_nowait(jpg)
                    except asyncio.QueueFull:
                        pass
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/tirobot/MimicRec/backend && env -u PYTHONPATH ./.venv/bin/python -m pytest ../tests/unit/test_camera_manager_preview_toggle.py ../tests/unit/test_camera_manager.py -v
```

Expected: all PASS (existing camera_manager tests still green — they exercise the default `preview_enabled=True` path).

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/cameras/manager.py tests/unit/test_camera_manager_preview_toggle.py
git commit -m "feat(cameras): CameraManager preview_enabled flag gates WS fan-out"
```

---

## Task 3: `GoProDeviceRegistry` honors `preview_enabled`

**Files:**
- Modify: `backend/mimicrec/gopro/registry.py`
- Test: `tests/unit/gopro/test_registry_preview_toggle.py`

When `preview_enabled=False`, `_previews` stays empty; `preview_sources()` returns `{}`; `gopro_specs()` is unchanged so `init_dataset` still gets the GoPro features schema.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/gopro/test_registry_preview_toggle.py`:

```python
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


@pytest.mark.asyncio
async def test_registry_preview_disabled_yields_empty_sources(paths):
    a = MockGoProDevice(name="g1", usb_serial="S1")
    reg = GoProDeviceRegistry(
        devices=[a], paths=paths, errors=ErrorBus(), preview_enabled=False,
    )
    await reg.start()
    try:
        assert reg.preview_sources() == {}, "no preview sources when disabled"
        assert "g1" in reg.gopro_specs(), "gopro_specs unchanged so info.json schema works"
    finally:
        await reg.stop()


@pytest.mark.asyncio
async def test_registry_preview_disabled_does_not_call_start_preview(paths):
    a = MockGoProDevice(name="g1", usb_serial="S1")
    calls: list[int] = []
    real_start = a.start_preview

    async def spy_start(port: int) -> None:
        calls.append(port)
        await real_start(port)

    a.start_preview = spy_start  # type: ignore[assignment]

    reg = GoProDeviceRegistry(
        devices=[a], paths=paths, errors=ErrorBus(), preview_enabled=False,
    )
    await reg.start()
    try:
        assert calls == [], "start_preview must not be invoked when preview disabled"
    finally:
        await reg.stop()


@pytest.mark.asyncio
async def test_registry_default_preview_enabled_is_true(paths):
    """Existing behavior: preview_enabled defaults to True and sources are populated."""
    a = MockGoProDevice(name="g1", usb_serial="S1")
    reg = GoProDeviceRegistry(devices=[a], paths=paths, errors=ErrorBus())
    await reg.start()
    try:
        assert "g1" in reg.preview_sources()
    finally:
        await reg.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/tirobot/MimicRec/backend && env -u PYTHONPATH ./.venv/bin/python -m pytest ../tests/unit/gopro/test_registry_preview_toggle.py -v
```

Expected: FAIL — `GoProDeviceRegistry.__init__()` does not accept `preview_enabled`.

- [ ] **Step 3: Implement**

Edit `backend/mimicrec/gopro/registry.py`. Update `__init__`:

```python
def __init__(
    self,
    devices: list,
    paths: DatasetPaths,
    errors: ErrorBus,
    preview_enabled: bool = True,
) -> None:
    names = [d.name for d in devices]
    serials = [d.usb_serial for d in devices]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate name in GoPro devices: {names}")
    if len(set(serials)) != len(serials):
        raise ValueError(f"duplicate usb_serial in GoPro devices: {serials}")
    self._devices = devices
    self._paths = paths
    self._errors = errors
    self._preview_enabled = preview_enabled
    self._queue: DLQueue | None = None
    self._worker: GoProDLWorker | None = None
    self._worker_task: asyncio.Task | None = None
    self._recorders: dict[str, GoProRecorder] = {}
    self._previews: dict[str, GoProPreviewSource] = {}
```

Update the recorder + preview construction loop in `start()` (currently `registry.py:57-64`):

```python
        # 2. Restore queue, build recorders + (optionally) preview sources.
        self._queue = DLQueue.restore(self._paths.pending_dir / "gopro_dl")
        for d in self._devices:
            self._recorders[d.name] = GoProRecorder(d, self._queue, self._paths, self._errors)
            if self._preview_enabled:
                # The device knows which UDP port the camera will actually
                # emit to: HERO9–11 firmware ignores the port arg and forces
                # 8554, so the device must claim it via udp_preview_port and
                # the preview source binds the same.
                self._previews[d.name] = GoProPreviewSource(d, udp_port=d.udp_preview_port)
```

`stop()`'s `for src in self._previews.values()` loop already handles the empty-dict case correctly.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/tirobot/MimicRec/backend && env -u PYTHONPATH ./.venv/bin/python -m pytest ../tests/unit/gopro/test_registry_preview_toggle.py ../tests/unit/gopro/test_registry.py -v
```

Expected: all PASS — including existing registry tests (they don't pass `preview_enabled` and the default keeps them on the previous path).

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/gopro/registry.py tests/unit/gopro/test_registry_preview_toggle.py
git commit -m "feat(gopro): GoProDeviceRegistry preview_enabled flag skips preview source creation"
```

---

## Task 4: Schemas — `preview_enabled` on session request + state payload

**Files:**
- Modify: `backend/mimicrec/api/schemas.py`
- Test: `tests/unit/test_schemas_preview_enabled.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_schemas_preview_enabled.py`:

```python
import pytest
from pydantic import ValidationError

from mimicrec.api.schemas import (
    HandTeachSessionRequest,
    SessionStatePayload,
    TeleopSessionRequest,
)


def _teleop_kwargs(**extra):
    base = dict(
        dataset="ds", task="t", robot="r", cameras=["c"],
        teleop="tl", mapper="mp",
    )
    base.update(extra)
    return base


def test_teleop_request_preview_enabled_defaults_true():
    req = TeleopSessionRequest(**_teleop_kwargs())
    assert req.preview_enabled is True


def test_teleop_request_accepts_preview_enabled_false():
    req = TeleopSessionRequest(**_teleop_kwargs(preview_enabled=False))
    assert req.preview_enabled is False


def test_handteach_request_inherits_preview_enabled_default():
    req = HandTeachSessionRequest(
        dataset="ds", task="t", robot="r", cameras=["c"],
    )
    assert req.preview_enabled is True


def test_request_rejects_non_bool_preview_enabled():
    with pytest.raises(ValidationError):
        TeleopSessionRequest(**_teleop_kwargs(preview_enabled="yes"))


def test_state_payload_preview_enabled_defaults_true():
    p = SessionStatePayload(state="idle")
    assert p.preview_enabled is True


def test_state_payload_round_trips_preview_enabled_false():
    p = SessionStatePayload(state="ready", preview_enabled=False)
    dumped = p.model_dump()
    assert dumped["preview_enabled"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/tirobot/MimicRec/backend && env -u PYTHONPATH ./.venv/bin/python -m pytest ../tests/unit/test_schemas_preview_enabled.py -v
```

Expected: FAIL — `preview_enabled` field does not exist.

- [ ] **Step 3: Implement**

Edit `backend/mimicrec/api/schemas.py`. Inside `_BaseSessionRequest`, add the field after `gopros` (the existing tail of the class body):

```python
class _BaseSessionRequest(BaseModel):
    dataset: str
    task: str
    robot: str
    cameras: list[str]
    fps: int = 30
    gopros: list[str] = Field(default_factory=list)
    preview_enabled: bool = True
```

Inside `SessionStatePayload`, add the field after `gopros`:

```python
class SessionStatePayload(BaseModel):
    state: str
    sub_state: str | None = None
    mode: str | None = None
    dataset: str | None = None
    task: str | None = None
    robot: str | None = None
    teleop: str | None = None
    mapper: str | None = None
    cameras: list[str] = []
    fps: int | None = None
    gopros: list[str] = Field(default_factory=list)
    preview_enabled: bool = True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/tirobot/MimicRec/backend && env -u PYTHONPATH ./.venv/bin/python -m pytest ../tests/unit/test_schemas_preview_enabled.py ../tests/unit/gopro/test_schemas_gopros.py -v
```

Expected: PASS for all (existing schema tests must still pass).

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/api/schemas.py tests/unit/test_schemas_preview_enabled.py
git commit -m "feat(api): preview_enabled on session request and state payload"
```

---

## Task 5: `deps.py` wires the flag through

**Files:**
- Modify: `backend/mimicrec/api/deps.py`

The existing tests in Task 8 (integration) will exercise the wire-up end to end; this task is plumbing.

- [ ] **Step 1: Update CameraManager construction**

Find this line (currently `deps.py:158`):

```python
    cm = CameraManager(cameras=cams, error_bus=error_bus)
```

Replace with:

```python
    cm = CameraManager(
        cameras=cams,
        error_bus=error_bus,
        preview_enabled=req.preview_enabled,
    )
```

- [ ] **Step 2: Update GoProDeviceRegistry construction**

Find this block (currently `deps.py:147-149`):

```python
            gopro_registry = GoProDeviceRegistry(
                devices=gopro_devices, paths=_paths, errors=error_bus,
            )
```

Replace with:

```python
            gopro_registry = GoProDeviceRegistry(
                devices=gopro_devices, paths=_paths, errors=error_bus,
                preview_enabled=req.preview_enabled,
            )
```

- [ ] **Step 3: Persist into session_meta**

Find the `session_meta` dict (currently `deps.py:301-310`):

```python
    app.state.session_meta = {
        "dataset": req.dataset,
        "task": req.task,
        "robot": req.robot,
        "teleop": teleop_name,
        "mapper": mapper_name,
        "cameras": list(req.cameras),
        "gopros": list(getattr(req, "gopros", [])),
        "fps": req.fps,
    }
```

Add the `preview_enabled` key:

```python
    app.state.session_meta = {
        "dataset": req.dataset,
        "task": req.task,
        "robot": req.robot,
        "teleop": teleop_name,
        "mapper": mapper_name,
        "cameras": list(req.cameras),
        "gopros": list(getattr(req, "gopros", [])),
        "fps": req.fps,
        "preview_enabled": bool(req.preview_enabled),
    }
```

- [ ] **Step 4: Smoke check**

```bash
cd /home/tirobot/MimicRec/backend && env -u PYTHONPATH ./.venv/bin/python -m pytest ../tests/integration/test_session_lifecycle_mock.py ../tests/integration/test_gopro_session_bootstrap.py ../tests/integration/test_gopro_mock_session.py -v
```

Expected: all PASS (these are the existing integration tests that touch `deps.py` — `preview_enabled` defaults to True and behavior is unchanged).

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/api/deps.py
git commit -m "feat(api): deps wires preview_enabled into managers and session_meta"
```

---

## Task 6: WS `/ws/cameras/{name}` closes 1008 when disabled

**Files:**
- Modify: `backend/mimicrec/api/ws/camera_hub.py`

Existing line that calls `subscribe_preview` (`camera_hub.py:16`) only catches `KeyError` (unknown camera). We add a `PreviewDisabledError` branch with a distinct close reason.

- [ ] **Step 1: Edit `camera_hub.py`**

Replace the body of `ws_camera`:

```python
from __future__ import annotations
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from mimicrec.errors import PreviewDisabledError

router = APIRouter()


@router.websocket("/ws/cameras/{cam_name}")
async def ws_camera(websocket: WebSocket, cam_name: str):
    await websocket.accept()
    cm = getattr(websocket.app.state, "camera_manager", None)
    if not cm:
        await websocket.close(code=1008, reason="no active session")
        return
    try:
        q = cm.subscribe_preview(cam_name)
    except PreviewDisabledError:
        await websocket.close(code=1008, reason="preview disabled this session")
        return
    except KeyError:
        await websocket.close(code=1008, reason=f"camera '{cam_name}' not found")
        return
    try:
        while True:
            try:
                jpg = await asyncio.wait_for(q.get(), timeout=1.0)
                await websocket.send_bytes(jpg)
            except asyncio.TimeoutError:
                # Check if client disconnected
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
                except asyncio.TimeoutError:
                    continue
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
```

- [ ] **Step 2: Verify ASGI test client behavior is unchanged for default-on**

```bash
cd /home/tirobot/MimicRec/backend && env -u PYTHONPATH ./.venv/bin/python -m pytest ../tests/integration/test_session_lifecycle_mock.py -v
```

Expected: PASS — no test there hits this WS, but importing the module should still succeed (sanity).

- [ ] **Step 3: Commit**

```bash
git add backend/mimicrec/api/ws/camera_hub.py
git commit -m "feat(ws): camera_hub closes with 'preview disabled this session' reason"
```

---

## Task 7: Surface `preview_enabled` in REST and WS state payloads

**Files:**
- Modify: `backend/mimicrec/api/routes/session.py`
- Modify: `backend/mimicrec/api/ws/session_hub.py`

- [ ] **Step 1: Update REST payload builder**

Edit `backend/mimicrec/api/routes/session.py`. Inside `build_state_payload`, the non-idle branch currently constructs `SessionStatePayload(...)`. Add the `preview_enabled` argument right after `gopros`:

```python
    return SessionStatePayload(
        state=sm.session.state.value,
        sub_state=sm.session.sub_state.value if sm.session.sub_state else None,
        mode=sm.session.mode.value if sm.session.mode else None,
        dataset=meta.get("dataset"),
        task=meta.get("task"),
        robot=meta.get("robot"),
        teleop=meta.get("teleop"),
        mapper=meta.get("mapper"),
        cameras=meta.get("cameras", []),
        fps=meta.get("fps"),
        gopros=meta.get("gopros", []),
        preview_enabled=meta.get("preview_enabled", True),
    ).model_dump()
```

- [ ] **Step 2: Update WS state builder**

Edit `backend/mimicrec/api/ws/session_hub.py`. In `_build_ws_state`, the non-idle return dict currently ends with `"gopros": meta.get("gopros", []), "fps": meta.get("fps")`. Add `preview_enabled`:

```python
    return {
        "state": sm.session.state.value,
        "sub_state": sm.session.sub_state.value if sm.session.sub_state else None,
        "mode": sm.session.mode.value if sm.session.mode else None,
        "dataset": meta.get("dataset"),
        "task": meta.get("task"),
        "robot": meta.get("robot"),
        "teleop": meta.get("teleop"),
        "mapper": meta.get("mapper"),
        "cameras": meta.get("cameras", []),
        # Must mirror REST /api/session/state. The frontend session-store
        # overwrites `gopros` from every WS push, so omitting this key
        # silently unmounts every GoPro CameraPreview tile within 200ms
        # of session start.
        "gopros": meta.get("gopros", []),
        "fps": meta.get("fps"),
        "preview_enabled": meta.get("preview_enabled", True),
    }
```

- [ ] **Step 3: Smoke check**

```bash
cd /home/tirobot/MimicRec/backend && env -u PYTHONPATH ./.venv/bin/python -m pytest ../tests/integration/test_session_lifecycle_mock.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/mimicrec/api/routes/session.py backend/mimicrec/api/ws/session_hub.py
git commit -m "feat(api): emit preview_enabled in REST and WS session_state payloads"
```

---

## Task 8: Integration test — preview_enabled=False end-to-end

**Files:**
- Test: `tests/integration/test_session_preview_toggle.py`

Use the existing FastAPI test-client pattern from `test_session_lifecycle_mock.py`. The test starts a session with `preview_enabled=False`, asserts both REST and WS state echo the flag, and confirms `/ws/cameras/{name}` closes 1008.

- [ ] **Step 1: Locate existing test app fixture**

Read `tests/integration/test_session_lifecycle_mock.py` (the first ~40 lines) to mirror its app/client setup. The fixture pattern uses `fastapi.testclient.TestClient` against `mimicrec.api.app:create_app()`. Match that pattern exactly so the test runs in the same harness.

- [ ] **Step 2: Write the failing test**

Create `tests/integration/test_session_preview_toggle.py`:

```python
"""End-to-end test for the session-level preview_enabled toggle.

The toggle must:
1. Round-trip through REST `/api/session/state` payload.
2. Round-trip through WS `/ws/session` initial snapshot.
3. Cause `/ws/cameras/{name}` to close with code 1008 + reason
   "preview disabled this session".
"""
from __future__ import annotations
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicrec.api.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    # Mirror the env layout used by test_session_lifecycle_mock.py: configs
    # come from the repo's `configs/` and datasets are written under tmp_path
    # so each test gets an isolated dataset root.
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("MIMICREC_CONFIGS_ROOT", str(repo_root / "configs"))
    monkeypatch.setenv("MIMICREC_DATASETS_ROOT", str(tmp_path / "datasets"))
    app = create_app()
    with TestClient(app) as c:
        yield c


def _start_body(preview_enabled: bool) -> dict:
    # Config names match files in repo `configs/`:
    #   configs/robot/mock.yaml         → MockRobotAdapter
    #   configs/cameras/mock_cam.yaml   → MockCamera
    return {
        "mode": "hand_teach",
        "dataset": "preview_toggle_test",
        "task": "default",
        "robot": "mock",
        "cameras": ["mock_cam"],
        "fps": 30,
        "preview_enabled": preview_enabled,
    }


def test_rest_state_echoes_preview_enabled_false(client: TestClient):
    r = client.post("/api/session/start", json=_start_body(False))
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["preview_enabled"] is False
    state2 = client.get("/api/session/state").json()
    assert state2["preview_enabled"] is False
    client.post("/api/session/end")


def test_rest_state_default_preview_enabled_is_true(client: TestClient):
    body = _start_body(True)
    body.pop("preview_enabled")  # omit field entirely
    r = client.post("/api/session/start", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["preview_enabled"] is True
    client.post("/api/session/end")


def test_ws_session_initial_snapshot_carries_preview_enabled_false(client: TestClient):
    client.post("/api/session/start", json=_start_body(False))
    try:
        with client.websocket_connect("/ws/session") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "session_state"
            assert msg["data"]["preview_enabled"] is False
    finally:
        client.post("/api/session/end")


def test_ws_camera_closes_1008_when_preview_disabled(client: TestClient):
    client.post("/api/session/start", json=_start_body(False))
    try:
        with pytest.raises(Exception) as excinfo:
            with client.websocket_connect("/ws/cameras/mock_cam"):
                pass
        # starlette's WebSocketDisconnect carries .code on the exception;
        # match either the attribute or the string form of the close code.
        msg = str(excinfo.value)
        assert "1008" in msg or "preview disabled" in msg
    finally:
        client.post("/api/session/end")
```

> **Note:** if `mock` / `mock_cam` are missing on a future host, list `configs/robot/` and `configs/cameras/` and substitute any working mock pair (typically `mock` + one of `mock_cam`/`mock_front`/`mock_wrist`). The integration test does not require any specific mock — only that the names resolve to existing yaml files.

- [ ] **Step 3: Run the test, fix config names if needed**

```bash
cd /home/tirobot/MimicRec/backend && env -u PYTHONPATH ./.venv/bin/python -m pytest ../tests/integration/test_session_preview_toggle.py -v
```

If a 400 comes back from `/api/session/start` because of a missing config name, open `tests/integration/test_session_lifecycle_mock.py` and copy its working `robot`/`cameras` fixture names into `_start_body`. Re-run.

Expected (after any name fix): all four tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_session_preview_toggle.py
git commit -m "test(integration): preview_enabled=False round-trips REST/WS and closes camera WS"
```

---

## Task 9: Frontend stores hold `previewEnabled`

**Files:**
- Modify: `frontend/src/state/record-form-store.ts`
- Modify: `frontend/src/state/session-store.ts`

- [ ] **Step 1: Add `previewEnabled` to `RecordFormDraft`**

Edit `frontend/src/state/record-form-store.ts`. Add the field to the interface and DEFAULTS:

```typescript
export interface RecordFormDraft {
  mode: "teleop" | "hand_teach";
  robot: string;
  teleop: string;
  mapper: string;
  selectedCams: string[];
  selectedGopros: string[];
  dataset: string;
  task: string;
  fps: number;
  autoCycle: boolean;
  autoDurationSec: number;
  autoReviewSec: number;
  previewEnabled: boolean;
}
```

```typescript
const DEFAULTS: RecordFormDraft = {
  mode: "teleop",
  robot: "",
  teleop: "",
  mapper: "",
  selectedCams: [],
  selectedGopros: [],
  dataset: "",
  task: "",
  fps: 30,
  autoCycle: false,
  autoDurationSec: 10,
  autoReviewSec: 3,
  previewEnabled: true,
};
```

- [ ] **Step 2: Add `previewEnabled` to session-store**

Edit `frontend/src/state/session-store.ts`. Update the interface, the initial value, and `setSessionState`:

```typescript
interface SessionStore {
  state: "idle" | "ready" | "recording" | "review";
  subState: string | null;
  mode: string | null;
  dataset: string | null;
  task: string | null;
  robot: string | null;
  teleop: string | null;
  mapper: string | null;
  cameras: string[];
  gopros: string[];
  fps: number | null;
  previewEnabled: boolean;
  episodeProgress: EpisodeProgress | null;
  replayProgress: ReplayProgress | null;
  lastError: { error: string; message: string } | null;
  setSessionState: (data: Record<string, unknown>) => void;
  setEpisodeProgress: (data: EpisodeProgress) => void;
  setReplayProgress: (data: ReplayProgress) => void;
  setError: (data: { error: string; message: string }) => void;
  clearError: () => void;
}
```

In the `create<SessionStore>(...)` body, add `previewEnabled: true` to the initial state object (next to `fps: null`), and inside `setSessionState`, add the hydration line at the bottom of the `set({...})` block (next to `fps`):

```typescript
  setSessionState: (data) =>
    set({
      state: (data.state as SessionStore["state"]) ?? "idle",
      subState: (data.sub_state as string) ?? null,
      mode: (data.mode as string) ?? null,
      dataset: (data.dataset as string) ?? null,
      task: (data.task as string) ?? null,
      robot: (data.robot as string) ?? null,
      teleop: (data.teleop as string) ?? null,
      mapper: (data.mapper as string) ?? null,
      cameras: (data.cameras as string[]) ?? [],
      gopros: (data.gopros as string[]) ?? [],
      fps: (data.fps as number) ?? null,
      previewEnabled: (data.preview_enabled as boolean | undefined) ?? true,
    }),
```

- [ ] **Step 3: Type-check**

```bash
cd /home/tirobot/MimicRec && npm --prefix frontend run build
```

Expected: clean build (`tsc` passes, `vite build` produces output).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/state/record-form-store.ts frontend/src/state/session-store.ts
git commit -m "feat(frontend): record-form and session stores hold previewEnabled"
```

---

## Task 10: SessionConfigForm — checkbox + payload

**Files:**
- Modify: `frontend/src/components/SessionConfigForm.tsx`

- [ ] **Step 1: Destructure `previewEnabled` from the form store**

Find the destructure (currently `SessionConfigForm.tsx:26`):

```typescript
  const { mode, robot, teleop, mapper, selectedCams, selectedGopros, dataset, task, fps } = form;
```

Replace with:

```typescript
  const { mode, robot, teleop, mapper, selectedCams, selectedGopros, dataset, task, fps, previewEnabled } = form;
```

- [ ] **Step 2: Include the field in `handleStart` body**

Find the body assignment (currently `SessionConfigForm.tsx:36-38`):

```typescript
    const body: Record<string, unknown> = {
      mode, dataset, task, robot, cameras: selectedCams, gopros: selectedGopros, fps,
    };
```

Replace with:

```typescript
    const body: Record<string, unknown> = {
      mode, dataset, task, robot, cameras: selectedCams, gopros: selectedGopros, fps,
      preview_enabled: previewEnabled,
    };
```

- [ ] **Step 3: Add the checkbox**

In the `border border-hairline rounded-md p-3 space-y-2 bg-surface-soft` block (currently containing `autoCycle`), append a sibling `<label>` after the `autoCycle` block (and any of its nested fields). Add the checkbox right above the closing `</div>` of that group:

```tsx
        <label className="flex items-center gap-2 text-sm font-medium text-charcoal">
          <input
            type="checkbox"
            checked={previewEnabled}
            onChange={e => form.set({ previewEnabled: e.target.checked })}
          />
          ライブプレビュー表示（OFF で USB 帯域・CPU を解放）
        </label>
```

- [ ] **Step 4: Type-check + visual smoke**

```bash
cd /home/tirobot/MimicRec && npm --prefix frontend run build
```

Expected: clean build.

Run the dev server and visually confirm the checkbox renders adjacent to "Auto cycle":

```bash
cd /home/tirobot/MimicRec && npm --prefix frontend run dev
```

Then open the Record page in a browser. Confirm the checkbox is visible, defaults to ON, and toggling it does not throw console errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SessionConfigForm.tsx
git commit -m "feat(frontend): SessionConfigForm preview_enabled checkbox"
```

---

## Task 11: RecordPage placeholder when preview is disabled

**Files:**
- Modify: `frontend/src/pages/RecordPage.tsx`

- [ ] **Step 1: Read `previewEnabled` from the session store**

Find the existing selectors block (currently `RecordPage.tsx:19-30`). Add a new selector:

```typescript
  const previewEnabled = useSessionStore((s) => s.previewEnabled);
```

(Place it adjacent to the `gopros` selector for readability.)

- [ ] **Step 2: Replace the camera-tile grid block**

Find the grid block (currently `RecordPage.tsx:123-129`):

```tsx
      {(cameras.length > 0 || gopros.length > 0) && sessionState !== "review" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-md mb-md">
          {[...cameras, ...gopros].map((cam) => (
            <CameraPreview key={cam} camName={cam} />
          ))}
        </div>
      )}
```

Replace with:

```tsx
      {(cameras.length > 0 || gopros.length > 0) && sessionState !== "review" && (
        previewEnabled ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-md mb-md">
            {[...cameras, ...gopros].map((cam) => (
              <CameraPreview key={cam} camName={cam} />
            ))}
          </div>
        ) : (
          <Card className="mb-md text-stone text-body-sm text-center py-md">
            ライブプレビューはこのセッションでは無効化されています
          </Card>
        )
      )}
```

(`Card` is already imported at the top of the file.)

- [ ] **Step 3: Type-check + visual smoke**

```bash
cd /home/tirobot/MimicRec && npm --prefix frontend run build
```

Expected: clean build.

Run the dev server, start a session with the checkbox off, and confirm the camera tiles are replaced by the placeholder text:

```bash
cd /home/tirobot/MimicRec && npm --prefix frontend run dev
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/RecordPage.tsx
git commit -m "feat(frontend): RecordPage shows placeholder when preview disabled"
```

---

## Task 12: Final verification

- [ ] **Step 1: Backend full test sweep**

```bash
cd /home/tirobot/MimicRec/backend && env -u PYTHONPATH ./.venv/bin/python -m pytest ../tests -v
```

Expected: every test passes (default `-m "not gopro_hardware"` from `pytest.ini`).

- [ ] **Step 2: Frontend type-check + build**

```bash
cd /home/tirobot/MimicRec && npm --prefix frontend run build
```

Expected: clean build.

- [ ] **Step 3: Manual end-to-end smoke**

Start the backend and frontend dev server. With real or mock hardware:

1. Default-on path: leave the new checkbox checked, start a session, confirm camera tiles render frames as before.
2. Disabled path: uncheck the box, start a session, confirm:
   - The placeholder card replaces the camera tile grid.
   - `/api/session/state` returns `"preview_enabled": false`.
   - Browser DevTools Network tab shows no `/ws/cameras/...` connections (or shows them closing immediately with 1008).
   - For GoPro: `journalctl -u <backend>` does not contain `preview opening` log lines from `gopro/preview.py`.
   - Recording an episode succeeds; `episode_save` writes an MP4 in the dataset.
3. Diagnostic A/B (the original motivation): record 5 consecutive episodes with `preview_enabled=false`. If DL/ffmpeg failures stop, the preview pipeline was contributing. Document the result in the spec's risk section as follow-up.

- [ ] **Step 4: Final commit (only if any cleanup was needed)**

```bash
git status
# If clean, no commit needed.
```

---

## Out of Scope (explicit, mirroring the spec)

- Mid-session toggle.
- Per-camera or per-GoPro granularity.
- Fixing the `download_file` timeout/retry, `media_list.size` resume, or `-map 0:d:1` issues flagged in Codex review (separate plans).
- Adding a frontend test runner (vitest/jest). Frontend correctness is verified via `tsc && vite build` and manual smoke.
