# MimicRec Plan B — HTTP/WebSocket API Surface

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI REST + WebSocket API layer on top of the Plan A domain core, enabling HTTP clients to control sessions, record episodes, manage datasets, and stream live data — validated end-to-end against mock adapters.

**Architecture:** Thin API wrapper. FastAPI routes call `SessionManager` methods; exception handlers translate domain errors to HTTP status codes; WebSocket hubs bridge `LatestValue` slots and `ErrorBus` to connected clients. No business logic in the API layer.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, Pydantic v2, httpx (testing), pytest + pytest-asyncio.

**Spec:** [docs/superpowers/specs/2026-04-25-mimicrec-plan-b-api-surface.md](../specs/2026-04-25-mimicrec-plan-b-api-surface.md)

---

## Scope boundary

**This plan covers Plan B only: HTTP/WebSocket API surface.**

- **Plan B does:** FastAPI app, REST routes, WebSocket hubs, Pydantic schemas, exception mapping, adapter instantiation from config, trajectory loading, API-level tests.
- **Plan B does NOT:** React frontend (Plan C), real hardware wiring (Plan D).

## Exit criteria

1. `GET /api/health` → 200
2. `POST /api/session/start` with mock config → 200, session in READY
3. Full episode cycle via HTTP: start → episode/start → episode/stop → episode/save → parquet exists
4. `DELETE /api/datasets/{ds}/episodes/{idx}` → 204, episode tombstoned
5. `GET /api/datasets/{ds}/archive` → valid zip stream without tombstoned episodes
6. `/ws/session` receives `session_state` events on transitions (including snapshot on connect)
7. `/ws/cameras/{cam}` delivers JPEG binary frames
8. `HandTeachNotSupportedError` on SO-101 hand-teach → HTTP 422
9. `InvalidTransitionError` on bad transition → HTTP 409
10. `ReplayStartRequest` with `speed=0` → 422 (validation)
11. All 55 Plan A tests still pass

## File structure

### Source tree (new files, all under `backend/mimicrec/api/`)

```
backend/mimicrec/api/
    __init__.py
    app.py                  # FastAPI(), lifespan, include_router calls
    deps.py                 # get_session_manager(), get_configs_root(), get_datasets_root(),
                            # create_session_from_request(), instantiate_adapter()
    schemas.py              # All Pydantic request/response models
    errors.py               # @app.exception_handler registrations
    routes/
        __init__.py
        session.py          # /api/session/start, /end, /state, /config, /health
        episode.py          # /api/episode/start, /stop, /save, /discard
        replay.py           # /api/replay/start, /stop
        datasets.py         # /api/datasets CRUD, archive, video, frames
        configs.py          # /api/configs/{group}
    ws/
        __init__.py
        session_hub.py      # /ws/session — state transitions, progress, errors
        state_hub.py        # /ws/state — robot joint state polling
        camera_hub.py       # /ws/cameras/{cam} — JPEG preview relay
```

### Modified Plan A files

```
backend/mimicrec/datasets/reader.py     # add load_replay_trajectory(), read_dataset_info()
backend/mimicrec/session/lifecycle.py    # add recorded_at to episode_save metadata
backend/pyproject.toml                  # add fastapi, uvicorn, httpx deps
```

### Test tree

```
tests/api/
    __init__.py
    conftest.py                 # shared app fixture, mock session helpers
    test_session_routes.py
    test_episode_routes.py
    test_dataset_routes.py
    test_config_routes.py
    test_replay_routes.py
    test_error_mapping.py
    test_ws_session.py
    test_ws_state.py
    test_ws_camera.py
```

## Conventions

- **TDD throughout.** Every task writes a failing test first.
- **Every task ends with a commit.** Commit message format: `planB: <short imperative>`.
- **Imports always absolute** (`from mimicrec.api.schemas import ...`).
- **All Plan A tests must remain green** after every commit.

---

## Task 0 — Dependencies and app scaffold

**Goal:** Add FastAPI/uvicorn/httpx to pyproject.toml, create the empty `api/` package with a health endpoint, verify the app starts.

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/mimicrec/api/__init__.py`
- Create: `backend/mimicrec/api/app.py`
- Create: `backend/mimicrec/api/schemas.py` (empty initially)
- Create: `backend/mimicrec/api/errors.py` (empty initially)
- Create: `backend/mimicrec/api/deps.py` (empty initially)
- Create: `backend/mimicrec/api/routes/__init__.py`
- Create: `backend/mimicrec/api/routes/session.py`
- Create: `backend/mimicrec/api/ws/__init__.py`
- Create: `tests/api/__init__.py`
- Create: `tests/api/conftest.py`
- Create: `tests/api/test_session_routes.py`

- [ ] **Step 0.1: Add dependencies to `backend/pyproject.toml`**

Add `fastapi>=0.115`, `uvicorn[standard]>=0.30` to `dependencies`, and `httpx>=0.27`, `httpx-ws>=0.6` to `dev`.

- [ ] **Step 0.2: Install updated deps**

```bash
uv pip install --python .venv/bin/python -e "./backend[dev]"
```

- [ ] **Step 0.3: Write minimal `app.py` with health endpoint**

```python
# backend/mimicrec/api/app.py
from __future__ import annotations
from contextlib import asynccontextmanager

from fastapi import FastAPI

from mimicrec.api.routes import session


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    sm = getattr(app.state, "session_manager", None)
    if sm:
        await sm.end()


def create_app() -> FastAPI:
    app = FastAPI(title="MimicRec", version="0.1.0", lifespan=lifespan)
    app.state.session_manager = None
    app.state.error_bus = None
    app.state.camera_manager = None
    app.state.resolved_config = None
    app.state.session_meta = None  # {dataset, task, robot, teleop, mapper, cameras, fps}
    app.include_router(session.router, prefix="/api")
    return app
```

- [ ] **Step 0.4: Write session router with health endpoint**

```python
# backend/mimicrec/api/routes/session.py
from __future__ import annotations
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 0.5: Create empty `__init__.py` files and conftest**

Create all `__init__.py` for api/, api/routes/, api/ws/, tests/api/.

Note: `pytest.ini` already has `asyncio_mode = auto`, so no `@pytest.mark.asyncio` needed.

```python
# tests/api/conftest.py
from __future__ import annotations
from pathlib import Path
import pytest
from mimicrec.api.app import create_app


REPO_ROOT = Path(__file__).resolve().parents[2]  # MimicRec/


@pytest.fixture
def app():
    a = create_app()
    a.state.configs_root = REPO_ROOT / "configs"
    a.state.datasets_root = None  # tests set this via tmp_path
    return a
```

- [ ] **Step 0.6: Write test**

```python
# tests/api/test_session_routes.py
from httpx import AsyncClient, ASGITransport


async def test_health_returns_ok(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 0.7: Run tests**

```bash
bash scripts/test.sh tests/ -q
```

Expected: 56 passed (55 Plan A + 1 health).

- [ ] **Step 0.8: Commit**

```bash
git add backend/pyproject.toml backend/mimicrec/api tests/api
git commit -m "planB: scaffold FastAPI app with health endpoint"
```

---

## Task 1 — Pydantic schemas and exception handlers

**Goal:** Define all request/response models and wire up domain exception → HTTP status mapping.

**Files:**
- Create: `backend/mimicrec/api/schemas.py`
- Create: `backend/mimicrec/api/errors.py`
- Create: `tests/api/test_error_mapping.py`

- [ ] **Step 1.1: Write `schemas.py`**

All models from spec §9: `_BaseSessionRequest`, `TeleopSessionRequest`, `HandTeachSessionRequest`, `StartSessionRequest` (discriminated union), `SaveEpisodeRequest`, `ReplayStartRequest`, `CreateDatasetRequest`, `CreateTaskRequest` (name: str, instruction: str), `SessionStatePayload`, `DatasetSummary`, `EpisodeSummary`, `TaskSummary`, `ErrorPayload`.

- [ ] **Step 1.2: Write `errors.py`**

```python
# backend/mimicrec/api/errors.py
from __future__ import annotations
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mimicrec.errors import (
    HandTeachNotSupportedError, InvalidTransitionError,
    HardwareError, RecorderError, ReplaySafetyError,
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HandTeachNotSupportedError)
    async def _(req: Request, exc: HandTeachNotSupportedError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(InvalidTransitionError)
    async def _(req: Request, exc: InvalidTransitionError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(HardwareError)
    async def _(req: Request, exc: HardwareError):
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.exception_handler(RecorderError)
    async def _(req: Request, exc: RecorderError):
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.exception_handler(ReplaySafetyError)
    async def _(req: Request, exc: ReplaySafetyError):
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.exception_handler(FileNotFoundError)
    async def _(req: Request, exc: FileNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(KeyError)
    async def _(req: Request, exc: KeyError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})
```

- [ ] **Step 1.3: Register handlers in `app.py`**

Add `register_exception_handlers(app)` in `create_app()`.

- [ ] **Step 1.4: Write failing test for exception mapping**

```python
# tests/api/test_error_mapping.py
# Create a test route that raises each domain exception, verify HTTP status
```

Test that a route raising `InvalidTransitionError` returns 409, `HandTeachNotSupportedError` returns 422, etc.

- [ ] **Step 1.5: Run tests, verify pass**

```bash
bash scripts/test.sh tests/ -q
```

- [ ] **Step 1.6: Commit**

```bash
git add backend/mimicrec/api/schemas.py backend/mimicrec/api/errors.py \
    backend/mimicrec/api/app.py tests/api/test_error_mapping.py
git commit -m "planB: Pydantic schemas and exception-to-HTTP mapping"
```

---

## Task 2 — Dependency injection and adapter instantiation

**Goal:** Implement `deps.py` with `create_session_from_request()` that resolves config names to adapter instances, creates a `SessionManager`, and wires it into `app.state`.

**Files:**
- Create: `backend/mimicrec/api/deps.py`
- Modify: `backend/mimicrec/api/routes/session.py`
- Create: `tests/api/test_session_routes.py` (expand)

- [ ] **Step 2.1: Implement `deps.py`**

```python
# Key functions:
# get_configs_root(app) -> Path
# get_datasets_root(app) -> Path
# get_session_manager(app) -> SessionManager  (raises InvalidTransitionError if None)
# get_session_manager_or_none(app) -> SessionManager | None  (for /session/state, WS hubs)
# instantiate_adapter(target_str, **kwargs) -> object
# create_session_from_request(app, request, datasets_root) -> SessionManager
```

`instantiate_adapter` does: split `_target_` on last dot → `importlib.import_module(module_path)`, `getattr(module, class_name)`, then calls the constructor with kwargs from config.

**`create_session_from_request` concrete logic:**

The function does NOT use `load_session_config()` (which expects a session YAML path). Instead, it loads individual sub-configs directly:

```python
async def create_session_from_request(app, req, datasets_root: Path) -> SessionManager:
    configs_root = get_configs_root(app)
    
    # 1. Load individual configs
    robot_cfg = OmegaConf.load(configs_root / "robot" / f"{req.robot}.yaml")
    robot = instantiate_adapter(robot_cfg._target_)
    
    teleop = None
    mapper = None
    if hasattr(req, "teleop"):  # TeleopSessionRequest
        teleop_cfg = OmegaConf.load(configs_root / "teleop" / f"{req.teleop}.yaml")
        teleop = instantiate_adapter(teleop_cfg._target_, dof=teleop_cfg.get("dof", robot.dof))
        mapper_cfg = OmegaConf.load(configs_root / "mapper" / f"{req.mapper}.yaml")
        mapper = instantiate_adapter(mapper_cfg._target_)
    
    # 2. Cameras
    cams = {}
    for cam_name in req.cameras:
        cam_cfg = OmegaConf.load(configs_root / "cameras" / f"{cam_name}.yaml")
        cams[cam_name] = instantiate_adapter(cam_cfg._target_, name=cam_name,
            width=cam_cfg.get("width", 64), height=cam_cfg.get("height", 48))
    
    error_bus = ErrorBus()
    cm = CameraManager(cameras=cams, error_bus=error_bus)
    
    # 3. Replay safety (dof from robot.dof, dt_sec from 1/fps)
    replay_safety = None
    if "replay" in robot_cfg:
        replay_safety = ReplaySafetyConfig.from_robot_cfg(
            robot_cfg, dof=robot.dof, dt_sec=1.0 / req.fps)
    
    # 4. Dataset
    ds_root = datasets_root / req.dataset
    if not ds_root.exists():
        init_dataset(ds_root, fps=req.fps,
            joint_names=robot.joint_names, camera_names=req.cameras)
    
    # 5. Build resolved config snapshot
    resolved = OmegaConf.to_container(OmegaConf.create({
        "robot": OmegaConf.to_container(robot_cfg),
        "cameras": {n: OmegaConf.to_container(OmegaConf.load(
            configs_root / "cameras" / f"{n}.yaml")) for n in req.cameras},
    }))
    
    return SessionManager(
        dataset_root=ds_root, robot=robot, teleop=teleop, mapper=mapper,
        cameras=cm, mode=req.mode, fps=req.fps, error_bus=error_bus,
        resolved_config=resolved, replay_safety=replay_safety,
    )
```

Store `error_bus`, `camera_manager`, session metadata in `app.state` for use by WS hubs.

- [ ] **Step 2.2: Implement session routes: start, end, state, config**

```python
# backend/mimicrec/api/routes/session.py
@router.post("/session/start")
async def session_start(request: Request, body: StartSessionRequest):
    sm = await create_session_from_request(request.app, body)
    await sm.start()
    request.app.state.session_manager = sm
    return build_state_payload(request.app)

@router.post("/session/end")
async def session_end(request: Request):
    sm = get_session_manager(request.app)
    await sm.end()
    request.app.state.session_manager = None
    return build_state_payload(request.app)

@router.get("/session/state")
async def session_state(request: Request):
    # Must tolerate None session_manager — returns state: "idle" when no session
    return build_state_payload(request.app)

@router.get("/session/config")
async def session_config(request: Request):
    cfg = request.app.state.resolved_config
    if cfg is None:
        raise InvalidTransitionError("no active session")
    return cfg

# build_state_payload reads app.state.session_manager and app.state.session_meta.
# When session_manager is None, returns {"state": "idle", all other fields null/empty}.
# When active, reads session.state, session.mode, and session_meta for dataset/task/etc.
```

- [ ] **Step 2.3: Write failing test for session start/end**

Test that `POST /api/session/start` with a teleop mock config returns 200 with `state: "ready"`, and `POST /api/session/end` returns `state: "idle"`.

- [ ] **Step 2.4: Run tests, verify pass**

- [ ] **Step 2.5: Commit**

```bash
git commit -m "planB: dependency injection and session start/end routes"
```

---

## Task 3 — Episode and replay routes

**Goal:** Wire up episode/start, /stop, /save, /discard and replay/start, /stop routes.

**Files:**
- Create: `backend/mimicrec/api/routes/episode.py`
- Create: `backend/mimicrec/api/routes/replay.py`
- Modify: `backend/mimicrec/datasets/reader.py` (add `load_replay_trajectory`, `read_dataset_info`)
- Modify: `backend/mimicrec/session/lifecycle.py` (add `recorded_at` to episode_save)
- Create: `tests/api/test_episode_routes.py`
- Create: `tests/api/test_replay_routes.py`

- [ ] **Step 3.1: Add domain utilities**

In `datasets/reader.py`, add:
```python
def load_replay_trajectory(ds_root: Path, episode_idx: int) -> ReplayTrajectory:
    """Read episode parquet and extract joint trajectory."""
    from mimicrec.session.replay import ReplayTrajectory
    from mimicrec.recording.dataset_layout import dataset_paths, resolve_chunk
    import pyarrow.parquet as pq
    import numpy as np
    paths = dataset_paths(ds_root)
    chunk = resolve_chunk(episode_idx)
    pq_path = paths.episode_parquet(chunk, episode_idx)
    if not pq_path.exists():
        raise FileNotFoundError(f"episode {episode_idx} parquet not found")
    table = pq.read_table(pq_path)
    joint_pos = np.stack(table.column("action.joint_pos").to_pylist())
    return ReplayTrajectory(joint_targets=joint_pos.astype(np.float32))

def read_dataset_info(ds_root: Path) -> dict:
    import json
    info_path = ds_root / "meta" / "info.json"
    if not info_path.exists():
        raise FileNotFoundError(f"info.json not found at {info_path}")
    return json.loads(info_path.read_text())
```

In `session/lifecycle.py` `episode_save()`, add `"recorded_at": datetime.utcnow().isoformat()` to metadata_extra dict.

- [ ] **Step 3.2: Implement episode routes**

```python
# backend/mimicrec/api/routes/episode.py
@router.post("/episode/start")
@router.post("/episode/stop")
@router.post("/episode/save")
@router.post("/episode/discard")
```

Each calls the corresponding `SessionManager` method and returns `SessionStatePayload`.

- [ ] **Step 3.3: Implement replay routes**

```python
# backend/mimicrec/api/routes/replay.py
@router.post("/replay/start")  # loads trajectory, calls sm.replay_start()
@router.post("/replay/stop")   # calls sm.replay_stop()
```

- [ ] **Step 3.4: Write failing test for full episode cycle via HTTP**

```python
async def test_full_episode_cycle(app, tmp_path):
    # POST /session/start → 200
    # POST /episode/start → 200, state == "recording"
    # POST /episode/stop → 200, state == "review"
    # POST /episode/save → 200, state == "ready"
    # Verify parquet exists
    # POST /session/end → 200, state == "idle"
```

- [ ] **Step 3.5: Write failing test for replay routes**

- [ ] **Step 3.6: Run tests, verify pass**

- [ ] **Step 3.7: Commit**

```bash
git commit -m "planB: episode and replay routes with trajectory loading"
```

---

## Task 4 — Dataset and config routes

**Goal:** Wire up dataset CRUD, episode listing/deletion, archive download, and config listings.

**Files:**
- Create: `backend/mimicrec/api/routes/datasets.py`
- Create: `backend/mimicrec/api/routes/configs.py`
- Create: `tests/api/test_dataset_routes.py`
- Create: `tests/api/test_config_routes.py`

- [ ] **Step 4.1: Implement dataset routes**

```python
# GET /api/datasets — list dirs under datasets_root, read info.json for each
# POST /api/datasets — create dataset via init_dataset()
# GET /api/datasets/{ds}/episodes — iter_episodes with query filters
# GET /api/datasets/{ds}/episodes/{idx} — single episode lookup
# DELETE /api/datasets/{ds}/episodes/{idx} — tombstone_episode()
# GET /api/datasets/{ds}/tasks — read tasks parquet
# POST /api/datasets/{ds}/tasks — upsert_task()
# GET /api/datasets/{ds}/archive — StreamingResponse wrapping build_archive_stream()
#   into a zipfile: write to io.BytesIO, use zipfile.ZipFile, yield chunks.
#   Set Content-Type: application/zip, Content-Disposition: attachment; filename="{ds}.zip"
# GET /api/datasets/{ds}/episodes/{idx}/video/{cam} — FileResponse
# GET /api/datasets/{ds}/episodes/{idx}/frames — JSON time-series
```

- [ ] **Step 4.2: Implement config routes**

```python
# GET /api/configs/{group} — list YAML filenames in configs/{group}/
@router.get("/configs/{group}")
async def list_configs(group: str, request: Request):
    configs_root = get_configs_root(request.app)
    group_dir = configs_root / group
    if not group_dir.is_dir():
        raise FileNotFoundError(f"config group '{group}' not found")
    return [p.stem for p in sorted(group_dir.glob("*.yaml"))]
```

- [ ] **Step 4.3: Write failing tests for dataset CRUD**

Test create dataset, list datasets, list episodes, delete episode (tombstone), archive download.

- [ ] **Step 4.4: Write failing test for config listing**

Test that `GET /api/configs/robot` returns `["mock"]`.

- [ ] **Step 4.5: Run tests, verify pass**

- [ ] **Step 4.6: Commit**

```bash
git commit -m "planB: dataset CRUD, archive download, config listing routes"
```

---

## Task 5 — WebSocket session hub

**Goal:** Implement `/ws/session` that broadcasts state transitions, episode progress, replay progress, and errors.

**Files:**
- Create: `backend/mimicrec/api/ws/session_hub.py`
- Create: `tests/api/test_ws_session.py`

- [ ] **Step 5.1: Implement session hub**

The hub maintains a set of connected WebSocket clients. Uses **polling** (not event-driven) since `Session.state` is a plain attribute:

- A polling loop runs at ~5 Hz, compares `session.state` to last known state. On change, emits `session_state` event.
- During RECORDING, polls `Metrics` at ~1 Hz for `episode_progress`.
- Subscribes to `ErrorBus` via `error_bus.subscribe()` in a separate `asyncio.Task` that drains the queue and broadcasts errors as `{"type": "error", "data": {"error": type(e).__name__, "message": str(e)}}`.

On connect, sends the current state as the first message (snapshot).

```python
# backend/mimicrec/api/ws/session_hub.py
from __future__ import annotations
import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

@router.websocket("/ws/session")
async def ws_session(websocket: WebSocket):
    await websocket.accept()
    app = websocket.app
    sm = getattr(app.state, "session_manager", None)
    # Send current state snapshot
    await websocket.send_json({"type": "session_state", "data": _build_state(app)})
    # ... polling loop
```

- [ ] **Step 5.2: Register ws router in `app.py`**

- [ ] **Step 5.3: Write failing test**

Test that connecting to `/ws/session` receives a `session_state` message with `state: "idle"`. Then start a session via REST and verify a `session_state` event with `state: "ready"` arrives.

- [ ] **Step 5.4: Run tests, verify pass**

- [ ] **Step 5.5: Commit**

```bash
git commit -m "planB: WebSocket session hub with state transitions and error relay"
```

---

## Task 6 — WebSocket robot state and camera hubs

**Goal:** Implement `/ws/state` (robot joint state at 10-15 Hz) and `/ws/cameras/{cam}` (JPEG preview).

**Files:**
- Create: `backend/mimicrec/api/ws/state_hub.py`
- Create: `backend/mimicrec/api/ws/camera_hub.py`
- Create: `tests/api/test_ws_state.py`
- Create: `tests/api/test_ws_camera.py`

- [ ] **Step 6.1: Implement state hub**

Polls `robot_state_slot.peek()` at ~15 Hz and sends JSON to connected clients.

```python
@router.websocket("/ws/state")
async def ws_state(websocket: WebSocket):
    await websocket.accept()
    sm = get_session_manager_or_none(websocket.app)
    while True:
        if sm:
            s = sm._robot_state_slot.peek()
            if s:
                await websocket.send_json({
                    "joint_pos": s.value.joint_pos.tolist(),
                    "joint_vel": s.value.joint_vel.tolist(),
                    "joint_effort": s.value.joint_effort.tolist(),
                    "t_mono_ns": s.t_mono_ns,
                })
        await asyncio.sleep(1/15)
```

- [ ] **Step 6.2: Implement camera hub**

Subscribes to `CameraManager.subscribe_preview(cam_name)` and relays JPEG bytes as binary WebSocket frames.

```python
@router.websocket("/ws/cameras/{cam_name}")
async def ws_camera(websocket: WebSocket, cam_name: str):
    await websocket.accept()
    cm = getattr(websocket.app.state, "camera_manager", None)
    if not cm:
        await websocket.close(code=1008, reason="no active session")
        return
    q = cm.subscribe_preview(cam_name)
    while True:
        jpg = await q.get()
        await websocket.send_bytes(jpg)
```

- [ ] **Step 6.3: Register both WS routers in `app.py`**

- [ ] **Step 6.4: Write failing test for `/ws/state`**

Start a session, connect to `/ws/state`, receive at least one message with `joint_pos`.

- [ ] **Step 6.5: Write failing test for `/ws/cameras/{cam}`**

Start a session with a mock camera, connect to `/ws/cameras/front`, receive binary JPEG data.

- [ ] **Step 6.6: Run tests, verify pass**

- [ ] **Step 6.7: Commit**

```bash
git commit -m "planB: WebSocket robot state and camera preview hubs"
```

---

## Task 7 — Exit-criteria test suite

**Goal:** Write targeted tests that map 1:1 to the Plan B exit criteria.

**Files:**
- Create: `tests/api/test_exit_criteria.py`

- [ ] **Step 7.1: Write all exit-criteria tests**

```python
# 1. GET /api/health → 200
# 2. POST /api/session/start → 200, state == "ready"
# 3. Full cycle: start → episode/start → stop → save → parquet exists
# 4. DELETE episode → 204, tombstoned
# 5. GET archive → valid zip without deleted episodes
# 6. /ws/session receives state events (including snapshot on connect)
# 7. /ws/cameras/{cam} delivers JPEG binary
# 8. SO-101 hand-teach → 422
# 9. Invalid transition → 409
# 10. speed=0 → 422 validation
# 11. All Plan A tests still pass (verified by running full suite)
```

- [ ] **Step 7.2: Run full test suite**

```bash
bash scripts/test.sh tests/ -v
bash scripts/test.sh tests/api/test_exit_criteria.py -v
```

- [ ] **Step 7.3: Commit**

```bash
git commit -m "planB: exit-criteria test suite"
```

---

## Task 8 — Final cleanup

**Goal:** Verify all tests pass, check for any gaps.

- [ ] **Step 8.1: Run full suite 5 times**

```bash
for i in 1 2 3 4 5; do bash scripts/test.sh tests/ -q 2>&1 | tail -1; done
```

- [ ] **Step 8.2: Verify Plan A tests unaffected**

```bash
bash scripts/test.sh tests/unit tests/integration tests/exit_criteria -v
```

- [ ] **Step 8.3: Commit any remaining fixes**

```bash
git commit -m "planB: cleanup and flake audit"
```
