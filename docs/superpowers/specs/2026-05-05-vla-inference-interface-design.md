# VLA Inference Interface

**Date:** 2026-05-05
**Status:** Draft (pending spec review + user approval)
**Scope:** Add a closed-loop VLA inference mode to MimicRec. The app calls a self-hosted Vision-Language-Action HTTP server (initially the user's `vla-gemma-4` Gemma-VLA), receives action chunks (ΔEE pose + gripper), runs them on a real robot (SO-101 first, reBot deferred), records rollouts as datasets, and exposes a new `InferencePage` UI.

## 1. Purpose

The user wants MimicRec to act as the **operator-facing interface to a VLA inference API**. Today the app records human demos (teleop) and replays them; this spec adds a third mode where the action source is a VLA model, with the rest of the existing pipeline (cameras, robot adapters, dispatcher, recording) reused.

The VLA contract must be **YAML-configurable** (not hardcoded) so the user can iterate on server I/O without code changes, and so future models (OpenVLA, π0, etc.) can be wired in by editing a config file.

The action format is **6-dim ΔEE pose + 1-dim gripper** (7-dim total), which biases toward cross-robot transferability — the same model can be moved from SO-101 to reBot if both have IK that accepts EE deltas.

## 2. Scope

### In scope (MVP)

- New `inference/` Python module: HTTP client, action chunk buffer, action decoder, safety filter, inference control loop, async producer task.
- New `SessionMode.INFERENCE` slotted into the existing session lifecycle (mutually exclusive with `TELEOP` / `HAND_TEACH`).
- IK service: wraps `lerobot.robots.so_follower.robot_kinematic_processor.InverseKinematicsEEToJoints` (already bundled).
- New configurable YAML at `configs/inference/<name>.yaml` with full I/O contract (endpoint, request/response field mapping, normalization, action format, frame, gripper kind, units, optional `done` signal).
- New REST + WebSocket API: `/session/inference/start|stop|instruction|state` and `/ws/inference/telemetry`.
- New `InferencePage.tsx` frontend with config/dataset selectors, live instruction input, telemetry, camera tiles, episode controls, REVIEW with success/failure labeling, and always-visible E-stop.
- Recording integration: rollouts written as episodes in the existing dataset format. Instruction → `tasks.parquet`, with new `outcome`, `source`, `inference_config`, `stop_reason` columns on `meta/episodes.jsonl` (additive only, NULL for teleop).
- Per-step delta clamp + joint limit + slow-stop on chunk-late, all gated through `InferenceSafety`.
- Unit + integration tests on every component, one E2E test against `mock_robot` + a fake VLA server.

### Out of scope (deferred)

- **Sim-only inference path** (Isaac Sim bridge as primary target). The design supports it via robot adapter swap, but the MVP ships and verifies on SO-101 + mock.
- **reBot adapter integration**. Designed to slot in (the inference subsystem is robot-agnostic) but verified later.
- **Other action types**: `joint_position`, `joint_delta`, `ee_pose` (absolute). MVP supports `ee_delta` only.
- **Shared control / human override** during inference (e.g., grab the leader arm to take over). Architecturally noted as a future arbitrator layer in front of `command_goal_slot`.
- **Voice → STT → instruction** pipeline. The UI reserves a disabled mic icon; the backend `PUT /session/inference/instruction` already accepts arbitrary text, so future implementation is purely frontend.
- **EE-delta export from `vla_compat`**. (iii) cross-robot transfer requires also exporting datasets in EE-delta form. Tracked as a follow-up to the existing `vla_compat` exporter.
- **Multi-inflight inference** (`max_inflight > 1`). MVP fixes `max_inflight=1`. Schema accepts the field for future use.
- **`done` action heuristic from action norms** (option d in the brainstorm). MVP uses manual + optional `done` field from response (option c) + max_episode_seconds (option b).
- **Per-step task transitions inside an episode**. RECORDING phase locks instruction; one episode = one task.

## 3. Decisions log

| # | Decision | Choice | Rationale |
|---|---|---|---|
| Q1 | VLA target | Self-hosted Gemma-VLA over HTTP, contract via YAML | User's setup; iteration speed |
| Q2 | MVP mode | Real-robot closed loop | User priority |
| Q3 | Inference output | Action chunk (N future actions per call) | Hides per-call latency (Gemma-class can't sustain 30Hz single-step) |
| Q4 | Chunk consumption | Half-prefetch (consume ≥50% → fire next request) | Doubles latency budget vs sequential, simpler than overlapping |
| Q4b | Late-chunk fallback | Slow-stop (linear interpolation to `q_curr` over N ticks) | Avoids dispatch jolts |
| Q5 | Recording during inference | Yes — instruction → `tasks.parquet`, episode = one task | Reuses existing recording pipeline |
| Q6 | Safety layers | Per-step delta clamp + hard joint limits + manual E-stop + slow-stop | Required for real-robot operation; EE workspace box is overkill for MVP |
| Q7 | UI placement | New `InferencePage` (separate from RecordPage) | Different semantics, RecordPage already dense |
| Q8 | First robot | SO-101 (MVP), reBot designed-in | User priority + existing maturity |
| Q9 | Action type | `ee_delta` only | 6-dim ΔEE + 1-dim gripper. Cross-robot transferability (iii); typical VLA output format |
| Q10 | Frame / gripper / units | All YAML-configurable | `frame: ee_local|world`, `gripper.kind: absolute|delta|binary`, `pose.units: ...`. Fits multiple training stacks |
| Q11 | Image encoding (MVP) | `jpeg_base64` only | Smallest schema, works with Gemma-VLA |
| Q12 | Normalization stance | Configurable; `method: none` allowed | Some servers normalize internally |
| Q13 | Instruction lifecycle | `LatestValue[str]` slot, free during READY, **locked during RECORDING** | Clean episode-task semantics |
| Q14 | Rollout dataset | Same as `dataset_ref` (no separate target) | Simpler |
| Q15 | Task-done | Manual stop + optional model `done` signal in response + `max_episode_seconds` watchdog + REVIEW success/failure label | Layered defense + human-in-loop |

**Units convention** (referenced throughout): `RobotState.joint_pos` is `float32[Narm]` in **degrees** (matches `FKService` and the SO-101 adapter). `RobotState.gripper_pos` is a normalized scalar in `[-1, +1]` after the recent SO-101 gripper normalization fix (commit `e52029e`). The values fed into `request.state.components` are these raw values; `normalization` (if any) operates on them.

## 4. Architecture overview

```
┌────────────────────────────────────────────────────────────────────┐
│ Backend                                                            │
│                                                                    │
│   inference/producer ──HTTP──► Gemma VLA Server (separate)         │
│         ▲             │                                            │
│         │ wakes        ▼                                           │
│         │      inference/client → ActionDecoder (ee_delta + IK)    │
│         │                            │                             │
│         │                            ▼                             │
│         │                       ChunkBuffer                        │
│         │                            │                             │
│         └────────────────────────────┘ pop_next() per tick         │
│                                       │                            │
│                                       ▼                            │
│                       inference/control_loop ──► InferenceSafety   │
│                                                       │            │
│                                                       ▼            │
│                                              command_goal_slot     │
│                                                       │            │
│                                            (existing dispatcher)   │
│                                                       │            │
│                                                       ▼            │
│                                              SO-101 / reBot        │
│                                                                    │
│   if SessionState.RECORDING: control_loop also enqueues SampleBundle │
│   into existing recording writer → parquet/mp4 in datasets/<name>/ │
└────────────────────────────────────────────────────────────────────┘
```

`inference/producer` is the **only** new async task that talks to the VLA server. The control loop is purely local: pop chunk step → safety filter → command slot.

## 5. Module layout

```
backend/mimicrec/
├── inference/                              ← NEW
│   ├── __init__.py
│   ├── contract.py                         pydantic models for ContractSpec; YAML loader; env-var interpolation; validation
│   ├── client.py                           InferenceClient: builds request body per ContractSpec, parses response, returns raw action chunk + metadata
│   ├── chunk_buffer.py                     ChunkBuffer: deque + half-prefetch event + `_refill_in_flight` flag
│   ├── action_decoder.py                   ActionDecoder: ee_delta → q chain (uses IKService); applies frame/gripper/units rules from contract
│   ├── safety.py                           InferenceSafety: per-step delta clamp, joint limit, slow-stop, IK-fail hold
│   ├── producer.py                         run_inference_producer (async task)
│   ├── control_loop.py                     run_inference_control_loop (mirrors run_teleop_control_loop)
│   └── types.py                            ActionChunk, InferenceMetrics, ContractSpec re-exports, SafetyEvent
│
├── kinematics/
│   └── ik.py                               ← NEW: IKService wrapping lerobot's InverseKinematicsEEToJoints; degrees in/out matching FKService
│
├── session/
│   ├── lifecycle.py                        +start_inference_session, +stop_inference_session, +max_episode_seconds watchdog
│   └── state.py                            (no change; SessionState reused)
│
├── api/routes/
│   └── inference.py                        ← NEW: REST endpoints + WS telemetry channel
│
├── config/
│   └── inference_loader.py                 ← NEW: configs/inference/*.yaml discovery + load
│
└── types.py                                +SessionMode.INFERENCE

configs/
└── inference/                              ← NEW
    ├── gemma_libero_v1.yaml                example for user's first VLA
    └── README.md                           contract reference

frontend/src/
├── pages/InferencePage.tsx                 ← NEW
├── api/inference.ts                        ← NEW: REST client + WS hook
├── stores/inference-store.ts               ← NEW: Zustand store
└── App.tsx                                 +route entry

tests/inference/                            ← NEW
├── test_contract.py
├── test_client.py
├── test_chunk_buffer.py
├── test_action_decoder.py
├── test_safety.py
├── test_ik_service.py
├── test_producer_loop.py
├── test_lifecycle.py
└── test_recording_integration.py

tests/e2e/
└── test_inference_e2e.py                   ← NEW: fake VLA server + mock_robot, 60s closed loop
```

## 6. YAML contract

The contract has three top-level blocks: `endpoint`, `request`, `response`, plus a `loop` tuning block.

### 6.1 Skeleton

```yaml
name: gemma_libero_v1
description: "Gemma-VLA, LIBERO-finetuned, local FastAPI"

endpoint:
  url: "http://localhost:8001/predict"
  method: POST
  timeout_s: 5.0
  headers:
    Authorization: "Bearer ${VLA_API_TOKEN}"   # ${ENV} interpolation
  retry: { max_attempts: 0 }                   # MVP: no retry; safety handles late chunks

request:
  images:
    front:
      field: "image_primary"
      encoding: "jpeg_base64"                  # MVP: jpeg_base64 only
      resize: [224, 224]
      jpeg_quality: 90
    wrist:
      field: "image_wrist"
      encoding: "jpeg_base64"
      resize: [224, 224]
      jpeg_quality: 90
  state:
    field: "proprio"
    components: ["joint_pos", "gripper_pos"]
    normalization:
      method: "none"                            # MVP default; observation.state stats not yet exported
  instruction:
    field: "instruction"                        # value injected from instruction_slot at request time
  extra_fields:
    model_version: "gemma-libero-v1"

response:
  actions_path: "actions"                       # JSONPath into response body; expects N x 7 array
  chunk:
    expected_size: 16
    on_size_mismatch: "use_actual"              # use_actual | reject
  action:
    type: "ee_delta"                            # MVP: ee_delta only
    frame: "ee_local"                           # ee_local | world
    pose:
      units: "meter_axisangle_rad"              # meter_axisangle_rad | mm_euler_deg | ...
    gripper:
      kind: "absolute"                          # absolute | delta | binary
      units: "normalized_0_1"                   # normalized_0_1 | percent_0_100 | binary_threshold_0p5
    components: ["ee_delta", "gripper"]         # order in the per-step vector (length 7)
    normalization:
      method: "mean_std"                        # none | minmax_neg1_pos1 | mean_std
      stats_ref:
        type: "vla_export"                      # vla_export | absolute
        dataset: "SO101"                        # resolves to ${MIMICREC_VLA_DEST_ROOT}/SO101/meta/action_stats.json
  done:                                         # OPTIONAL — omit if server has no done signal
    path: "done"
    threshold: 0.5
    action_on_done: "auto_stop"                 # auto_stop | notify_only

loop:
  prefetch_threshold: 0.5
  max_inflight: 1                               # MVP fixed at 1
```

### 6.2 Validation (pydantic, at load time)

- `endpoint.url` must start with `http://` or `https://`.
- `request.images.<cam>.field` values must be unique.
- All `components` entries must be in the registry of known keys (`joint_pos`, `gripper_pos`, `ee_delta`, `gripper`).
- `stats_ref`: if `type=vla_export`, the resolved path must exist on disk; if `type=absolute`, the literal path must exist.
- `action.type` and combinations must be in the implemented registry (MVP: `ee_delta` only).
- `${ENV}` interpolation: missing env vars → load fails with a clear error.

### 6.3 stats resolution

`type: "vla_export"` resolves to:

```
${MIMICREC_VLA_DEST_ROOT}/<dataset>/meta/action_stats.json
```

Default `MIMICREC_VLA_DEST_ROOT = ~/vla-gemma-4/data/local`. Existing `action_stats.json` from the `vla_compat` exporter has the form `{"mean": [..7..], "std": [..7..]}`.

Observation state stats are **not currently exported**. MVP allows only `method: none` for `request.state.normalization`. When future stats are exported, the loader is the only place to extend.

## 7. Component design

### 7.1 ChunkBuffer

```python
@dataclass
class ChunkBuffer:
    _steps: deque[StepAction]         # StepAction = decoded q + optional gripper command
    _origin_size: int                  # set on push_chunk()
    _refill_event: asyncio.Event
    _refill_in_flight: bool = False
    prefetch_threshold: float = 0.5

    def pop_next(self) -> StepAction | None:
        if not self._steps:
            return None
        step = self._steps.popleft()
        consumed_ratio = 1 - len(self._steps) / max(1, self._origin_size)
        if consumed_ratio >= self.prefetch_threshold and not self._refill_in_flight:
            self._refill_in_flight = True
            self._refill_event.set()
        return step

    def push_chunk(self, chunk: list[StepAction]) -> None:
        self._steps.extend(chunk)
        self._origin_size = len(self._steps)
        self._refill_in_flight = False
```

`StepAction` carries a target `q` (degrees), gripper command, and any safety-relevant metadata (e.g., `ik_failed: bool`).

The buffer's `_refill_event` and `_refill_in_flight` are intentionally accessed by `InferenceProducer` (the only writer of chunks). Producer + buffer are a designed-pair; the underscore signals "not for general callers" rather than fully private. The implementation may expose thin public methods (`request_refill_signal()`, `acknowledge_refill_started()`) if doing so improves test ergonomics, but the contract is "exactly one producer per buffer".

### 7.2 InferenceProducer (async task)

```python
async def run_inference_producer(
    client, decoder, buffer, camera_slots, robot_state_slot, instruction_slot,
    metrics, stopped: asyncio.Event,
):
    buffer._refill_event.set()        # initial fire
    while not stopped.is_set():
        await buffer._refill_event.wait()
        buffer._refill_event.clear()
        frames = {n: s.peek() for n, s in camera_slots.items()}
        state = robot_state_slot.peek()
        instr = instruction_slot.peek()
        if any(v is None for v in (state, instr)) or not frames:
            buffer._refill_in_flight = False
            await asyncio.sleep(0.01); continue
        t0 = time.perf_counter()
        try:
            resp = await client.predict(frames, state, instr)
            chunk = decoder.decode(resp, current_state=state.value)
            buffer.push_chunk(chunk)
            metrics.observe("inference_latency_ms", (time.perf_counter() - t0) * 1000)
        except Exception as e:
            metrics.inc("inference_error_count")
            buffer._refill_in_flight = False
            # log via ErrorBus; do NOT crash the task
```

### 7.3 ActionDecoder (ee_delta only in MVP)

Per-step pseudocode for one chunk:

```
T_curr = FK(state.joint_pos[:Narm])
seed_q = state.joint_pos[:Narm]
for step in chunk_raw:
    delta_pose, gripper_raw = split(step, contract.action.components)
    delta_pose_phys = de_normalize(delta_pose, action_stats)
    delta_pose_phys = convert_units(delta_pose_phys, contract.pose.units)
    if contract.frame == "ee_local":
        T_next = T_curr * delta_pose_phys
    else:  # world
        T_next = delta_pose_phys * T_curr
    q_next, ok = IKService.solve(T_next, seed=seed_q)
    if not ok:
        q_next = seed_q                        # hold; safety enforces clamp/slow-stop
    gripper_cmd = decode_gripper(gripper_raw, contract.gripper, current=state.gripper_pos)
    yield StepAction(q=q_next, gripper=gripper_cmd, ik_failed=not ok)
    T_curr = T_next
    seed_q = q_next
```

`decode_gripper` interprets `kind: absolute|delta|binary` and `units: ...`. `binary_threshold_0p5` returns `1.0` if value ≥ 0.5 else `0.0`.

### 7.4 InferenceSafety

```python
def filter(self, step: StepAction | None, q_curr: np.ndarray, tick_t_ns: int) -> RobotCommand:
    if step is None:                            # buffer empty
        return self._slow_stop(q_curr, tick_t_ns)
    delta = step.q - q_curr
    delta = np.clip(delta, -self.max_delta, self.max_delta)
    q_safe = np.clip(q_curr + delta, self.joint_min, self.joint_max)
    self._last_safe_q = q_safe
    self._slow_stop_remaining = 0
    return RobotCommand(q=q_safe, gripper=step.gripper, t_mono_ns=tick_t_ns)

def _slow_stop(self, q_curr, tick_t_ns) -> RobotCommand:
    if self._slow_stop_remaining is None:
        self._slow_stop_remaining = self.slow_stop_ticks
    n = self._slow_stop_remaining
    if n <= 0 or self._last_safe_q is None:
        q = q_curr
    else:
        q = self._last_safe_q + (q_curr - self._last_safe_q) * (1 - n / self.slow_stop_ticks)
    self._slow_stop_remaining = max(0, n - 1)
    return RobotCommand(q=q, gripper=None, t_mono_ns=tick_t_ns)
```

Safety params from `configs/robot/<name>.yaml`:

```yaml
inference_safety:
  max_joint_delta_per_step_deg: 2.0
  slow_stop_ticks: 5
  joint_limits_deg:                            # if not set, falls back to URDF limits
    shoulder_pan: [-180.0, 180.0]
    shoulder_lift: [-110.0, 110.0]
    elbow_flex: [-110.0, 110.0]
    wrist_flex: [-110.0, 110.0]
    wrist_roll: [-180.0, 180.0]
```

### 7.5 IKService

Wraps `lerobot.robots.so_follower.robot_kinematic_processor.InverseKinematicsEEToJoints`. Degrees in/out, mirroring `FKService` conventions. Joint order from robot config. Returns `(q_solved, success: bool)`. Failures don't raise — `success=False` is propagated as `ik_failed` through `StepAction`.

### 7.6 run_inference_control_loop

Tick-by-tick logic mirrors `run_teleop_control_loop` exactly except for the action source: `chunk_buffer.pop_next()` instead of `teleop_slot.peek()`, and `safety.filter()` instead of `mapper.map()`. RECORDING phase enqueue is unchanged.

## 8. Lifecycle, API, recording

### 8.1 SessionMode addition

`SessionMode.INFERENCE` joins `TELEOP` and `HAND_TEACH`. Lifecycle picks one control loop:

```python
if mode == SessionMode.TELEOP:    run_teleop_control_loop(...)
elif mode == SessionMode.HAND_TEACH:    run_handteach_control_loop(...)
elif mode == SessionMode.INFERENCE:    run_inference_control_loop(...)
```

Teleop reader task is **not** spawned in INFERENCE mode (the leader arm is decoupled). Camera readers and dispatcher run as in TELEOP.

### 8.2 New API surface

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/session/inference/start` | `{ session_config_ref, inference_config_ref, dataset_ref, instruction }` | `{ session_id, state }` — 409 if any session is already active |
| POST | `/session/inference/stop` | `{}` | `{ ok }` |
| PUT | `/session/inference/instruction` | `{ text }` | `{ ok }` — 409 if `state == RECORDING` |
| GET | `/session/inference/state` | — | `{ phase, instruction, locked_instruction, buffer_depth, buffer_origin, chunks_consumed, last_inference_latency_ms, inference_errors, last_safety_event }` |
| GET | `/configs/inference` | — | `{ items: [{name, description}] }` |
| GET | `/configs/inference/{name}` | — | `{ ContractSpec dump (env vars elided) }` |
| WS | `/ws/inference` | — | streaming events (see §8.4); new hub alongside existing `session_hub`/`state_hub`/`teleop_hub`/`camera_hub` |

Existing endpoints reused without modification:

- `POST /episode/start` — start a recording episode within the inference session.
- `POST /episode/stop` — stop the recording.
- `POST /episode/save` (existing) — commit the episode. Body is `SaveEpisodeRequest { success: bool | None, comment: str | None }`. Inference rollouts populate `success=True|False` from the REVIEW UI (Save (success) vs Save (failure)). Teleop callers continue to send `success=None` (no behavior change).
- `POST /episode/discard` — discard the episode.
- `POST /robot/estop` (existing, in `api/routes/session.py:122`) — used as the InferencePage E-stop. Calls the active adapter's `estop()` method (SO-101 supports it). No new emergency-stop endpoint is added.

### 8.3 Recording integration

- Instruction lock: at `episode_start`, the value of `_instruction_slot.peek()` is captured into `Session.locked_instruction`. `PUT /session/inference/instruction` returns 409 while RECORDING. At `episode_stop` (or discard), the lock is released.
- `episodes.jsonl` per-episode metadata gains three optional columns:
  - `source: "teleop" | "hand_teach" | "inference"` (NULL/missing for legacy rows)
  - `inference_config: <name>` (only when `source == "inference"`)
  - `stop_reason: "manual" | "model_done" | "timeout"` (only when `source == "inference"`)
- The success/failure label is carried by the **existing `success: bool | None`** field on `SaveEpisodeRequest` (no new column). The InferencePage REVIEW UI sets `success=True` for *Save (success)* and `success=False` for *Save (failure)*. The backend does **not** reject `success=None` for inference rollouts — that case maps to "unlabeled rollout" and the column is recorded as null. The frontend always presents the labeled buttons for inference, so `null` only occurs if the API is called directly.
- `tasks.parquet` gets the locked instruction via the existing `upsert_task` path; `task_index` is assigned per-episode as today.

Existing teleop episodes are unaffected.

### 8.4 WebSocket events

```jsonc
{"type": "buffer_state",        "depth": 8, "origin_size": 16}
{"type": "inference_started",   "instruction": "pick up the bottle"}
{"type": "inference_done",      "latency_ms": 142.3, "chunk_size": 16}
{"type": "inference_error",     "kind": "http_timeout"|"schema"|"transport", "message": "..."}
{"type": "safety_event",        "kind": "delta_clamp"|"joint_limit"|"slow_stop"|"ik_fail", "step_index": 42, "joint": "elbow_flex"}
{"type": "instruction_locked",  "text": "pick up the bottle"}
{"type": "instruction_released"}
{"type": "next_action_preview", "ee_delta": [...6...], "gripper": 0.2}    // throttled, e.g., every 5 ticks
{"type": "episode_phase",       "phase": "ready"|"recording"|"review"}
{"type": "model_done",          "received": true}                          // contract.done.path triggered
{"type": "watchdog_timeout",    "elapsed_sec": 121.3}                      // max_episode_seconds hit
```

The new `/ws/inference` channel is implemented as a new `inference_hub` alongside the existing `api/ws/{session,state,teleop,camera}_hub.py`. Hardware errors continue to surface through the existing `session_hub` (the InferencePage subscribes to both). Camera streams remain on their existing `camera_hub` channels.

### 8.5 max_episode_seconds watchdog

Lifecycle starts a watchdog task on `episode_start` that auto-fires `episode_stop` after `session_config.max_episode_seconds` (default 120s). On fire, it sets `stop_reason: "timeout"` and emits `watchdog_timeout`. Cancellable on normal `episode_stop`.

## 9. UI: InferencePage

A single page with phase-driven main panel; persistent header with `[● live]` indicator and right-aligned `[E-STOP]` (red, always visible).

| Phase | Main panel content |
|---|---|
| pre-start | Inference config dropdown, dataset dropdown, instruction text input + disabled mic icon, **Start session** |
| ready | Editable instruction input + **Update**, telemetry block (buffer / latency / chunks / errors / safety events), camera tiles, action preview (numeric ΔEE + gripper), **Start episode** + **Stop session** |
| recording | Locked instruction display, episode timer (`mm:ss / mm:ss`), telemetry + cameras + action preview, "model done signal: …", **Stop episode** |
| review | Episode summary (index, duration), **Save (✓ success)** / **Save (✗ failure)** / **Discard** |

Component–to–API mapping is documented inline with the implementation; no new entries beyond §8.2.

Zustand store shape covers: `phase`, `config { name, spec? }`, `dataset`, `instruction`, `lockedInstruction`, `telemetry { bufferDepth, bufferOrigin, lastLatencyMs, chunksConsumed, inferenceErrors, safetyEvents[], nextAction?, modelDoneSignal }`, `episodeElapsedSec`, `reviewEpisode? { index, durationSec }` and the corresponding action methods.

Frontend opens the WebSocket on session start and closes on session stop. Telemetry events update store; UI reads reactively.

## 10. Error handling

| Category | Source | Surface | Effect on session |
|---|---|---|---|
| Config validation | YAML / pydantic / env interpolation | `400` on `/start` with detail | does not start |
| Stats not found | resolver, at start | `400` with path | does not start |
| HTTP transport | client (timeout, conn refused) | WS `inference_error{kind:"transport"}` + UI toast | producer continues; buffer drains; safety enters slow-stop |
| Schema mismatch | response parsing | WS `inference_error{kind:"schema"}` | same as transport |
| IK failure | decoder | WS `safety_event{kind:"ik_fail"}` | step holds at seed; chunk continues |
| Delta clamp / joint limit | safety | WS `safety_event` | clamped value used; recorded |
| Slow-stop entered | safety | WS `safety_event{kind:"slow_stop"}` | linear interpolation to current |
| Hardware error | RobotAdapter / dispatcher | existing `ErrorBus` → existing `session_hub` WS (no duplication on `inference_hub`) | session stopped (existing behavior) |
| Episode watchdog timeout | lifecycle | WS `watchdog_timeout` + auto `episode_stop` | RECORDING → REVIEW |

Inference-side failures **do not crash the session**. Only hardware errors and explicit stop end the session.

## 11. Testing

### Unit

- `test_contract.py` — load happy path, env-var interpolation, missing env, unknown action.type, non-existent stats path, components-with-unknown-keys.
- `test_chunk_buffer.py` — half-prefetch threshold fires once, flag prevents double-fire, empty-buffer pop returns None, push resets origin and clears flag.
- `test_action_decoder.py` — round-trip ee_local / world frames; gripper kinds (absolute / delta / binary); units conversion; IK chain seeding; IK failure propagates `ik_failed`.
- `test_safety.py` — clamp at boundary, joint-limit clip, slow-stop linear over N ticks, IK-fail step held.
- `test_client.py` — request body assembly per contract, jpeg encoding shape, header env interpolation; mock httpx server returns canned response, parser roundtrip.
- `test_ik_service.py` — known-pose round trip, unsolvable pose returns `ok=False`.

### Integration

- `test_producer_loop.py` — fake client returns canned chunk; verify producer fills buffer on refill event; verify error path leaves buffer empty without crashing.
- `test_lifecycle.py` — `start_inference_session` spawns producer + control_loop + dispatcher; stop cancels all; teleop session active → start_inference returns 409; inference watchdog auto-stops episode.
- `test_recording_integration.py` — full session: start → episode_start → inject N ticks of inference → episode_stop → commit(outcome=success). Verify parquet rows, mp4 written, `tasks.parquet` has instruction, `episodes.jsonl` has new columns populated.

### E2E

- `test_inference_e2e.py` — boot a fake VLA HTTP server (aiohttp.test_utils) that emits ee_delta chunks with mild motion; spin up an inference session against `mock_robot`; run 60 seconds; assert: zero `inference_error`, ≥1 chunk consumed, `safety_event` count below threshold, parquet+mp4 generated, recovered action stats fall within expected ranges.

`mock_robot`-only for E2E. CI runs unit + integration; E2E gated to manual / nightly.

## 12. Configuration changes

- `configs/robot/so101.yaml`: add `inference_safety:` block (max_joint_delta_per_step_deg, slow_stop_ticks, optional joint_limits_deg). Same shape will be added to `configs/robot/rebotarm.yaml` when reBot is enabled.
- `configs/sessions/<name>.yaml`: add optional `max_episode_seconds: 120` (default 120 if absent).
- `configs/inference/`: new directory; ships with `gemma_libero_v1.yaml` template + `README.md` describing schema.
- `MIMICREC_VLA_DEST_ROOT` env var: already exists for the `vla_compat` export pipeline; reused as the default base for `stats_ref.type: vla_export`.

## 13. Future work / migration notes

- **`vla_compat` removal (planned in `2026-04-29-lerobot-v3-native-recording.md`)**: when this lands, `meta/action_stats.json` may move (or stats may be computed natively into the source dataset). The contract resolver gets a new `stats_ref.type: source` option; current `vla_export` stays as a back-compat path. No breaking change to existing inference YAMLs.
- **Cross-robot transfer (iii)**: requires `vla_compat` (or its successor) to support `--action-format ee_delta`, exporting EE-delta as the `action` column. Tracked as a follow-up on the existing exporter.
- **EE workspace box safety**: `InferenceSafety.filter` is the natural insertion point; FKService is already available. Add when needed.
- **Shared control / human override**: introduce a `mode_arbitrator` task between control loops and `command_goal_slot` that blends teleop + inference based on a "human override active" signal.
- **Multi-inflight**: relax `max_inflight=1`; producer becomes a small queue of in-flight tasks. ChunkBuffer schedule may need re-design (consume from "the most recently committed chunk" vs FIFO of chunks).
- **Voice → STT**: pure frontend; appears as another writer to `PUT /session/inference/instruction`. No backend change required.
- **Other action types**: when `joint_position` / `joint_delta` / `ee_pose` are needed, extend `ActionDecoder` with their branches. Contract validation registry gets the new entries.

## 14. Appendix — full sample YAML (with comments)

```yaml
# configs/inference/gemma_libero_v1.yaml
name: gemma_libero_v1
description: "Gemma-VLA fine-tuned on LIBERO, served on local FastAPI."

endpoint:
  url: "http://localhost:8001/predict"
  method: POST
  timeout_s: 5.0
  headers:
    Authorization: "Bearer ${VLA_API_TOKEN}"
  retry:
    max_attempts: 0

request:
  images:
    front:
      field: "image_primary"
      encoding: "jpeg_base64"
      resize: [224, 224]
      jpeg_quality: 90
    wrist:
      field: "image_wrist"
      encoding: "jpeg_base64"
      resize: [224, 224]
      jpeg_quality: 90
  state:
    field: "proprio"
    components: ["joint_pos", "gripper_pos"]
    normalization:
      method: "none"        # MVP default: server normalizes, or model is robust to raw
  instruction:
    field: "instruction"
  extra_fields:
    model_version: "gemma-libero-v1"

response:
  actions_path: "actions"
  chunk:
    expected_size: 16
    on_size_mismatch: "use_actual"
  action:
    type: "ee_delta"
    frame: "ee_local"
    pose:
      units: "meter_axisangle_rad"
    gripper:
      kind: "absolute"
      units: "normalized_0_1"
    components: ["ee_delta", "gripper"]
    normalization:
      method: "mean_std"
      stats_ref:
        type: "vla_export"
        dataset: "SO101"
  done:
    path: "done"
    threshold: 0.5
    action_on_done: "auto_stop"

loop:
  prefetch_threshold: 0.5
  max_inflight: 1
```
