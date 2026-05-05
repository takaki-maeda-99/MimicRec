# VLA Inference Interface

**Date:** 2026-05-05
**Status:** Approved (subagent rounds 1–3, user reviews 1–3 — LGTM 2026-05-05)
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
- New REST + WebSocket API: `/session/inference/start|stop|instruction|state` and `/ws/inference`.
- New `InferencePage.tsx` frontend with config/dataset selectors, live instruction input, telemetry, camera tiles, episode controls, REVIEW with success/failure labeling, and always-visible E-stop.
- Recording integration: rollouts written as episodes in the existing dataset format. Instruction → `tasks.parquet`. Three additive columns on `meta/episodes.jsonl` (`source`, `inference_config`, `stop_reason`) — null for teleop. Success/failure label reuses the **existing** `SaveEpisodeRequest.success: bool | None` field; no new outcome column.
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
| Q16 | READY phase robot motion | **Robot is actively driven by VLA during READY** (RECORDING gates only the parquet/mp4 write path, not command dispatch) | Lets the operator validate model behavior before committing to a recorded episode; matches the "rehearsal" semantics expected from a closed-loop UI |
| Q17 | Instruction update on READY | `PUT /session/inference/instruction` **flushes the chunk buffer** and re-arms the producer; the in-flight request (if any) is dropped via a generation counter | Avoids ~0.5 s of stale motion under the previous instruction. Slow-stop covers the gap until the new chunk arrives |

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
  retry: { max_attempts: 0 }                   # MVP: no retry; safety handles late chunks.
                                               # NOTE: setting this > 0 in production inference is
                                               # almost always wrong — it amplifies state drift, and
                                               # half-prefetch + slow-stop already cover transient
                                               # network errors. Reserved for future health-check
                                               # type usage only.

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
  done:                                         # OPTIONAL — omit entirely to disable the auto-stop signal path
    path: "done"                                # JSONPath into response body
    type: "float"                               # float | bool. If float, compared with `threshold`. If bool, taken directly.
    threshold: 0.5                              # only used when type=float
    scope: "chunk"                              # chunk | step. MVP: only "chunk" implemented.
                                                #   chunk = applies to the chunk as a whole; auto_stop
                                                #           fires after the chunk is fully consumed.
                                                #   step  = (future) per-step done; would auto_stop
                                                #           on the first step that reports done.
    action_on_done: "auto_stop"                 # auto_stop | notify_only.
                                                # In READY phase, auto_stop is silently downgraded
                                                # to notify_only (there is no episode to stop) — the
                                                # WS still emits `model_done` for visibility. auto_stop
                                                # is honored only during RECORDING, where it fires
                                                # episode_stop with stop_reason="model_done".

loop:
  prefetch_threshold: 0.5
  max_inflight: 1                               # MVP fixed at 1
```

### 6.2 Validation (pydantic, at load time)

- `endpoint.url` must start with `http://` or `https://`.
- `request.images.<cam>.field` values must be unique.
- All `components` entries must be in the **components-to-dim registry**:

  | key | dim | source |
  |---|---|---|
  | `joint_pos` | `Narm` (from robot config) | `RobotState.joint_pos` |
  | `gripper_pos` | 1 | `RobotState.gripper_pos` (normalized [-1, +1]) |
  | `ee_delta` | 6 (3 pos + 3 axis-angle) | computed via FK / decoder |
  | `gripper` | 1 | from `action.gripper.kind` rules |
  | `joint_delta` | `Narm` | (future, not in MVP) |
  | `ee_pose` | 7 (3 pos + 4 quat) | (future, not in MVP) |

  Total expected vector length is the sum of component dims in declared order. Used both at request-build time (state vector packing) and at response-decode time.
- `stats_ref`: if `type=vla_export`, the resolved path must exist on disk; if `type=absolute`, the literal path must exist. **The length of `mean` and `std` arrays in `action_stats.json` MUST equal the sum of `action.components` dims** (length mismatch → load fails). MVP `["ee_delta", "gripper"]` requires length 7, matching the existing 7-dim stats produced by `vla_compat`.
- `action.type` and combinations must be in the implemented registry (MVP: `ee_delta` only).
- `${ENV}` interpolation: missing env vars → load fails with a clear error.
- If `response.done` block is present, `done.scope` must be in the implemented registry (MVP: `chunk` only); `done.type` ∈ `{bool, float}`; if `bool`, `threshold` is ignored.
- The robot config's `inference_safety:` block (see §7.4) **must be present** when `start_inference_session` is called — missing block returns 400 with a remedy hint. URDF mechanical limits are intentionally NOT used as a fallback (they are too wide for closed-loop policy use).

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
    """
    Action chunk buffer with half-prefetch trigger and instruction-flush support.

    Concurrency contract: SINGLE producer (InferenceProducer), SINGLE consumer
    (run_inference_control_loop), BOTH on the same asyncio event loop. This
    invariant is what allows the implementation to skip locks. Adding a
    second producer or accessing from a thread requires re-design.
    """
    _steps: deque[StepAction]         # StepAction = decoded q + optional gripper command
    _origin_size: int                  # set on push_chunk()
    _refill_event: asyncio.Event
    _refill_in_flight: bool = False
    _generation: int = 0               # bumped on flush(); producer captures + checks on push
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

    def try_push_chunk(self, chunk: list[StepAction], generation: int) -> bool:
        """Push chunk only if generation still matches. Returns False if stale."""
        if generation != self._generation:
            return False                       # caller's snapshot is stale; chunk dropped
        self._steps.extend(chunk)
        self._origin_size = len(self._steps)
        self._refill_in_flight = False
        return True

    def flush(self) -> int:
        """Drop any queued steps, bump generation, re-arm the producer.
        Returns the number of steps that were dropped (used by
        callers that emit `instruction_updated.flushed_steps` on the WS)."""
        flushed = len(self._steps)
        self._steps.clear()
        self._origin_size = 0
        self._generation += 1
        self._refill_in_flight = False
        self._refill_event.set()
        return flushed

    def request_refill_now(self) -> None:
        """Producer-facing signal used at startup, on producer-driven re-arm,
        and by the lifecycle on REVIEW → READY transition."""
        self._refill_in_flight = False
        self._refill_event.set()

    async def wait_for_refill(self) -> None:
        """Producer-facing wait. Encapsulates the underlying Event so the
        producer never touches `_refill_event` directly — keeps the seam
        clean for tests that swap a fake buffer in."""
        await self._refill_event.wait()
        self._refill_event.clear()

    def current_generation(self) -> int:
        return self._generation
```

`StepAction` carries a target `q` (degrees), gripper command, and any safety-relevant metadata (e.g., `ik_failed: bool`).

`_refill_event` and `_refill_in_flight` are accessed only via the methods above; `_generation` is captured by `InferenceProducer` at the start of each refill round and passed back to `try_push_chunk` so that any chunk computed under a stale instruction is dropped on arrival.

### 7.2 InferenceProducer (async task)

The producer takes a coordinated **input snapshot** at the start of each refill, captures the buffer's current generation, and is the only task that must always re-arm itself before sleeping (so the loop can never deadlock when inputs aren't ready or HTTP fails).

```python
async def run_inference_producer(
    client, decoder, buffer, camera_slots, robot_state_slot, instruction_slot,
    safety,                                              # for safety.on_new_chunk()
    session,                                             # exposes producer_paused, state, stopped
    metrics, error_bus,
):
    buffer.request_refill_now()                          # initial fire
    backoff_s = 0.1                                      # error backoff, doubles up to 1.0
    NOT_READY_RETRY_S = 0.05

    async def stop_aware_sleep(seconds: float) -> bool:
        """Sleep, but return True early if the session is stopping.
        Replaces bare asyncio.sleep so backoff/retry can't delay graceful shutdown."""
        try:
            await asyncio.wait_for(session.stopped.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False

    while not session.stopped.is_set():
        await buffer.wait_for_refill()                   # see §7.1 (public method)

        # REVIEW phase: skip fetching, go back to wait. Lifecycle re-arms us on REVIEW exit.
        if session.producer_paused:
            continue

        # --- coordinated input snapshot ---
        # All slots are .peek()ed back-to-back at the same async stack frame.
        # Each Stamped value carries its own t_mono_ns; we forward those into
        # extras so the server can verify (or refuse) the synchrony window.
        gen = buffer.current_generation()
        frames = {n: s.peek() for n, s in camera_slots.items()}
        state = robot_state_slot.peek()
        instr = instruction_slot.peek()

        not_ready = (
            state is None or instr is None or
            not frames or any(f is None for f in frames.values())
        )
        if not_ready:
            if await stop_aware_sleep(NOT_READY_RETRY_S):
                return
            buffer.request_refill_now()                  # ← re-arm; otherwise deadlock
            continue

        t0 = time.perf_counter()
        try:
            extras = {
                "_t_mono_ns": {
                    "state": state.t_mono_ns,
                    **{f"image:{n}": f.t_mono_ns for n, f in frames.items()},
                    "instruction": instr.t_mono_ns,
                },
            }
            resp = await client.predict(frames, state, instr, extras=extras)
            chunk = decoder.decode(resp, current_state=state.value)
            pushed = buffer.try_push_chunk(chunk, generation=gen)
            if not pushed:
                metrics.inc("inference_chunk_dropped_stale")
                buffer.request_refill_now()              # generation advanced → fetch fresh
            else:
                safety.on_new_chunk()                    # reset _clamps_in_current_chunk (see §7.4)
                metrics.observe("inference_latency_ms",
                                (time.perf_counter() - t0) * 1000)
                backoff_s = 0.1                          # reset on success
                # Note: no explicit re-arm here — the consumer-side
                # half-prefetch in pop_next() will fire _refill_event
                # once consumed_ratio >= prefetch_threshold.
        except Exception as e:
            metrics.inc("inference_error_count")
            await error_bus.publish_inference_error(kind=classify(e), message=str(e))
            if await stop_aware_sleep(backoff_s):
                return
            backoff_s = min(backoff_s * 2, 1.0)
            buffer.request_refill_now()                  # ← re-arm; otherwise deadlock
```

`stop_aware_sleep` replaces bare `asyncio.sleep` so a graceful `session.stop` interrupts a 1 s backoff immediately rather than waiting it out (which also avoids cancelling an in-flight `httpx` request mid-read and the resource-warning fallout that comes with that).

**Test coverage required (§11):** the not-ready and exception paths must each have a regression test that verifies the producer recovers (re-fires within bounded time and eventually succeeds when conditions clear). Specifically `test_producer_loop.py` must include "initial state=None then becomes available" and "3 consecutive transport errors then success".

**Sync window (§4):** the snapshot is best-effort, not tick-aligned. Inter-camera and camera-vs-state offsets can reach a few tens of ms in practice. The `extras._t_mono_ns` map carries each per-source timestamp so the server side (or downstream analysis) can detect violations of any synchrony assumptions the model has. A future improvement is to expose a tick-aligned `SampleBundle`-style snapshot from the recording pipeline and have the producer pull from it.

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
class InferenceSafety:
    # state initialized at session start
    _last_safe_q: np.ndarray | None = None       # last clamped joint command
    _last_gripper_cmd: float | None = None       # last gripper command emitted
    _slow_stop_remaining: int = 0                # 0 = not in slow-stop; counts down to 0 from slow_stop_ticks
    _clamps_in_current_chunk: int = 0            # surfaced via telemetry; reset by on_new_chunk()

    def filter(self, step: StepAction | None, q_curr: np.ndarray, tick_t_ns: int) -> RobotCommand:
        if step is None:                                                # buffer empty
            return self._slow_stop(q_curr, tick_t_ns)
        delta = step.q - q_curr
        clamped = np.clip(delta, -self.max_delta, self.max_delta)
        if not np.array_equal(clamped, delta):
            self._clamps_in_current_chunk += 1                          # surfaced via telemetry
        q_safe = np.clip(q_curr + clamped, self.joint_min, self.joint_max)
        self._last_safe_q = q_safe
        # Hold-the-last semantics for gripper: if a step has gripper=None
        # (decoder decided no change, or contract has no gripper output),
        # repeat whatever was sent last to avoid the dispatcher flapping.
        gripper_cmd = step.gripper if step.gripper is not None else self._last_gripper_cmd
        if gripper_cmd is not None:
            self._last_gripper_cmd = gripper_cmd
        self._slow_stop_remaining = 0
        return RobotCommand(q=q_safe, gripper=gripper_cmd, t_mono_ns=tick_t_ns)

    def _slow_stop(self, q_curr: np.ndarray, tick_t_ns: int) -> RobotCommand:
        # Linear interpolation from _last_safe_q toward q_curr over slow_stop_ticks.
        # Once finished, hold q_curr (zero motion).
        if self._last_safe_q is None:
            q = q_curr.copy()
        else:
            if self._slow_stop_remaining == 0:
                self._slow_stop_remaining = self.slow_stop_ticks
            n = self._slow_stop_remaining
            # alpha series for slow_stop_ticks=N=5: tick 1→0.2, tick 2→0.4, ..., tick 5→1.0.
            # We start ramping immediately (no "do nothing" first tick), since the operator
            # already feels the late-chunk and we want to begin deceleration right away.
            alpha = 1.0 - ((n - 1) / self.slow_stop_ticks)
            q = self._last_safe_q + (q_curr - self._last_safe_q) * alpha
            self._slow_stop_remaining = max(0, n - 1)
            if self._slow_stop_remaining == 0:
                self._last_safe_q = q                                   # converged
        # Gripper during slow-stop holds the last commanded value (do not flap).
        return RobotCommand(q=q, gripper=self._last_gripper_cmd, t_mono_ns=tick_t_ns)

    def on_new_chunk(self) -> None:
        """Called by InferenceProducer after a successful try_push_chunk().
        Resets per-chunk metrics so they reflect "this chunk only"."""
        self._clamps_in_current_chunk = 0
```

`_clamps_in_current_chunk` is sampled by the producer/control_loop at chunk boundaries and emitted on the WS as `clamps_per_chunk` (see §8.4) so growth indicates VLA-vs-tracking divergence in production.

Safety params from `configs/robot/<name>.yaml`. **The `inference_safety:` block is required to start an inference session** — there is intentionally no URDF-mechanical-limit fallback (those values are too wide for closed-loop policy use).

```yaml
inference_safety:                              # REQUIRED for inference sessions; missing block → 400
  max_joint_delta_per_step_deg: 2.0
  slow_stop_ticks: 5
  joint_limits_deg:                            # required; values inside the URDF mechanical limits
    shoulder_pan: [-180.0, 180.0]
    shoulder_lift: [-110.0, 110.0]
    elbow_flex: [-110.0, 110.0]
    wrist_flex: [-110.0, 110.0]
    wrist_roll: [-180.0, 180.0]
```

### 7.5 IKService

Wraps `lerobot.model.kinematics.RobotKinematics.inverse_kinematics(current_joint_pos_deg, desired_ee_pose_4x4)` — the same `RobotKinematics` class that `FKService` already wraps for forward kinematics. Degrees in/out, joint order from `KinematicsConfig.joint_names`. Returns `(q_solved, success: bool)`. The placo solver always returns *some* solution, so "success" is computed by a FK round-trip: `success = position_error < 0.02 m AND orientation_error < 0.1 rad` (≈6°). Failures don't raise — `success=False` is propagated as `ik_failed` through `StepAction`. (Earlier drafts of this spec referenced `lerobot.robots.so_follower.robot_kinematic_processor.InverseKinematicsEEToJoints`; that class is an action-processor step, not an IK solver, and is not used here.)

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

**READY phase semantics (Q16).** The inference control loop runs continuously from session start to session stop and **always publishes commands to `command_goal_slot`**. The `RECORDING` phase only gates the parquet/mp4 write path (`enqueue(SampleBundle)`), not command dispatch. Concretely:

- `READY`: VLA is queried, chunks decoded and applied via safety, robot moves under model control. Operator uses this to validate model behavior, position the arm, edit the instruction, then press *Start episode* when ready.
- `RECORDING`: same as READY plus the recording writer is enqueueing.
- `REVIEW`: control_loop **continues to run normally**, but on entering REVIEW the lifecycle performs the following **in this exact order**:
  1. `session.producer_paused = True` (must come first — otherwise step 2's `_refill_event.set()` could wake the producer to fetch one stale chunk before it sees the pause flag),
  2. `chunk_buffer.flush()` (empties queued steps, bumps generation so any in-flight chunk is dropped on arrival, and re-arms the event harmlessly since the producer is now paused).

  With the buffer empty, every `pop_next()` returns `None` and `safety.filter(None, q_curr, ...)` enters slow-stop, holding the arm at `_last_safe_q` and continuing to assert that hold every tick (no dispatch hole). Gripper holds at `_last_gripper_cmd` (§7.4).

  On commit / discard (REVIEW → READY), the lifecycle reverses the order:
  1. `session.producer_paused = False`,
  2. `chunk_buffer.request_refill_now()`.

  Order on resume is technically forgiving (the producer is asleep on `wait_for_refill()`), but the symmetric ordering is what the lifecycle helper enforces. **Implementation:** these pairs are wrapped in `lifecycle.pause_producer_and_flush()` and `lifecycle.resume_producer()` so the order is enforced in one place and tested once.

  The first chunk after resume is grounded in the current robot state — never the state captured at REVIEW entry.

The InferencePage `[● live]` indicator is lit whenever commands are being dispatched (READY + RECORDING). UI must clearly communicate "the robot is under model control" during READY (see §9). E-stop (`POST /robot/estop`) remains the operator's escape hatch in any phase.

**Instruction update flush (Q17).** `PUT /session/inference/instruction` calls `chunk_buffer.flush()` immediately. This:
- empties any queued steps (control_loop next pop_next() returns `None` → safety enters slow-stop),
- bumps the buffer's `_generation` so any in-flight HTTP response is dropped on arrival via `try_push_chunk`,
- re-arms the producer to fetch a fresh chunk under the new instruction.

The robot decelerates over `slow_stop_ticks` (≈333 ms at 15 fps) until the next chunk arrives, then resumes. This is the `READY`-only path; during `RECORDING` the endpoint returns 409 and no flush happens.

### 8.2 New API surface

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/session/inference/start` | `{ session_config_ref, inference_config_ref, dataset_ref, instruction }` | `{ session_id, state }` — 409 if any session is already active |
| POST | `/session/inference/stop` | `{}` | `{ ok }` |
| PUT | `/session/inference/instruction` | `{ text }` | `{ ok }` — 409 if `state == RECORDING`. Handler updates `_instruction_slot`, captures `flushed = chunk_buffer.flush()` (returns the dropped step count), and publishes `{type: "instruction_updated", text, flushed_steps: flushed}` on `inference_hub` (§8.4). |
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
{"type": "buffer_state",         "depth": 8, "origin_size": 16, "generation": 3}
{"type": "inference_started",    "instruction": "pick up the bottle"}
{"type": "inference_done",       "latency_ms": 142.3, "chunk_size": 16}
{"type": "inference_error",      "kind": "http_timeout"|"schema"|"transport", "message": "..."}
{"type": "inference_chunk_dropped_stale", "generation_was": 2, "current_generation": 3}
{"type": "safety_event",         "kind": "delta_clamp"|"joint_limit"|"slow_stop"|"ik_fail", "step_index": 42, "joint": "elbow_flex"}
{"type": "clamps_per_chunk",     "count": 7, "chunk_size": 16}             // emitted at each chunk boundary
{"type": "instruction_updated",  "text": "...", "flushed_steps": 6}        // PUT during READY
{"type": "instruction_locked",   "text": "pick up the bottle"}
{"type": "instruction_released"}
{"type": "next_action_preview",  "ee_delta": [...6...], "gripper": 0.2}    // throttled, e.g., every 5 ticks
{"type": "episode_phase",        "phase": "ready"|"recording"|"review"}
{"type": "model_done",           "received": true}                         // contract.done.path triggered
{"type": "watchdog_timeout",     "elapsed_sec": 121.3}                     // max_episode_seconds hit
```

The new `/ws/inference` channel is implemented as a new `inference_hub` alongside the existing `api/ws/{session,state,teleop,camera}_hub.py`. Hardware errors continue to surface through the existing `session_hub` (the InferencePage subscribes to both). Camera streams remain on their existing `camera_hub` channels.

### 8.5 max_episode_seconds watchdog

Lifecycle starts a watchdog task on `episode_start` that auto-fires `episode_stop` after `session_config.max_episode_seconds` (default 120s). On fire, it sets `stop_reason: "timeout"` and emits `watchdog_timeout`. Cancellable on normal `episode_stop`.

## 9. UI: InferencePage

A single page with phase-driven main panel; persistent header with `[● live]` indicator and right-aligned `[E-STOP]` (red, always visible). The `[● live]` dot is lit whenever commands are being dispatched (READY and RECORDING — see Q16). The page renders a yellow "Robot under model control" banner during READY to make the active dispatch unambiguous to the operator.

| Phase | Main panel content |
|---|---|
| pre-start | Inference config dropdown, dataset dropdown, instruction text input + disabled mic icon, **Start session** |
| ready | **Yellow banner: "Robot under model control — use E-STOP to halt".** Editable instruction input + **Update** (calls `PUT instruction` and triggers a buffer flush; brief slow-stop is expected), telemetry block (buffer / latency / chunks / errors / safety events / clamps_per_chunk), camera tiles, action preview (numeric ΔEE + gripper), **Start episode** + **Stop session** |
| recording | Locked instruction display, episode timer (`mm:ss / mm:ss`), telemetry + cameras + action preview, "model done signal: …", **Stop episode** |
| review | Episode summary (index, duration), **Save (✓ success)** / **Save (✗ failure)** / **Discard**. Control loop is paused (slow-stop holds the arm) until the operator chooses. |

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

- `test_contract.py` — load happy path, env-var interpolation, missing env, unknown action.type, non-existent stats path, components-with-unknown-keys, **action_stats length mismatch with declared components dim sum**, **`done.scope=step` rejected (MVP: chunk only)**, **`done.type` ∉ {bool, float} rejected**, **missing `inference_safety` block in robot config rejected at start_inference_session**.
- `test_chunk_buffer.py` — half-prefetch threshold fires once, flag prevents double-fire, empty-buffer pop returns None, push resets origin and clears flag, **`flush()` empties steps and bumps generation**, **`try_push_chunk` with stale generation returns False and drops the chunk**.
- `test_action_decoder.py` — round-trip ee_local / world frames; gripper kinds (absolute / delta / binary); units conversion; IK chain seeding; IK failure propagates `ik_failed`.
- `test_safety.py` — clamp at boundary, joint-limit clip, slow-stop linear over N ticks, IK-fail step held, **`step.gripper=None` repeats `_last_gripper_cmd`**, slow-stop preserves last gripper, clamp count exposed via `_clamps_in_current_chunk`.
- `test_client.py` — request body assembly per contract, jpeg encoding shape, header env interpolation; mock httpx server returns canned response, parser roundtrip.
- `test_ik_service.py` — known-pose round trip, unsolvable pose returns `ok=False`.

### Integration

- `test_producer_loop.py` — fake client returns canned chunk; verify producer fills buffer on refill event; **regression: initial state=None then becomes available — producer must recover and push a chunk** (deadlock check); **regression: 3 consecutive transport errors then success — producer must recover with bounded backoff** (deadlock check); **regression: instruction flush during in-flight request causes `try_push_chunk` to return False and producer to fetch fresh** (generation check); **spy: every successful push is followed by exactly one `safety.on_new_chunk()` call** (catches future refactor that decouples them).
- `test_lifecycle.py` — `start_inference_session` spawns producer + control_loop + dispatcher; stop cancels all; teleop session active → start_inference returns 409; inference watchdog auto-stops episode.
- `test_recording_integration.py` — full session: start → episode_start → inject N ticks of inference → episode_stop → POST /episode/save with `success=True`. Verify parquet rows, mp4 written, `tasks.parquet` has instruction, `episodes.jsonl` has the three new columns populated; `success=True` recorded via the existing `success` plumbing.

### E2E

- `test_inference_e2e.py` — boot a fake VLA HTTP server (aiohttp.test_utils) that emits ee_delta chunks with mild motion; spin up an inference session against `mock_robot`; run 60 seconds; assert: zero `inference_error`, ≥1 chunk consumed, `safety_event` count below threshold, parquet+mp4 generated, recovered action stats fall within expected ranges. **REVIEW-tail assertion**: at the moment `episode_phase=review` is broadcast, capture the next 100 ms of dispatched commands; assert each delta is ≤ `max_joint_delta_per_step_deg` (the slow-stop tail must not exceed the per-tick clamp).

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
    type: "float"
    threshold: 0.5
    scope: "chunk"
    action_on_done: "auto_stop"

loop:
  prefetch_threshold: 0.5
  max_inflight: 1
```
