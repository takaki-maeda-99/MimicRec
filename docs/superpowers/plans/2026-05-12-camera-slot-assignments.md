# Camera Slot Assignments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple the dataset's `observation.images.<name>` key from the physical-device yaml name by introducing a global slot vocabulary and per-session slot→device assignments. Each session picks which physical device fills each slot; the yaml's `name` field stays as the physical adapter identity (SimCamera ZMQ topic, GoPro logging) while the slot is the dataset key.

**Architecture:** A new `configs/camera_roles.yaml` declares the global slot vocabulary. A new request field `slot_assignments: list[SlotAssignment]` replaces (with backward-compat shim) the legacy `cameras` and `gopros` lists. `GoProDeviceRegistry` and `GoProRecorder` are refactored so the slot is plumbed alongside the physical device — `_recorders`/`_previews`/`gopro_specs()` are keyed by slot, and the DL sidecar's `cam_name` is the slot. State payload builders emit a new `image_sources: list[{slot, device, kind}]` field; legacy `cameras` / `gopros` keep mirroring slot names by kind.

**Tech Stack:** Python 3.12 (FastAPI / asyncio / pydantic / omegaconf), pytest with `asyncio_mode=auto`, React 19 / TypeScript / Zustand / Vite.

**Spec:** `docs/superpowers/specs/2026-05-12-camera-slot-assignments-design.md`

**Test runner (backend):** `env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/...` from `/home/tirobot/MimicRec`.

**Type-check (frontend):** `npm --prefix frontend run build` from `/home/tirobot/MimicRec`.

---

## File Structure

**New files:**

| Path | Responsibility |
|---|---|
| `configs/camera_roles.yaml` | Global slot vocabulary (front, wrist, top, side, gripper). |
| `tests/unit/test_camera_roles_loader.py` | Loader returns roles list; path-safe regex accepts/rejects expected names. |
| `tests/unit/test_schemas_slot_assignments.py` | `SlotAssignment` / `ImageSource` / `_BaseSessionRequest.slot_assignments` accept the new shape; legacy `cameras`/`gopros` still accepted. |
| `tests/unit/gopro/test_recorder_slot_aware.py` | `GoProRecorder(device, queue, paths, errs, slot=...)` writes `cam_name=slot` (not `device.name`) into the sidecar. |
| `tests/unit/gopro/test_registry_slot_aware.py` | `GoProDeviceRegistry(devices=[(slot, device), ...])` keys `_recorders` / `_previews` / `gopro_specs()` by slot. |
| `tests/unit/test_deps_slot_validation.py` | All slot/device validation paths in deps (duplicate slot, duplicate device basename, missing device, etc.). |
| `tests/unit/test_deps_orphan_sidecar.py` | Orphan / corrupt sidecar makes session start 409. |
| `tests/unit/test_state_payload_image_sources.py` | REST + WS state payloads include `image_sources`. |
| `tests/integration/test_camera_roles_endpoint.py` | `GET /api/configs/camera_roles` returns yaml content. |
| `tests/integration/test_dataset_schema_endpoint.py` | `GET /api/datasets/{ds}/schema` returns `image_keys` from `info.json`. |
| `tests/integration/test_slot_assignment_end_to_end.py` | New dataset with slot_assignments; second session changes device per slot. |
| `tests/integration/test_legacy_cameras_compat.py` | Old-style `cameras: [...]` / `gopros: [...]` body still starts a session via the shim. |

**Modified files:**

| Path | Change |
|---|---|
| `backend/mimicrec/api/schemas.py` | Add `SlotAssignment`, `ImageSource`. Add `slot_assignments` to `_BaseSessionRequest`. Make `cameras` / `gopros` optional. Add `image_sources` to `SessionStatePayload`. |
| `backend/mimicrec/api/routes/configs.py` | Add `GET /api/configs/camera_roles`. |
| `backend/mimicrec/api/routes/datasets.py` | Add `GET /api/datasets/{ds}/schema`. |
| `backend/mimicrec/api/routes/session.py` | `build_state_payload` emits `image_sources`. |
| `backend/mimicrec/api/ws/session_hub.py` | `_build_ws_state` emits `image_sources`. |
| `backend/mimicrec/api/deps.py` | Big refactor: shim, validation, resolved-tuple build, slot-aware registry + init_dataset wiring, orphan sidecar check, resolved_config snapshot, session_meta update. |
| `backend/mimicrec/gopro/recorder.py` | Add `slot: str` constructor param; use `slot` as sidecar `cam_name`. |
| `backend/mimicrec/gopro/registry.py` | Constructor takes `list[tuple[str, GoProDevice]]`; key everything by slot. |
| `tests/unit/gopro/test_registry.py` | Update construction to pass `(slot, device)` tuples (slot==device.name for parity). |
| `tests/unit/gopro/test_recorder.py` | Update construction to pass `slot=device.name` for parity. |
| `frontend/src/api/queries.ts` | Add `useCameraRoles()` and `useDatasetSchema()` hooks. |
| `frontend/src/api/types.ts` | Add `ImageSource` type. |
| `frontend/src/state/record-form-store.ts` | Replace `selectedCams` / `selectedGopros` with `slotAssignments: SlotAssignmentDraft[]`. |
| `frontend/src/state/session-store.ts` | Add `imageSources: ImageSource[]` (hydrated from `data.image_sources`). |
| `frontend/src/components/SessionConfigForm.tsx` | Replace cameras/gopros multi-selects with the slot-assignment list UI; `handleStart` sends `slot_assignments`. |

---

## Task 1: `configs/camera_roles.yaml` + `GET /api/configs/camera_roles`

**Files:**
- Create: `configs/camera_roles.yaml`
- Modify: `backend/mimicrec/api/routes/configs.py`
- Test: `tests/integration/test_camera_roles_endpoint.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_camera_roles_endpoint.py`:

```python
from __future__ import annotations
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MIMICREC_CONFIGS_ROOT", str(REPO_ROOT / "configs"))
    monkeypatch.setenv("MIMICREC_DATASETS_ROOT", str(tmp_path / "datasets"))
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_camera_roles_endpoint_returns_yaml_roles(client: TestClient):
    r = client.get("/api/configs/camera_roles")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "roles" in body
    # Sanity: must include the canonical four roles.
    assert {"front", "wrist", "top", "side"}.issubset(set(body["roles"]))
```

- [ ] **Step 2: Run test, verify it fails**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/integration/test_camera_roles_endpoint.py -v
```

Expected: 404 (route not registered yet).

- [ ] **Step 3: Implement yaml**

Create `configs/camera_roles.yaml`:

```yaml
# Globally-defined camera slots. Datasets pick a subset; each session
# decides which physical device fills each slot.
roles:
  - front
  - wrist
  - top
  - side
  - gripper
```

- [ ] **Step 4: Implement endpoint**

Append to `backend/mimicrec/api/routes/configs.py`:

```python
from omegaconf import OmegaConf


@router.get("/configs/camera_roles")
async def camera_roles(request: Request) -> dict:
    """Returns the global slot vocabulary defined in
    configs/camera_roles.yaml. Used by the frontend to populate the
    slot dropdown in the session config form."""
    configs_root = get_configs_root(request.app)
    path = configs_root / "camera_roles.yaml"
    if not path.exists():
        return {"roles": []}
    cfg = OmegaConf.load(path)
    roles = list(cfg.roles) if hasattr(cfg, "roles") else []
    return {"roles": roles}
```

- [ ] **Step 5: Run test, verify it passes**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/integration/test_camera_roles_endpoint.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add configs/camera_roles.yaml backend/mimicrec/api/routes/configs.py tests/integration/test_camera_roles_endpoint.py
git commit -m "feat(api): camera_roles.yaml + GET /api/configs/camera_roles"
```

---

## Task 2: Camera roles loader helper + unit test

**Files:**
- Modify: `backend/mimicrec/api/deps.py` (new helper `_load_camera_roles`)
- Test: `tests/unit/test_camera_roles_loader.py`

A helper that `deps.create_session_from_request` will use in Task 7. Pinning it in a dedicated unit test makes the regex + missing-file handling easy to verify in isolation.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_camera_roles_loader.py`:

```python
import re
import pytest

from mimicrec.api.deps import _load_camera_roles, _SLOT_NAME_RE


def test_loader_returns_roles_list(tmp_path):
    (tmp_path / "camera_roles.yaml").write_text(
        "roles:\n  - front\n  - wrist\n"
    )
    assert _load_camera_roles(tmp_path) == ["front", "wrist"]


def test_loader_missing_file_returns_empty(tmp_path):
    assert _load_camera_roles(tmp_path) == []


def test_slot_name_regex_accepts_valid_names():
    for name in ("front", "wrist", "wrist_2", "top-1", "FRONT", "g_1-2"):
        assert _SLOT_NAME_RE.match(name), f"{name!r} should match"


def test_slot_name_regex_rejects_path_unsafe():
    for name in ("foo/bar", "foo.bar", "", "front bar", "front/", "front."):
        assert not _SLOT_NAME_RE.match(name), f"{name!r} should not match"
```

- [ ] **Step 2: Run test, verify it fails**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/unit/test_camera_roles_loader.py -v
```

Expected: ImportError — `_load_camera_roles` / `_SLOT_NAME_RE` do not exist.

- [ ] **Step 3: Implement helper**

Add to `backend/mimicrec/api/deps.py` (near the top, after the existing imports — `OmegaConf` and `re` may already be imported; add `import re` if not):

```python
import re

_SLOT_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _load_camera_roles(configs_root: Path) -> list[str]:
    """Read the global slot vocabulary from configs/camera_roles.yaml.
    Returns [] if the file is missing so the same helper is safe to
    call before the feature ships (existing datasets do not require
    camera_roles.yaml)."""
    path = configs_root / "camera_roles.yaml"
    if not path.exists():
        return []
    cfg = OmegaConf.load(path)
    return list(cfg.roles) if hasattr(cfg, "roles") else []
```

- [ ] **Step 4: Run test, verify it passes**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/unit/test_camera_roles_loader.py -v
```

Expected: 4/4 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/api/deps.py tests/unit/test_camera_roles_loader.py
git commit -m "feat(api): _load_camera_roles helper + path-safe regex"
```

---

## Task 3: `GET /api/datasets/{ds}/schema`

**Files:**
- Modify: `backend/mimicrec/api/routes/datasets.py`
- Test: `tests/integration/test_dataset_schema_endpoint.py`

Returns the list of `observation.images.*` keys from `info.json`. Frontend uses this to pre-populate slot rows for existing datasets.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_dataset_schema_endpoint.py`:

```python
from __future__ import annotations
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicrec.api.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("MIMICREC_CONFIGS_ROOT", str(repo_root / "configs"))
    monkeypatch.setenv("MIMICREC_DATASETS_ROOT", str(tmp_path / "datasets"))
    app = create_app()
    with TestClient(app) as c:
        yield c


def _seed_info_json(datasets_root: Path, ds: str, image_keys: list[str]) -> None:
    meta_dir = datasets_root / ds / "meta"
    meta_dir.mkdir(parents=True)
    features = {
        f"observation.images.{k}": {"info": {}} for k in image_keys
    }
    features["action"] = {}  # non-image feature — must be ignored by the endpoint
    info = {"features": features}
    (meta_dir / "info.json").write_text(json.dumps(info))


def test_schema_endpoint_returns_image_keys(client: TestClient, tmp_path: Path):
    _seed_info_json(tmp_path / "datasets", "ds1", ["front", "wrist"])
    r = client.get("/api/datasets/ds1/schema")
    assert r.status_code == 200, r.text
    assert sorted(r.json()["image_keys"]) == ["front", "wrist"]


def test_schema_endpoint_works_for_zero_episode_dataset(client: TestClient, tmp_path: Path):
    """The whole point of this endpoint is to be callable BEFORE any
    episode is recorded — useEpisodes returns [] then, but the schema
    is already fixed at init_dataset time."""
    _seed_info_json(tmp_path / "datasets", "ds_empty", ["front"])
    r = client.get("/api/datasets/ds_empty/schema")
    assert r.status_code == 200
    assert r.json()["image_keys"] == ["front"]


def test_schema_endpoint_404_for_unknown_dataset(client: TestClient):
    r = client.get("/api/datasets/does_not_exist/schema")
    assert r.status_code == 404
```

- [ ] **Step 2: Run test, verify it fails**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/integration/test_dataset_schema_endpoint.py -v
```

Expected: 404 (route not registered).

- [ ] **Step 3: Implement endpoint**

Append to `backend/mimicrec/api/routes/datasets.py`:

```python
@router.get("/datasets/{ds}/schema")
async def dataset_schema(request: Request, ds: str) -> dict:
    """Returns the list of observation.images.* keys from this dataset's
    info.json. The keys are the slot names; the frontend uses this to
    pre-populate slot rows for existing datasets (works even when
    episodes/ is empty)."""
    root = get_datasets_root(request.app)
    ds_root = root / ds
    info_path = ds_root / "meta" / "info.json"
    if not info_path.exists():
        raise FileNotFoundError(f"dataset '{ds}' not found")
    import json as _json
    info = _json.loads(info_path.read_text())
    image_keys = sorted(
        k.removeprefix("observation.images.")
        for k in info.get("features", {})
        if k.startswith("observation.images.")
    )
    return {"image_keys": image_keys}
```

- [ ] **Step 4: Run test, verify it passes**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/integration/test_dataset_schema_endpoint.py -v
```

Expected: 3/3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/api/routes/datasets.py tests/integration/test_dataset_schema_endpoint.py
git commit -m "feat(api): GET /api/datasets/{ds}/schema for slot row pre-fill"
```

---

## Task 4: Add `SlotAssignment` / `ImageSource` schemas

**Files:**
- Modify: `backend/mimicrec/api/schemas.py`
- Test: `tests/unit/test_schemas_slot_assignments.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_schemas_slot_assignments.py`:

```python
import pytest

from mimicrec.api.schemas import (
    HandTeachSessionRequest,
    ImageSource,
    SessionStatePayload,
    SlotAssignment,
    TeleopSessionRequest,
)


def _teleop_kwargs(**extra):
    base = dict(
        dataset="ds", task="t", robot="r",
        teleop="tl", mapper="mp",
    )
    base.update(extra)
    return base


def test_slot_assignment_parses():
    a = SlotAssignment(slot="front", device="gopro_external")
    assert a.slot == "front"
    assert a.device == "gopro_external"


def test_image_source_parses():
    s = ImageSource(slot="front", device="gopro_external", kind="gopro")
    assert s.kind == "gopro"


def test_session_request_accepts_slot_assignments():
    req = TeleopSessionRequest(**_teleop_kwargs(
        slot_assignments=[
            {"slot": "front", "device": "gopro_external"},
            {"slot": "wrist", "device": "mock_cam"},
        ],
    ))
    assert [a.slot for a in req.slot_assignments] == ["front", "wrist"]


def test_session_request_still_accepts_legacy_cameras_gopros():
    """Backward-compat: legacy clients sending cameras/gopros must still
    parse; the deps layer normalizes them into slot_assignments."""
    req = HandTeachSessionRequest(
        dataset="ds", task="t", robot="r",
        cameras=["front"], gopros=["gopro_external"],
    )
    assert req.cameras == ["front"]
    assert req.gopros == ["gopro_external"]
    assert req.slot_assignments == []


def test_session_state_payload_includes_image_sources():
    p = SessionStatePayload(
        state="ready",
        image_sources=[
            ImageSource(slot="front", device="gopro_external", kind="gopro"),
        ],
    )
    dumped = p.model_dump()
    assert dumped["image_sources"] == [
        {"slot": "front", "device": "gopro_external", "kind": "gopro"}
    ]
```

- [ ] **Step 2: Run test, verify it fails**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/unit/test_schemas_slot_assignments.py -v
```

Expected: ImportError — `SlotAssignment` / `ImageSource` do not exist.

- [ ] **Step 3: Implement schemas**

Edit `backend/mimicrec/api/schemas.py`. Add new types near the top of the file (after the existing imports) and update `_BaseSessionRequest` + `SessionStatePayload`:

```python
from typing import Annotated, Literal


class SlotAssignment(BaseModel):
    slot: str
    device: str


class ImageSource(BaseModel):
    slot: str
    device: str
    kind: Literal["camera", "gopro"]


class _BaseSessionRequest(BaseModel):
    dataset: str
    task: str
    robot: str
    fps: int = 30
    preview_enabled: bool = True
    slot_assignments: list[SlotAssignment] = Field(default_factory=list)
    # Deprecated legacy inputs. The deps layer rewrites them into
    # slot_assignments via a backward-compat shim.
    cameras: list[str] = Field(default_factory=list)
    gopros: list[str] = Field(default_factory=list)
```

`SessionStatePayload` gains `image_sources` (cameras / gopros stay as deprecated mirrors):

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
    image_sources: list[ImageSource] = Field(default_factory=list)
```

- [ ] **Step 4: Run test, verify it passes**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/unit/test_schemas_slot_assignments.py tests/unit/test_schemas_preview_enabled.py tests/unit/gopro/test_schemas_gopros.py -v
```

Expected: all PASS — including the existing schema tests (we only added fields with defaults, did not break old shape).

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/api/schemas.py tests/unit/test_schemas_slot_assignments.py
git commit -m "feat(api): SlotAssignment / ImageSource schemas + request/payload fields"
```

---

## Task 5: `GoProRecorder` takes `slot` and writes `cam_name=slot`

**Files:**
- Modify: `backend/mimicrec/gopro/recorder.py`
- Modify: `tests/unit/gopro/test_recorder.py` (existing constructor calls)
- Test: `tests/unit/gopro/test_recorder_slot_aware.py`

Today `recorder.stop_episode` writes `cam_name=self._device.name` into the GoPro DL sidecar. The sidecar's `cam_name` is what DLWorker uses to compute the final video path (`videos/observation.images.<cam_name>/episode_N.mp4`). To make the dataset key the slot, the recorder must take the slot as a separate parameter and write that.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/gopro/test_recorder_slot_aware.py`:

```python
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
```

- [ ] **Step 2: Run test, verify it fails**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/unit/gopro/test_recorder_slot_aware.py -v
```

Expected: TypeError — `GoProRecorder.__init__` does not accept `slot=`.

- [ ] **Step 3: Implement: add `slot` param to recorder**

Edit `backend/mimicrec/gopro/recorder.py`. Find the constructor (around line 27) and the place in `_stop_episode_inner` where `cam_name=self._device.name` is set (around line 175-180).

Constructor: add a required `slot: str` arg (keep existing args first so the call sites' positional args stay valid):

```python
class GoProRecorder:
    """Control-plane view over a single GoProDevice."""

    def __init__(self, device, queue: DLQueue, paths: DatasetPaths, errors: ErrorBus, slot: str) -> None:
        self._device = device
        self._slot = slot
        self._queue = queue
        self._paths = paths
        self._errors = errors
        self._known_files: set[str] = set()
        self._state: _EpisodeState | None = None
        # is_finishing tracking: see test_recorder_is_finishing_flag.py for context.
        self._is_finishing: bool = False
```

Use `self._slot` in the sidecar build. Find this block in `_stop_episode_inner`:

```python
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
```

Change `cam_name=self._device.name` to `cam_name=self._slot`.

- [ ] **Step 4: Update existing recorder tests to pass `slot`**

Edit `tests/unit/gopro/test_recorder.py`. Find every `GoProRecorder(d, queue, paths, errs)` call and change to `GoProRecorder(d, queue, paths, errs, slot=d.name)`. Use grep to find them:

```bash
grep -n "GoProRecorder(" tests/unit/gopro/test_recorder.py tests/unit/gopro/test_recorder_shutter_on_retry.py tests/unit/gopro/test_recorder_media_list_polling.py tests/unit/gopro/test_recorder_is_finishing_flag.py
```

Add `slot=d.name` (or `slot="g1"` matching the device's name) to each call. This preserves the previous behavior (cam_name == device.name) for those tests.

- [ ] **Step 5: Run all recorder tests, verify they pass**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/unit/gopro/test_recorder.py tests/unit/gopro/test_recorder_slot_aware.py tests/unit/gopro/test_recorder_shutter_on_retry.py tests/unit/gopro/test_recorder_media_list_polling.py tests/unit/gopro/test_recorder_is_finishing_flag.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/mimicrec/gopro/recorder.py tests/unit/gopro/test_recorder_slot_aware.py tests/unit/gopro/test_recorder.py tests/unit/gopro/test_recorder_shutter_on_retry.py tests/unit/gopro/test_recorder_media_list_polling.py tests/unit/gopro/test_recorder_is_finishing_flag.py
git commit -m "feat(gopro): GoProRecorder takes slot, writes slot into sidecar cam_name"
```

---

## Task 6: `GoProDeviceRegistry` accepts `list[tuple[slot, device]]`

**Files:**
- Modify: `backend/mimicrec/gopro/registry.py`
- Modify: `tests/unit/gopro/test_registry.py`
- Test: `tests/unit/gopro/test_registry_slot_aware.py`

Today the registry stores `_recorders[d.name]`, `_previews[d.name]`, returns `gopro_specs() = {d.name: spec}`. After this task it stores by `slot`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/gopro/test_registry_slot_aware.py`:

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
async def test_registry_keys_recorders_previews_specs_by_slot(paths):
    """Slot is the dict key throughout. device.name is preserved on the
    adapter for physical-ID logging but is not the registry key."""
    d = MockGoProDevice(name="gopro_external", usb_serial="S1")
    reg = GoProDeviceRegistry(
        devices=[("front", d)], paths=paths, errors=ErrorBus(),
    )
    await reg.start()
    try:
        assert "front" in reg.preview_sources()
        assert "gopro_external" not in reg.preview_sources()
        assert "front" in reg.gopro_specs()
        assert "gopro_external" not in reg.gopro_specs()
        assert "front" in reg._recorders  # type: ignore[attr-defined]
    finally:
        await reg.stop()


def test_registry_rejects_duplicate_slot(paths):
    a = MockGoProDevice(name="gopro_a", usb_serial="SA")
    b = MockGoProDevice(name="gopro_b", usb_serial="SB")
    with pytest.raises(ValueError, match="duplicate slot"):
        GoProDeviceRegistry(
            devices=[("front", a), ("front", b)],
            paths=paths, errors=ErrorBus(),
        )


def test_registry_rejects_duplicate_usb_serial_unchanged(paths):
    """Existing serial-uniqueness check still fires."""
    a = MockGoProDevice(name="ga", usb_serial="S1")
    b = MockGoProDevice(name="gb", usb_serial="S1")
    with pytest.raises(ValueError, match="duplicate usb_serial"):
        GoProDeviceRegistry(
            devices=[("front", a), ("wrist", b)],
            paths=paths, errors=ErrorBus(),
        )
```

- [ ] **Step 2: Run test, verify it fails**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/unit/gopro/test_registry_slot_aware.py -v
```

Expected: failures because the registry treats `("front", d)` as a device object.

- [ ] **Step 3: Refactor `GoProDeviceRegistry`**

Edit `backend/mimicrec/gopro/registry.py`. Change `__init__` to take a list of `(slot, device)` pairs:

```python
class GoProDeviceRegistry:
    def __init__(
        self,
        devices: list[tuple[str, object]],
        paths: DatasetPaths,
        errors: ErrorBus,
        preview_enabled: bool = True,
    ) -> None:
        slots = [s for s, _ in devices]
        serials = [d.usb_serial for _, d in devices]
        if len(set(slots)) != len(slots):
            raise ValueError(f"duplicate slot in GoPro devices: {slots}")
        if len(set(serials)) != len(serials):
            raise ValueError(f"duplicate usb_serial in GoPro devices: {serials}")
        self._pairs = list(devices)
        self._devices = [d for _, d in devices]
        self._paths = paths
        self._errors = errors
        self._preview_enabled = preview_enabled
        self._queue: DLQueue | None = None
        self._worker: GoProDLWorker | None = None
        self._worker_task: asyncio.Task | None = None
        self._recorders: dict[str, GoProRecorder] = {}
        self._previews: dict[str, GoProPreviewSource] = {}
```

In `start()`, replace the loop:

```python
        self._queue = DLQueue.restore(self._paths.pending_dir / "gopro_dl")
        for slot, d in self._pairs:
            self._recorders[slot] = GoProRecorder(
                d, self._queue, self._paths, self._errors, slot=slot,
            )
            if self._preview_enabled:
                self._previews[slot] = GoProPreviewSource(d, udp_port=d.udp_preview_port)
```

In `gopro_specs()`, key by slot:

```python
    def gopro_specs(self) -> dict[str, GoProSpec]:
        return {slot: d.get_spec() for slot, d in self._pairs}
```

Also: `_try_connect` in `start()` (the existing block that gathers connect results) iterates `self._devices` — that still works (slot isn't needed for connect). But error messages reference `d.name` — leave those alone (logs are about physical device, not slot).

- [ ] **Step 4: Update existing registry tests to pass tuples**

Edit `tests/unit/gopro/test_registry.py` and `tests/unit/gopro/test_registry_preview_toggle.py`. Find every `GoProDeviceRegistry(devices=[a, b, ...], ...)` call and change to `devices=[(a.name, a), (b.name, b), ...]`. Keep the slot equal to the device's name so existing assertions on `reg.preview_sources()["g1"]` still pass.

The existing tests `test_duplicate_name_raises` was about device name being duplicate — that semantic moves to "duplicate slot" now. Update its assertion message:

```python
def test_duplicate_slot_raises(paths):
    a = MockGoProDevice(name="ga", usb_serial="S1")
    b = MockGoProDevice(name="gb", usb_serial="S2")
    with pytest.raises(ValueError, match="duplicate slot"):
        GoProDeviceRegistry(devices=[("g1", a), ("g1", b)], paths=paths, errors=ErrorBus())
```

(Rename the test function from `test_duplicate_name_raises` to `test_duplicate_slot_raises`.)

- [ ] **Step 5: Run all registry tests, verify they pass**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/unit/gopro/test_registry.py tests/unit/gopro/test_registry_slot_aware.py tests/unit/gopro/test_registry_preview_toggle.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/mimicrec/gopro/registry.py tests/unit/gopro/test_registry_slot_aware.py tests/unit/gopro/test_registry.py tests/unit/gopro/test_registry_preview_toggle.py
git commit -m "feat(gopro): GoProDeviceRegistry keys recorders/previews/specs by slot"
```

---

## Task 7: deps.py — backward-compat shim + slot/device validation

**Files:**
- Modify: `backend/mimicrec/api/deps.py`
- Test: `tests/unit/test_deps_slot_validation.py`

This is the biggest task. We rebuild `create_session_from_request` around `slot_assignments`. Keep the existing skeleton (robot/teleop/mapper loading) untouched; only the camera/GoPro section changes.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_deps_slot_validation.py`. Use a minimal harness that drives `create_session_from_request` against a mocked `req` and a real `configs/` dir; assertions cover each rejection rule.

```python
from __future__ import annotations
from pathlib import Path

import pytest
from fastapi import HTTPException, FastAPI

from mimicrec.api.deps import create_session_from_request
from mimicrec.api.schemas import HandTeachSessionRequest, SlotAssignment


REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir(parents=True)
    app.state.push_coordinator = None
    return app


def _req(**extra) -> HandTeachSessionRequest:
    base = dict(dataset="ds1", task="t", robot="mock", fps=30)
    base.update(extra)
    return HandTeachSessionRequest(**base)


@pytest.mark.asyncio
async def test_legacy_cameras_gopros_normalized_into_slot_assignments(tmp_path):
    """Legacy clients sending {cameras: ['front'], gopros: ['mock_gopro']}
    must be rewritten into the equivalent slot_assignments."""
    app = _make_app(tmp_path)
    req = _req(cameras=["mock_cam"], gopros=[])
    sm = await create_session_from_request(app, req)
    try:
        slot_assigns = app.state.session_meta["slot_assignments"]
        assert {a["slot"] for a in slot_assigns} == {"mock_cam"}
        assert {a["device"] for a in slot_assigns} == {"mock_cam"}
    finally:
        await sm.end()


@pytest.mark.asyncio
async def test_duplicate_slot_400(tmp_path):
    app = _make_app(tmp_path)
    req = _req(slot_assignments=[
        SlotAssignment(slot="front", device="mock_cam"),
        SlotAssignment(slot="front", device="mock_front"),
    ])
    with pytest.raises(HTTPException) as exc:
        await create_session_from_request(app, req)
    assert exc.value.status_code == 400
    assert "duplicate slot" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_duplicate_device_basename_400(tmp_path):
    app = _make_app(tmp_path)
    req = _req(slot_assignments=[
        SlotAssignment(slot="front", device="mock_cam"),
        SlotAssignment(slot="wrist", device="mock_cam"),
    ])
    with pytest.raises(HTTPException) as exc:
        await create_session_from_request(app, req)
    assert exc.value.status_code == 400
    assert "duplicate device" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_slot_not_in_roles_or_image_keys_400(tmp_path):
    app = _make_app(tmp_path)
    req = _req(slot_assignments=[
        SlotAssignment(slot="bogus_slot", device="mock_cam"),
    ])
    with pytest.raises(HTTPException) as exc:
        await create_session_from_request(app, req)
    assert exc.value.status_code == 400
    assert "bogus_slot" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_path_unsafe_slot_400(tmp_path):
    app = _make_app(tmp_path)
    req = _req(slot_assignments=[
        SlotAssignment(slot="../escape", device="mock_cam"),
    ])
    with pytest.raises(HTTPException) as exc:
        await create_session_from_request(app, req)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_missing_device_400(tmp_path):
    app = _make_app(tmp_path)
    req = _req(slot_assignments=[
        SlotAssignment(slot="front", device="ghost_device"),
    ])
    with pytest.raises(HTTPException) as exc:
        await create_session_from_request(app, req)
    assert exc.value.status_code == 400
    assert "ghost_device" in str(exc.value.detail)
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/unit/test_deps_slot_validation.py -v
```

Expected: failures across the board (`deps.py` still uses the old `cameras`/`gopros` path).

- [ ] **Step 3: Refactor `deps.create_session_from_request`**

Edit `backend/mimicrec/api/deps.py`. Open the file, find the camera/GoPro section (lines ~107-156 today). Replace that whole block with a slot-aware version.

The new flow keeps the surrounding robot/teleop/mapper setup unchanged. The camera/GoPro section becomes:

```python
    # ── Slot assignments (replaces the legacy cameras/gopros lists) ─────
    declared_roles = _load_camera_roles(configs_root)

    # Backward-compat shim: legacy clients that send only `cameras`
    # and/or `gopros` get rewritten into slot_assignments where
    # slot == device (i.e. previous behavior).
    if not req.slot_assignments and (req.cameras or req.gopros):
        req.slot_assignments = [
            SlotAssignment(slot=n, device=n)
            for n in (*req.cameras, *req.gopros)
        ]

    # Slot duplicate
    seen_slots: set[str] = set()
    for a in req.slot_assignments:
        if a.slot in seen_slots:
            raise HTTPException(400, f"duplicate slot {a.slot!r}")
        seen_slots.add(a.slot)

    # Device basename duplicate (catches mock / sim cameras that have
    # no physical-ID uniqueness check downstream)
    seen_devices: set[str] = set()
    for a in req.slot_assignments:
        if a.device in seen_devices:
            raise HTTPException(400,
                f"duplicate device basename {a.device!r} assigned to multiple slots")
        seen_devices.add(a.device)

    # Slot name path-safe + must be in declared roles or in this
    # dataset's existing image_keys (existing datasets keep their
    # legacy keys working).
    ds_root = datasets_root / req.dataset
    existing_image_keys: set[str] = set()
    info_path = ds_root / "meta" / "info.json"
    if info_path.exists():
        import json as _json
        info = _json.loads(info_path.read_text())
        existing_image_keys = {
            k.removeprefix("observation.images.")
            for k in info.get("features", {})
            if k.startswith("observation.images.")
        }
    allowed_slots = set(declared_roles) | existing_image_keys
    for a in req.slot_assignments:
        if not _SLOT_NAME_RE.match(a.slot):
            raise HTTPException(400,
                f"slot {a.slot!r} contains path-unsafe characters")
        if a.slot not in allowed_slots:
            raise HTTPException(400,
                f"slot {a.slot!r} is neither in camera_roles.yaml nor in this "
                f"dataset's existing image_keys ({sorted(existing_image_keys)})")

    # Resolve each device basename to (kind, cfg, adapter). adapter
    # keeps its yaml-defined `name` (physical adapter identity, e.g.
    # SimCamera ZMQ topic); the slot is the dataset key.
    resolved: list[tuple[str, str, str, dict, object]] = []
    cam_cfgs: dict[str, dict] = {}
    for a in req.slot_assignments:
        cam_path = configs_root / "cameras" / f"{a.device}.yaml"
        go_path = configs_root / "gopros" / f"{a.device}.yaml"
        if cam_path.exists() and go_path.exists():
            raise HTTPException(400,
                f"device {a.device!r} is ambiguous (in both cameras/ and gopros/)")
        if cam_path.exists():
            kind = "camera"
            cfg = OmegaConf.to_container(OmegaConf.load(cam_path))
        elif go_path.exists():
            kind = "gopro"
            cfg = OmegaConf.to_container(OmegaConf.load(go_path))
        else:
            raise HTTPException(400, f"device {a.device!r} not found")
        kwargs = {k: v for k, v in cfg.items() if k != "_target_"}
        adapter = instantiate_adapter(str(cfg["_target_"]), **kwargs)
        resolved.append((a.slot, a.device, kind, cfg, adapter))
        if kind == "camera":
            cam_cfgs[a.slot] = cfg

    # Physical-ID uniqueness across resolved devices
    seen_device_ids: dict[int, str] = {}
    for slot, _device, kind, cfg, _adapter in resolved:
        if kind == "camera" and "device_id" in cfg:
            did = int(cfg["device_id"])
            if did in seen_device_ids:
                raise HTTPException(400,
                    f"duplicate OpenCV device_id={did} across slots "
                    f"({seen_device_ids[did]!r} and {slot!r})")
            seen_device_ids[did] = slot
    seen_serials: dict[str, str] = {}
    for slot, _device, kind, cfg, _adapter in resolved:
        if kind == "gopro" and "usb_serial" in cfg:
            ser = str(cfg["usb_serial"])
            if ser in seen_serials:
                raise HTTPException(400,
                    f"duplicate GoPro usb_serial={ser!r} across slots "
                    f"({seen_serials[ser]!r} and {slot!r})")
            seen_serials[ser] = slot

    # cams dict for CameraManager: keyed by slot
    cams: dict[str, object] = {
        slot: adapter for slot, _device, kind, _cfg, adapter in resolved
        if kind == "camera"
    }

    # GoPro device pairs for the registry: [(slot, device)]
    gopro_pairs: list[tuple[str, object]] = [
        (slot, adapter) for slot, _device, kind, _cfg, adapter in resolved
        if kind == "gopro"
    ]
```

After this block, follow with the existing error_bus / paths / gopro_registry construction. Replace the existing `GoProDeviceRegistry(...)` call to pass `devices=gopro_pairs`. Replace `for name, src in gopro_registry.preview_sources().items(): cams[name] = src` line — that still works as-is (preview_sources is keyed by slot now).

For `init_dataset` (around line 216-241), build args from `resolved`:

```python
camera_slots = [slot for slot, _d, k, _c, _a in resolved if k == "camera"]
camera_resolutions = {
    slot: (int(cam_cfgs[slot].get("width", 640)),
           int(cam_cfgs[slot].get("height", 480)))
    for slot in camera_slots
}
init_dataset(
    ds_root, fps=req.fps,
    joint_names=robot.joint_names,
    camera_names=camera_slots,
    robot_type=rt,
    gripper_convention=(...),  # unchanged
    proprio_layout=(...),       # unchanged
    camera_resolutions=camera_resolutions,
    gopro_specs=gopro_registry.gopro_specs() if gopro_registry else None,
)
```

The existing-dataset schema check (around line 281-298) becomes:

```python
        existing_image_keys = {
            k.removeprefix("observation.images.")
            for k in info.get("features", {})
            if k.startswith("observation.images.")
        }
        requested_slots = {a.slot for a in req.slot_assignments}
        if existing_image_keys != requested_slots:
            missing = sorted(existing_image_keys - requested_slots)
            extra = sorted(requested_slots - existing_image_keys)
            parts: list[str] = []
            if missing:
                parts.append(f"missing {missing}")
            if extra:
                parts.append(f"unexpected {extra} (not in dataset schema)")
            raise HTTPException(
                status_code=400,
                detail=(
                    f"dataset '{req.dataset}' was created with slots="
                    f"{sorted(existing_image_keys)}; request differs "
                    f"({'; '.join(parts)}). Create a new dataset to use a different slot set."
                ),
            )
```

Finally, update the `session_meta` dict (around line 301-310):

```python
    app.state.session_meta = {
        "dataset": req.dataset,
        "task": req.task,
        "robot": req.robot,
        "teleop": teleop_name,
        "mapper": mapper_name,
        "slot_assignments": [
            {"slot": s, "device": d, "kind": k}
            for s, d, k, _c, _a in resolved
        ],
        "cameras": [s for s, _d, k, _c, _a in resolved if k == "camera"],
        "gopros": [s for s, _d, k, _c, _a in resolved if k == "gopro"],
        "fps": req.fps,
        "preview_enabled": bool(req.preview_enabled),
    }
```

The orphan-sidecar check + resolved_config persistence come in Tasks 8 and 9; leave placeholders / skip them for now.

Also import `SlotAssignment` and `_SLOT_NAME_RE` are already in deps.py from Task 4 / Task 2; add `from mimicrec.api.schemas import SlotAssignment` if not present.

- [ ] **Step 4: Run validation tests, verify they pass**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/unit/test_deps_slot_validation.py -v
```

Expected: 6/6 PASS.

- [ ] **Step 5: Smoke-check existing integration tests**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/integration/test_session_lifecycle_mock.py tests/integration/test_gopro_mock_session.py tests/integration/test_session_preview_toggle.py -v
```

Expected: most PASS. `test_gopro_mock_session.py` may need a small update (its body uses legacy `gopros`, but the shim covers it) — confirm before continuing.

- [ ] **Step 6: Commit**

```bash
git add backend/mimicrec/api/deps.py tests/unit/test_deps_slot_validation.py
git commit -m "feat(api): deps rebuilds session around slot_assignments with backward-compat shim"
```

---

## Task 8: Orphan / corrupt GoPro sidecar check

**Files:**
- Modify: `backend/mimicrec/api/deps.py`
- Test: `tests/unit/test_deps_orphan_sidecar.py`

After `create_session_from_request` has resolved the slot set but before `gopro_registry.start()`, scan the pending sidecar dir and reject the session if any sidecar's `cam_name` is unknown or if any sidecar is unparseable.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_deps_orphan_sidecar.py`:

```python
from __future__ import annotations
import json
from pathlib import Path

import pytest
from fastapi import HTTPException, FastAPI

from mimicrec.api.deps import create_session_from_request
from mimicrec.api.schemas import HandTeachSessionRequest, SlotAssignment

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir(parents=True)
    app.state.push_coordinator = None
    return app


def _seed_sidecar(datasets_root: Path, ds: str, content: dict | str) -> None:
    pdir = datasets_root / ds / ".pending" / "gopro_dl"
    pdir.mkdir(parents=True)
    sidecar = pdir / "stale.json"
    if isinstance(content, str):
        sidecar.write_text(content)
    else:
        sidecar.write_text(json.dumps(content))


@pytest.mark.asyncio
async def test_orphan_sidecar_with_unknown_cam_name_409(tmp_path):
    _seed_sidecar(tmp_path / "datasets", "ds1", {
        "job_id": "j1", "gopro_serial": "S0", "sd_filename": "GX010001.MP4",
        "episode_index": 0, "chunk_index": 0, "cam_name": "ghost_slot",
        "episode_start_mono_ns": 0, "episode_stop_mono_ns": 10_000_000_000,
        "state": "pending_dl",
    })
    app = _make_app(tmp_path)
    req = HandTeachSessionRequest(dataset="ds1", task="t", robot="mock",
        slot_assignments=[SlotAssignment(slot="front", device="mock_cam")])
    with pytest.raises(HTTPException) as exc:
        await create_session_from_request(app, req)
    assert exc.value.status_code == 409
    assert "ghost_slot" in str(exc.value.detail) or "orphan" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_corrupt_sidecar_409(tmp_path):
    _seed_sidecar(tmp_path / "datasets", "ds_corrupt", "not valid json {")
    app = _make_app(tmp_path)
    req = HandTeachSessionRequest(dataset="ds_corrupt", task="t", robot="mock",
        slot_assignments=[SlotAssignment(slot="front", device="mock_cam")])
    with pytest.raises(HTTPException) as exc:
        await create_session_from_request(app, req)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_sidecar_with_matching_slot_passes(tmp_path):
    _seed_sidecar(tmp_path / "datasets", "ds_ok", {
        "job_id": "j1", "gopro_serial": "S0", "sd_filename": "GX010001.MP4",
        "episode_index": 0, "chunk_index": 0, "cam_name": "front",
        "episode_start_mono_ns": 0, "episode_stop_mono_ns": 10_000_000_000,
        "state": "pending_dl",
    })
    app = _make_app(tmp_path)
    req = HandTeachSessionRequest(dataset="ds_ok", task="t", robot="mock",
        slot_assignments=[SlotAssignment(slot="front", device="mock_cam")])
    # Should NOT raise an orphan check error. (Other errors may surface
    # from the rest of the start flow but not 409 with 'orphan'.)
    try:
        sm = await create_session_from_request(app, req)
        await sm.end()
    except HTTPException as e:
        assert e.status_code != 409, f"unexpected 409: {e.detail}"
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/unit/test_deps_orphan_sidecar.py -v
```

Expected: failures — orphan check not implemented yet.

- [ ] **Step 3: Add orphan check in deps.py**

Edit `backend/mimicrec/api/deps.py`. After the resolved-tuple loop in Task 7 and before `gopro_registry.start()`, add:

```python
    # Orphan / corrupt sidecar check. Sidecars persisted from a previous
    # session whose slot set differs from this one would cause DLWorker
    # to commit mp4s under unexpected paths (or fail validation in info.json).
    # Refuse to start until the operator resolves the discrepancy.
    pdir = ds_root / ".pending" / "gopro_dl"
    if pdir.exists():
        slot_names = {a.slot for a in req.slot_assignments}
        import json as _json
        from mimicrec.gopro.dl_queue import GoProDLJob
        for sidecar in sorted(pdir.glob("*.json")):
            try:
                data = _json.loads(sidecar.read_text())
                job = GoProDLJob.from_json(data)
            except Exception:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"corrupt or unparseable GoPro sidecar "
                        f"{sidecar.name!r} — refusing to start session "
                        f"until inspected"),
                )
            if job.cam_name not in slot_names:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"orphan GoPro sidecar {sidecar.name} "
                        f"(cam_name={job.cam_name!r}) does not match this "
                        f"session's slots {sorted(slot_names)}. Resolve by "
                        f"ending the previous session cleanly or moving "
                        f"the file aside."),
                )
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/unit/test_deps_orphan_sidecar.py -v
```

Expected: 3/3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/api/deps.py tests/unit/test_deps_orphan_sidecar.py
git commit -m "feat(api): orphan/corrupt GoPro sidecar 409 on session start"
```

---

## Task 9: Persist `slot_assignments` snapshot into `resolved_config`

**Files:**
- Modify: `backend/mimicrec/api/deps.py`
- Test: `tests/unit/test_deps_resolved_config.py`

`resolved_config` is stored on `app.state` and written into the episode parquet metadata. Surface the full slot↔device↔kind↔yaml-snapshot mapping so an analyst can later reconstruct exactly what hardware fed each episode.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_deps_resolved_config.py`:

```python
from __future__ import annotations
from pathlib import Path

import pytest
from fastapi import FastAPI

from mimicrec.api.deps import create_session_from_request
from mimicrec.api.schemas import HandTeachSessionRequest, SlotAssignment

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def app(tmp_path):
    app = FastAPI()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir(parents=True)
    app.state.push_coordinator = None
    return app


@pytest.mark.asyncio
async def test_resolved_config_records_full_slot_assignment_snapshot(app):
    req = HandTeachSessionRequest(
        dataset="ds_res", task="t", robot="mock",
        slot_assignments=[SlotAssignment(slot="front", device="mock_cam")],
    )
    sm = await create_session_from_request(app, req)
    try:
        rc = app.state.resolved_config
        assert "slot_assignments" in rc
        snap = rc["slot_assignments"]
        assert len(snap) == 1
        assert snap[0]["slot"] == "front"
        assert snap[0]["device"] == "mock_cam"
        assert snap[0]["kind"] == "camera"
        assert "device_config" in snap[0]
        # device_config is the yaml content dict
        assert snap[0]["device_config"]["_target_"].endswith("MockCamera")
    finally:
        await sm.end()
```

- [ ] **Step 2: Run test, verify it fails**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/unit/test_deps_resolved_config.py -v
```

Expected: AssertionError — `slot_assignments` key missing from `resolved_config`.

- [ ] **Step 3: Persist into resolved_config**

In `backend/mimicrec/api/deps.py`, find the existing `resolved_config` assembly (around line 288, look for `resolved: dict[str, object] = {"robot": OmegaConf.to_container(robot_cfg)}`). Add `slot_assignments`:

```python
    resolved_config: dict[str, object] = {"robot": OmegaConf.to_container(robot_cfg)}
    if teleop_cfg is not None:
        resolved_config["teleop"] = OmegaConf.to_container(teleop_cfg)
    if mapper_cfg is not None:
        resolved_config["mapper"] = OmegaConf.to_container(mapper_cfg)
    # New: per-slot device yaml snapshots
    resolved_config["slot_assignments"] = [
        {"slot": slot, "device": device, "kind": kind, "device_config": cfg}
        for slot, device, kind, cfg, _adapter in resolved
    ]
    # Keep cam_cfgs as legacy mirror so existing exporters / analysis
    # that look under resolved_config["cameras"] still find their data.
    if cam_cfgs:
        resolved_config["cameras"] = cam_cfgs
```

(Rename the existing local variable `resolved: dict` to `resolved_config: dict` if it collides with the resolved tuple list from Task 7. The plan-internal name is `resolved_config` for clarity. Adjust the downstream `app.state.resolved_config = resolved` assignment to use the new name.)

- [ ] **Step 4: Run test, verify it passes**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/unit/test_deps_resolved_config.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/api/deps.py tests/unit/test_deps_resolved_config.py
git commit -m "feat(api): persist slot_assignments + device yaml snapshots in resolved_config"
```

---

## Task 10: Emit `image_sources` in REST and WS state payloads

**Files:**
- Modify: `backend/mimicrec/api/routes/session.py`
- Modify: `backend/mimicrec/api/ws/session_hub.py`
- Test: `tests/unit/test_state_payload_image_sources.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_state_payload_image_sources.py`:

```python
from __future__ import annotations
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MIMICREC_CONFIGS_ROOT", str(REPO_ROOT / "configs"))
    monkeypatch.setenv("MIMICREC_DATASETS_ROOT", str(tmp_path / "datasets"))
    app = create_app()
    with TestClient(app) as c:
        yield c


def _start_body(**slot_assigns) -> dict:
    return {
        "mode": "hand_teach",
        "dataset": "img_src_ds",
        "task": "default",
        "robot": "mock",
        "fps": 30,
        "slot_assignments": [
            {"slot": "front", "device": "mock_cam"},
        ],
    }


def test_rest_state_includes_image_sources(client: TestClient):
    r = client.post("/api/session/start", json=_start_body())
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["image_sources"] == [
        {"slot": "front", "device": "mock_cam", "kind": "camera"}
    ]
    # Legacy mirror still populated by kind-filtered slot names
    assert state["cameras"] == ["front"]
    assert state["gopros"] == []
    client.post("/api/session/end")


def test_ws_state_includes_image_sources(client: TestClient):
    client.post("/api/session/start", json=_start_body())
    try:
        with client.websocket_connect("/ws/session") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "session_state"
            assert msg["data"]["image_sources"] == [
                {"slot": "front", "device": "mock_cam", "kind": "camera"}
            ]
    finally:
        client.post("/api/session/end")
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/unit/test_state_payload_image_sources.py -v
```

Expected: KeyError — `image_sources` not in payload.

- [ ] **Step 3: Update REST payload builder**

Edit `backend/mimicrec/api/routes/session.py`. In `build_state_payload`, find the `SessionStatePayload(...)` call. Add `image_sources` next to `gopros`:

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
        image_sources=meta.get("slot_assignments", []),
    ).model_dump()
```

- [ ] **Step 4: Update WS state builder**

Edit `backend/mimicrec/api/ws/session_hub.py`. In `_build_ws_state`, the non-idle return dict gets:

```python
        "image_sources": meta.get("slot_assignments", []),
```

inserted after `"preview_enabled"`.

- [ ] **Step 5: Run tests, verify they pass**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/unit/test_state_payload_image_sources.py -v
```

Expected: 2/2 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/mimicrec/api/routes/session.py backend/mimicrec/api/ws/session_hub.py tests/unit/test_state_payload_image_sources.py
git commit -m "feat(api): emit image_sources in REST and WS session_state payloads"
```

---

## Task 11: End-to-end integration — new dataset with slot_assignments

**Files:**
- Test: `tests/integration/test_slot_assignment_end_to_end.py`

Verifies that a new dataset opened with `slot_assignments` writes mp4s under the slot path and that a second session can change the device for the same slot.

- [ ] **Step 1: Write the test**

Create `tests/integration/test_slot_assignment_end_to_end.py`:

```python
from __future__ import annotations
import asyncio
import json
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_new_dataset_uses_slot_names_as_image_keys(tmp_path: Path):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir(parents=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = {
            "mode": "hand_teach",
            "dataset": "slot_ds",
            "task": "t",
            "robot": "mock",
            "fps": 30,
            "slot_assignments": [
                {"slot": "front", "device": "mock_cam"},
            ],
        }
        r = await ac.post("/api/session/start", json=body)
        assert r.status_code == 200, r.text
        # Schema endpoint reflects the slot, not the device basename
        r = await ac.get("/api/datasets/slot_ds/schema")
        assert r.status_code == 200
        assert r.json()["image_keys"] == ["front"]
        await ac.post("/api/session/end")


@pytest.mark.asyncio
async def test_second_session_can_swap_device_for_same_slot(tmp_path: Path):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir(parents=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # First session: front = mock_cam
        body1 = {
            "mode": "hand_teach", "dataset": "swap_ds", "task": "t", "robot": "mock", "fps": 30,
            "slot_assignments": [{"slot": "front", "device": "mock_cam"}],
        }
        r = await ac.post("/api/session/start", json=body1)
        assert r.status_code == 200, r.text
        await ac.post("/api/session/end")

        # Second session, same slot, different device
        body2 = {
            "mode": "hand_teach", "dataset": "swap_ds", "task": "t", "robot": "mock", "fps": 30,
            "slot_assignments": [{"slot": "front", "device": "mock_front"}],
        }
        r = await ac.post("/api/session/start", json=body2)
        assert r.status_code == 200, r.text
        # info.json schema unchanged — same slot
        r = await ac.get("/api/datasets/swap_ds/schema")
        assert r.json()["image_keys"] == ["front"]
        await ac.post("/api/session/end")


@pytest.mark.asyncio
async def test_second_session_with_different_slot_set_400(tmp_path: Path):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir(parents=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body1 = {
            "mode": "hand_teach", "dataset": "schema_strict_ds", "task": "t", "robot": "mock", "fps": 30,
            "slot_assignments": [{"slot": "front", "device": "mock_cam"}],
        }
        await ac.post("/api/session/start", json=body1)
        await ac.post("/api/session/end")

        body2 = {
            "mode": "hand_teach", "dataset": "schema_strict_ds", "task": "t", "robot": "mock", "fps": 30,
            "slot_assignments": [{"slot": "wrist", "device": "mock_cam"}],
        }
        r = await ac.post("/api/session/start", json=body2)
        assert r.status_code == 400, r.text
        assert "slot" in r.text.lower()
```

- [ ] **Step 2: Run tests, verify they pass**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/integration/test_slot_assignment_end_to_end.py -v
```

Expected: 3/3 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_slot_assignment_end_to_end.py
git commit -m "test(integration): slot_assignments end-to-end (new dataset, device swap, schema strict)"
```

---

## Task 12: Backward-compat shim integration test

**Files:**
- Test: `tests/integration/test_legacy_cameras_compat.py`

A request body with only the legacy `cameras` / `gopros` lists must still start a session.

- [ ] **Step 1: Write the test**

Create `tests/integration/test_legacy_cameras_compat.py`:

```python
from __future__ import annotations
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_legacy_cameras_only_body_starts_session(tmp_path: Path):
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    app.state.datasets_root = tmp_path / "datasets"
    app.state.datasets_root.mkdir(parents=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = {
            "mode": "hand_teach", "dataset": "legacy_ds", "task": "t", "robot": "mock", "fps": 30,
            "cameras": ["mock_cam"],   # legacy field
            # no slot_assignments
        }
        r = await ac.post("/api/session/start", json=body)
        assert r.status_code == 200, r.text
        # Image sources are populated by the shim (slot == device == "mock_cam")
        assert r.json()["image_sources"] == [
            {"slot": "mock_cam", "device": "mock_cam", "kind": "camera"}
        ]
        await ac.post("/api/session/end")
```

- [ ] **Step 2: Run test, verify it passes**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests/integration/test_legacy_cameras_compat.py -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_legacy_cameras_compat.py
git commit -m "test(integration): legacy cameras/gopros body still starts via shim"
```

---

## Task 13: Frontend hooks `useCameraRoles` + `useDatasetSchema`

**Files:**
- Modify: `frontend/src/api/queries.ts`
- Modify: `frontend/src/api/types.ts`

- [ ] **Step 1: Add `ImageSource` type**

Edit `frontend/src/api/types.ts`. Append:

```typescript
export interface ImageSource {
  slot: string;
  device: string;
  kind: "camera" | "gopro";
}
```

- [ ] **Step 2: Add hooks**

Edit `frontend/src/api/queries.ts`. Append:

```typescript
export function useCameraRoles() {
  return useQuery<{roles: string[]}>({
    queryKey: ["camera-roles"],
    queryFn: () => apiFetch<{roles: string[]}>("/api/configs/camera_roles"),
  });
}

export function useDatasetSchema(dataset: string | undefined) {
  return useQuery<{image_keys: string[]}>({
    queryKey: ["dataset-schema", dataset],
    queryFn: () => apiFetch<{image_keys: string[]}>(
      `/api/datasets/${dataset}/schema`,
    ),
    enabled: !!dataset,
  });
}
```

- [ ] **Step 3: Type-check**

```bash
npm --prefix frontend run build
```

Expected: clean build.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/queries.ts frontend/src/api/types.ts
git commit -m "feat(frontend): useCameraRoles + useDatasetSchema hooks + ImageSource type"
```

---

## Task 14: Frontend `record-form-store` adopts `slotAssignments`

**Files:**
- Modify: `frontend/src/state/record-form-store.ts`

- [ ] **Step 1: Refactor store**

Edit `frontend/src/state/record-form-store.ts`. Replace `selectedCams: string[]` and `selectedGopros: string[]` with `slotAssignments: SlotAssignmentDraft[]`:

```typescript
import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface SlotAssignmentDraft {
  slot: string;
  device: string;
}

export interface RecordFormDraft {
  mode: "teleop" | "hand_teach";
  robot: string;
  teleop: string;
  mapper: string;
  slotAssignments: SlotAssignmentDraft[];
  dataset: string;
  task: string;
  fps: number;
  autoCycle: boolean;
  autoDurationSec: number;
  autoReviewSec: number;
  previewEnabled: boolean;
}

interface RecordFormStore extends RecordFormDraft {
  set: (patch: Partial<RecordFormDraft>) => void;
  reset: () => void;
}

const DEFAULTS: RecordFormDraft = {
  mode: "teleop",
  robot: "",
  teleop: "",
  mapper: "",
  slotAssignments: [],
  dataset: "",
  task: "",
  fps: 30,
  autoCycle: false,
  autoDurationSec: 10,
  autoReviewSec: 3,
  previewEnabled: true,
};

export const useRecordFormStore = create<RecordFormStore>()(
  persist(
    (set) => ({
      ...DEFAULTS,
      set: (patch) => set(patch),
      reset: () => set(DEFAULTS),
    }),
    { name: "mimicrec-record-form" },
  ),
);
```

- [ ] **Step 2: Type-check**

```bash
npm --prefix frontend run build
```

The build will fail because `SessionConfigForm.tsx` references `selectedCams` / `selectedGopros`. Task 16 fixes the form. For this task only, also temporarily comment out the broken references in `SessionConfigForm.tsx` so `tsc` compiles. The form is fully rewritten in Task 16; this temporary breakage is expected and reverted by that task.

Concretely: in `SessionConfigForm.tsx`, find any `selectedCams` / `selectedGopros` reference and replace with a placeholder constant pointing to the new field:

```typescript
const selectedCams: string[] = [];  // TEMPORARY: removed by Task 16
const selectedGopros: string[] = [];  // TEMPORARY: removed by Task 16
```

Adjust the destructure on line 26 to drop `selectedCams` / `selectedGopros` from the form destructure too.

- [ ] **Step 3: Type-check again**

```bash
npm --prefix frontend run build
```

Expected: clean build.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/state/record-form-store.ts frontend/src/components/SessionConfigForm.tsx
git commit -m "feat(frontend): record-form-store moves to slotAssignments (form rewrite in next task)"
```

---

## Task 15: Frontend `session-store` adds `imageSources`

**Files:**
- Modify: `frontend/src/state/session-store.ts`

- [ ] **Step 1: Add `imageSources` to the store**

Edit `frontend/src/state/session-store.ts`. Add `imageSources: ImageSource[]` to the interface, default to `[]` in the create body, and hydrate from `data.image_sources` inside `setSessionState`:

```typescript
import type { EpisodeProgress, ImageSource, ReplayProgress } from "../api/types.ts";

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
  imageSources: ImageSource[];
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

Initial state adds `imageSources: []`, and `setSessionState` adds:

```typescript
      imageSources: (data.image_sources as ImageSource[] | undefined) ?? [],
```

- [ ] **Step 2: Type-check**

```bash
npm --prefix frontend run build
```

Expected: clean build.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/state/session-store.ts
git commit -m "feat(frontend): session-store holds imageSources hydrated from WS/REST"
```

---

## Task 16: Frontend `SessionConfigForm` slot-assignment UI

**Files:**
- Modify: `frontend/src/components/SessionConfigForm.tsx`

This task replaces the legacy multi-select blocks with the slot-row UI.

- [ ] **Step 1: Rewrite the camera section**

Edit `frontend/src/components/SessionConfigForm.tsx`. Imports gain:

```typescript
import { useCameraRoles, useConfigsWithContent, useDatasets, useDatasetSchema, useStartSession, useTasks } from "../api/queries.ts";
import type { SlotAssignmentDraft } from "../state/record-form-store.ts";
```

Inside the component, replace the cameras / gopros multi-select sections with the slot-row UI:

```typescript
  const { data: roles } = useCameraRoles();
  const { data: schema } = useDatasetSchema(datasetExists ? dataset : undefined);
  const cameraConfigs = useConfigsWithContent("cameras").data ?? [];
  const goproConfigs = useConfigsWithContent("gopros", { optional: true }).data ?? [];

  // Combined device options for the dropdown
  const deviceOptions = [
    ...cameraConfigs.map(c => ({name: c.name, kind: "camera" as const})),
    ...goproConfigs.map(g => ({name: g.name, kind: "gopro" as const})),
  ];

  // For existing datasets, force-display every dataset slot.
  // For new datasets, just show whatever the user has added.
  const datasetSlots = schema?.image_keys ?? [];
  const formSlots = form.slotAssignments.map(a => a.slot);
  const allSlotsToShow = datasetExists
    ? datasetSlots.map(slot => ({
        slot,
        device: form.slotAssignments.find(a => a.slot === slot)?.device ?? "",
        locked: true,
      }))
    : form.slotAssignments.map(a => ({...a, locked: false}));

  const setSlotDevice = (slot: string, device: string) => {
    const next = form.slotAssignments.filter(a => a.slot !== slot);
    if (device) next.push({slot, device});
    form.set({slotAssignments: next});
  };

  const addSlot = (slot: string) => {
    if (form.slotAssignments.some(a => a.slot === slot)) return;
    form.set({slotAssignments: [...form.slotAssignments, {slot, device: ""}]});
  };

  const removeSlot = (slot: string) => {
    form.set({slotAssignments: form.slotAssignments.filter(a => a.slot !== slot)});
  };

  const usedDevices = new Set(form.slotAssignments.map(a => a.device).filter(Boolean));
  const availableRoles = (roles?.roles ?? []).filter(r => !formSlots.includes(r));
  // Also surface legacy slot names from existing datasets that aren't in roles.yaml
  const legacySlots = datasetSlots.filter(s => !(roles?.roles ?? []).includes(s) && !formSlots.includes(s));
```

UI block (replace the `Cameras` and `GoPros` sections):

```tsx
      <div>
        <label className="block text-body-sm-medium text-charcoal mb-xs">
          Camera Assignments
        </label>
        <div className="flex flex-col gap-2">
          {allSlotsToShow.map(({slot, device, locked}) => (
            <div key={slot} className="flex items-center gap-2">
              <select
                disabled={locked}
                value={slot}
                className="..."
                onChange={() => { /* slot is fixed for existing rows */ }}
              >
                <option value={slot}>{slot}{legacySlots.includes(slot) ? " (legacy)" : ""}</option>
              </select>
              <select
                value={device}
                className="..."
                onChange={e => setSlotDevice(slot, e.target.value)}
              >
                <option value="">— none —</option>
                {deviceOptions.map(opt => (
                  <option
                    key={opt.name}
                    value={opt.name}
                    disabled={usedDevices.has(opt.name) && device !== opt.name}
                  >
                    {opt.name} ({opt.kind}){usedDevices.has(opt.name) && device !== opt.name ? " (in use)" : ""}
                  </option>
                ))}
              </select>
              {!locked && (
                <button type="button" onClick={() => removeSlot(slot)} className="...">
                  ✕
                </button>
              )}
            </div>
          ))}
          {!datasetExists && (
            <div className="flex items-center gap-2">
              <select
                value=""
                className="..."
                onChange={e => { if (e.target.value) addSlot(e.target.value); }}
              >
                <option value="">+ Add slot…</option>
                {availableRoles.map(r => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>
          )}
        </div>
      </div>
```

(Tailwind classes are intentionally elided to `"..."` — copy the same classes the surrounding form uses for `<Input>` / `<Button>` elements. Existing select styling examples are in `SessionConfigForm.tsx` for the `mode` SegmentedTabBar.)

`handleStart` body sends `slot_assignments`:

```typescript
    const body: Record<string, unknown> = {
      mode, dataset, task, robot, fps,
      slot_assignments: form.slotAssignments.map(a => ({slot: a.slot, device: a.device})),
      preview_enabled: previewEnabled,
    };
    if (mode === "teleop") {
      body.teleop = teleop;
      body.mapper = mapper;
    }
```

(Remove the legacy `cameras` / `gopros` body keys. Also remove the temporary placeholders inserted in Task 14.)

- [ ] **Step 2: Type-check**

```bash
npm --prefix frontend run build
```

Expected: clean build.

- [ ] **Step 3: Visual smoke**

```bash
npm --prefix frontend run dev
```

Open the Record page. Confirm:
- The Camera Assignments section renders below the form
- For a new dataset name: `+ Add slot` shows roles; each row's device dropdown shows cameras and gopros with the kind suffix
- Selecting the same device in two rows: the second row's dropdown disables that option with "(in use)"
- For an existing dataset name: rows are pre-populated from the schema endpoint and the slot dropdown is locked

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/SessionConfigForm.tsx
git commit -m "feat(frontend): SessionConfigForm camera assignment list UI"
```

---

## Task 17: Final verification

- [ ] **Step 1: Backend full sweep**

```bash
env -u PYTHONPATH ./backend/.venv/bin/python -m pytest tests -v --ignore=tests/integration/test_rebotarm_estop.py --ignore=tests/integration/test_rebotarm_replay_mode.py --ignore=tests/integration/test_rebotarm_session.py --ignore=tests/unit/test_rebotarm_adapter.py --ignore=tests/unit/test_rebotarm_adapter_proprio.py --ignore=tests/integration/test_inference_real_kinematics.py --ignore=tests/unit/test_inference_ik_service.py
```

The ignored tests fail in the current environment for reasons unrelated to this feature (missing `zmq` / `placo`). Confirm the rest passes.

- [ ] **Step 2: Frontend build**

```bash
npm --prefix frontend run build
```

Expected: clean.

- [ ] **Step 3: Manual smoke**

With the dev server running:

1. New dataset `slot_test_a`, slot `front` = `mock_cam`, slot `wrist` = `mock_front`. Start session → record one episode → save. Inspect `datasets/slot_test_a/meta/info.json`: `features` contains `observation.images.front` and `observation.images.wrist`.
2. Existing dataset `a3` (already has `wrist` + `gopro_external` image keys). Open session config: rows pre-fill for those two slots; slot dropdown is locked; device dropdown lets the operator pick a different physical device for each slot. Verify a session starts.
3. Try a legacy curl with only `cameras: ["mock_cam"]`:
   ```bash
   curl -X POST localhost:8000/api/session/start -H 'Content-Type: application/json' -d '{"mode":"hand_teach","dataset":"legacy_smoke","task":"t","robot":"mock","fps":30,"cameras":["mock_cam"]}'
   ```
   Confirm 200 OK and `image_sources` reflects the shim.

- [ ] **Step 4: No commit needed unless cleanup happened**

```bash
git status
```

If clean, done.

---

## Out of Scope (mirroring the spec)

- Migrating existing datasets' image keys to the global vocabulary.
- Removing the deprecated `cameras` / `gopros` fields from request / response schemas.
- Frontend migration from the `cameras`/`gopros` mirror to `image_sources` for tile rendering (the existing `episode.cameras` iteration path is unchanged).
- Mid-session changes to slot assignments.
- Drag-and-drop reordering of slot rows.
