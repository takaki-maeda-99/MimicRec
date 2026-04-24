# MimicRec Plan B — HTTP/WebSocket API Surface

## 1. Purpose

Expose the Plan A backend control core (`SessionManager`, datasets, configs) through a FastAPI REST + WebSocket API. No frontend — Plan C handles that.

## 2. Scope

**In scope:**
- FastAPI application with Uvicorn
- REST endpoints for session control, episode management, dataset operations, config listing
- WebSocket channels for session events, robot state streaming, camera preview
- Domain exception → HTTP status mapping
- Trajectory loading utility for replay
- API-level integration tests via `httpx.AsyncClient`

**Out of scope:**
- React frontend (Plan C)
- Real hardware adapters (remain stubs)
- Authentication / multi-user

## 3. Architecture

```
HTTP/WS clients
    │
    ▼
┌──────────────────────────────┐
│  FastAPI app (api/)          │
│  ├─ routes/session.py        │  POST /api/session/start, /end, /state
│  ├─ routes/episode.py        │  POST /api/episode/start, /stop, /save, /discard
│  ├─ routes/replay.py         │  POST /api/replay/start, /stop
│  ├─ routes/datasets.py       │  CRUD datasets, episodes, archive download
│  ├─ routes/configs.py        │  GET config listings
│  ├─ ws/session_hub.py        │  /ws/session — events, progress, errors
│  ├─ ws/state_hub.py          │  /ws/state — robot joint state @ 10-15 Hz
│  ├─ ws/camera_hub.py         │  /ws/cameras/{cam} — JPEG binary @ 10-15 Hz
│  ├─ errors.py                │  exception_handler registrations
│  ├─ schemas.py               │  Pydantic request/response models
│  ├─ deps.py                  │  Dependency injection (SessionManager, configs)
│  └─ app.py                   │  FastAPI() creation, lifespan, router includes
└──────────────────────────────┘
    │
    ▼
┌──────────────────────────────┐
│  Plan A domain layer         │
│  SessionManager, adapters,   │
│  CameraManager, datasets,    │
│  config loader               │
└──────────────────────────────┘
```

The API layer is a **thin translation wrapper**. It does not contain business logic — all state management, hardware control, and recording logic remain in the domain layer.

## 4. REST endpoints

### 4.1 Session control

| Method | Path | Body | Response | Domain call |
|--------|------|------|----------|-------------|
| `POST` | `/api/session/start` | `StartSessionRequest` | `SessionStatePayload` | Instantiate adapters from config, create `SessionManager`, call `.start()` |
| `POST` | `/api/session/end` | — | `SessionStatePayload` | `.end()`. If a recording is in progress, the in-progress episode is auto-discarded before shutdown. |
| `GET` | `/api/session/state` | — | `SessionStatePayload` | Read `session.state`, `session.mode`, etc. |
| `GET` | `/api/session/config` | — | JSON | Return resolved OmegaConf as dict |
| `GET` | `/api/health` | — | `{"status": "ok"}` | No domain call — always 200 |

### 4.2 Episode control

| Method | Path | Body | Response | Notes |
|--------|------|------|----------|-------|
| `POST` | `/api/episode/start` | — | `SessionStatePayload` | `.episode_start()`. Returns 409 if `replay_active` is true. |
| `POST` | `/api/episode/stop` | — | `SessionStatePayload` | `.episode_stop()` |
| `POST` | `/api/episode/save` | `SaveEpisodeRequest` | `SessionStatePayload` | `.episode_save(success, comment)` |
| `POST` | `/api/episode/discard` | — | `SessionStatePayload` | `.episode_discard()` |

### 4.3 Replay control

| Method | Path | Body | Response | Notes |
|--------|------|------|----------|-------|
| `POST` | `/api/replay/start` | `ReplayStartRequest` | `SessionStatePayload` | Loads trajectory via `load_replay_trajectory()` (new domain utility in `datasets/reader.py`), then calls `.replay_start(trajectory)` |
| `POST` | `/api/replay/stop` | — | `SessionStatePayload` | `.replay_stop()` |

### 4.4 Dataset operations

| Method | Path | Body / Query | Response | Domain call |
|--------|------|--------------|----------|-------------|
| `GET` | `/api/datasets` | — | `list[DatasetSummary]` | List dataset dirs, read each info.json |
| `POST` | `/api/datasets` | `CreateDatasetRequest` | `DatasetSummary` | `init_dataset(root, fps, joint_names, camera_names)` |
| `GET` | `/api/datasets/{ds}/episodes` | `?task&success&include_deleted` | `list[EpisodeSummary]` | `iter_episodes()` with filters |
| `GET` | `/api/datasets/{ds}/episodes/{idx}` | — | `EpisodeSummary` | Read single episode metadata |
| `DELETE` | `/api/datasets/{ds}/episodes/{idx}` | — | 204 | `tombstone_episode()` |
| `GET` | `/api/datasets/{ds}/tasks` | — | `list[TaskSummary]` | Read tasks parquet |
| `POST` | `/api/datasets/{ds}/tasks` | `{name, instruction}` | `TaskSummary` | `upsert_task()`, then re-read to build response |
| `GET` | `/api/datasets/{ds}/archive` | — | `StreamingResponse` | `build_archive_stream()`. Headers: `Content-Type: application/zip`, `Content-Disposition: attachment; filename="{ds}.zip"` |
| `GET` | `/api/datasets/{ds}/episodes/{idx}/video/{cam}` | — | `FileResponse` (mp4) | Serve MP4 file from dataset |
| `GET` | `/api/datasets/{ds}/episodes/{idx}/frames` | — | JSON | Read parquet, return time-series |

Note: video and frames endpoints are nested under `/api/datasets/{ds}/episodes/{idx}/` for consistency (differs from parent spec §11 which used `/api/episodes/`).

### 4.5 Config listings

Route paths use the actual disk directory names (singular for robot/teleop/mapper, plural for cameras):

| Method | Path | Disk directory | Response |
|--------|------|----------------|----------|
| `GET` | `/api/configs/robot` | `configs/robot/` | List YAML filenames (without extension) |
| `GET` | `/api/configs/teleop` | `configs/teleop/` | List YAML filenames |
| `GET` | `/api/configs/mapper` | `configs/mapper/` | List YAML filenames |
| `GET` | `/api/configs/cameras` | `configs/cameras/` | List YAML filenames |

## 5. WebSocket channels

### 5.1 `/ws/session` — session event stream

Low-rate, event-driven. Server sends JSON messages:

```json
{"type": "session_state", "data": {"state": "recording", "mode": "teleop", ...}}
{"type": "episode_progress", "data": {"num_frames": 42, "duration_sec": 1.4, ...}}
{"type": "replay_progress", "data": {"frame_index": 10, "total_frames": 300, "speed": 1.0}}
{"type": "error", "data": {"error": "HardwareError", "message": "camera front: timeout"}}
```

- `session_state`: emitted on every state transition. Also sent as the **first message on connect** (current state snapshot) to eliminate reconnection races.
- `episode_progress`: ~1 Hz during RECORDING (num_frames, duration_sec, stale_sample_count, writer_queue_depth, writer_lag_ms, ticks_skipped)
- `replay_progress`: ~2 Hz during REPLAYING (frame_index, total_frames, speed)
- `error`: on hardware/recording/replay errors from ErrorBus

**ErrorBus integration:** The session hub subscribes to `ErrorBus` via `error_bus.subscribe()` on startup. When an error event arrives, it is serialized as `{"type": "error", "data": {"error": type(e).__name__, "message": str(e)}}` and broadcast to all connected WebSocket clients.

### 5.2 `/ws/state` — robot joint state

10-15 Hz decimated from the control loop rate. JSON text messages:

```json
{"joint_pos": [0.1, 0.2, ...], "joint_vel": [...], "joint_effort": [...], "t_mono_ns": 12345}
```

Source: `robot_state_slot.peek()` polled by a dedicated broadcast task at the configured rate.

### 5.3 `/ws/cameras/{cam_name}` — camera preview

10-15 Hz. Binary WebSocket frames containing raw JPEG bytes (not base64). Each camera has its own channel so a stalled consumer on one camera doesn't block others.

Source: `CameraManager.subscribe_preview(cam_name)` queue.

## 6. Exception → HTTP mapping

Registered via `@app.exception_handler`:

| Domain Exception | HTTP Status | Semantics |
|------------------|-------------|-----------|
| `HandTeachNotSupportedError` | 422 | Unprocessable — robot can't do hand-teach |
| `InvalidTransitionError` | 409 | Conflict — wrong session state for this action (includes replay_active guard) |
| `HardwareError` | 500 | Internal — hardware fault |
| `RecorderError` | 500 | Internal — storage fault |
| `ReplaySafetyError` | 500 | Internal — safety trip (also emitted on /ws/session) |
| `FileNotFoundError` | 404 | Dataset or episode not found |
| `KeyError` (from tombstone) | 404 | Episode not found or already deleted |

Response body: `{"detail": str(exception)}`.

## 7. Dependency injection (`deps.py`)

- **`configs_root: Path`** — resolved from env var `MIMICREC_CONFIGS_ROOT` or default `configs/`
- **`datasets_root: Path`** — resolved from env var `MIMICREC_DATASETS_ROOT` or default `datasets/`
- **`session_manager: SessionManager | None`** — singleton, created on `POST /session/start`, cleared on `POST /session/end`. Routes that require an active session use a `get_session_manager()` dependency that returns 409 if no session is active.

### Adapter instantiation

`POST /api/session/start` receives config names (e.g., `robot: "mock"`, `teleop: "mock_leader"`). The API layer:

1. Loads the session config via `load_session_config()` using the session YAML that matches the request's robot/teleop/mapper/cameras combination
2. Instantiates adapters by resolving `_target_` from the config (simple `importlib.import_module` + `getattr` — no Hydra)
3. Creates `CameraManager` with the instantiated cameras
4. Extracts `ReplaySafetyConfig` from the robot config's `replay:` block (if present)
5. Creates `SessionManager` with all components
6. Calls `session_manager.start()`

This instantiation logic lives in `deps.py` as a helper function `create_session_from_request()`.

### Trajectory loading

`POST /api/replay/start` needs to convert a saved episode's parquet data into a `ReplayTrajectory`. This is implemented as a new domain utility `load_replay_trajectory(ds_root, episode_idx) -> ReplayTrajectory` in `datasets/reader.py`. It reads the episode's parquet, extracts the `action.joint_pos` column, and wraps it in `ReplayTrajectory(joint_targets=...)`. This keeps business logic in the domain layer, not the API route handler.

## 8. Application lifecycle (`app.py`)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: nothing special (session created on-demand)
    yield
    # Shutdown: end active session if any
    if getattr(app.state, "session_manager", None):
        await app.state.session_manager.end()
```

## 9. Pydantic models (`schemas.py`)

### StartSessionRequest — discriminated union

Following the parent spec §11.3, the request uses a discriminated union so that `teleop` and `mapper` are required for TELEOP mode and absent for HAND_TEACH mode. Validation happens at deserialization time, not runtime.

```python
class _BaseSessionRequest(BaseModel):
    dataset: str
    task: str
    robot: str
    cameras: list[str]
    fps: int = 30

class TeleopSessionRequest(_BaseSessionRequest):
    mode: Literal[SessionMode.TELEOP] = SessionMode.TELEOP
    teleop: str
    mapper: str

class HandTeachSessionRequest(_BaseSessionRequest):
    mode: Literal[SessionMode.HAND_TEACH] = SessionMode.HAND_TEACH

StartSessionRequest = Annotated[
    TeleopSessionRequest | HandTeachSessionRequest,
    Field(discriminator="mode"),
]
```

### Other models

```python
class SaveEpisodeRequest(BaseModel):
    success: bool | None = None
    comment: str | None = None

class ReplayStartRequest(BaseModel):
    dataset: str
    episode_idx: int
    speed: float = Field(default=1.0, ge=0.1, le=5.0)  # bounded for safety

class CreateDatasetRequest(BaseModel):
    name: str
    fps: int = 30
    joint_names: list[str] = []
    camera_names: list[str] = []

class SessionStatePayload(BaseModel):
    state: SessionState
    sub_state: SubState | None = None
    mode: SessionMode | None = None
    dataset: str | None = None
    task: str | None = None
    robot: str | None = None
    teleop: str | None = None
    mapper: str | None = None
    cameras: list[str] = []
    fps: int | None = None

class DatasetSummary(BaseModel):
    name: str
    num_episodes: int
    total_frames: int

class EpisodeSummary(BaseModel):
    episode_index: int
    task: str
    duration_sec: float
    num_frames: int
    success: bool | None
    robot: str
    teleop: str | None
    mode: str
    recorded_at: str | None = None  # ISO 8601 wall-clock timestamp

class TaskSummary(BaseModel):
    task_index: int
    task: str
    instruction: str | None = None

class ErrorPayload(BaseModel):
    detail: str
```

## 10. Domain layer additions for Plan B

Small additions to Plan A code needed by the API:

1. **`datasets/reader.py`** — add `load_replay_trajectory(ds_root, episode_idx) -> ReplayTrajectory` that reads parquet and extracts joint trajectory
2. **`datasets/reader.py`** — add `read_dataset_info(ds_root) -> dict` that reads and returns `info.json`
3. **`session/lifecycle.py`** — add `recorded_at` (wall-clock ISO timestamp via `datetime.utcnow().isoformat()`) to the metadata dict in `episode_save()`

These are minimal, targeted additions — not refactors.

## 11. File structure

```
backend/mimicrec/api/
    __init__.py
    app.py              # FastAPI creation, lifespan, router includes
    deps.py             # get_session_manager, get_configs_root, adapter instantiation
    schemas.py          # Pydantic request/response models
    errors.py           # exception handlers
    routes/
        __init__.py
        session.py      # /api/session/*
        episode.py      # /api/episode/*
        replay.py       # /api/replay/*
        datasets.py     # /api/datasets/*
        configs.py      # /api/configs/*
    ws/
        __init__.py
        session_hub.py  # /ws/session
        state_hub.py    # /ws/state
        camera_hub.py   # /ws/cameras/{cam}
tests/
    api/
        __init__.py
        conftest.py     # shared fixtures (mock SessionManager, test app)
        test_session_routes.py
        test_episode_routes.py
        test_replay_routes.py
        test_dataset_routes.py
        test_config_routes.py
        test_ws_session.py
        test_ws_state.py
        test_ws_camera.py
        test_error_mapping.py
```

## 12. Testing strategy

- Use `httpx.AsyncClient` with FastAPI's ASGI app (no real server needed)
- Mock adapters (same ones from Plan A) wired into a real `SessionManager`
- WebSocket tests use `httpx_ws` or FastAPI's built-in WebSocket test client
- All Plan A tests (55) remain unchanged and must still pass
- New tests cover:
  - REST endpoint happy paths and error cases
  - Domain exception → HTTP status mapping
  - WebSocket message delivery (including first-message snapshot on connect)
  - Session lifecycle through HTTP (start → episode → save → end)
  - Archive download streaming

## 13. Dependencies to add

```toml
# in backend/pyproject.toml
dependencies = [
    ...,
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "httpx>=0.27",          # for TestClient
]
```

## 14. Exit criteria

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
