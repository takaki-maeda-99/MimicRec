# VLA Server Implementation Prompt

Hand this document to whoever (or whatever LLM) is implementing the VLA inference HTTP server that MimicRec will talk to. It captures the **hard requirements** MimicRec enforces — bend them and the client will reject your responses or produce dangerous robot motion.

For the corresponding client side, see `backend/mimicrec/inference/contract.py` (pydantic schema) and `configs/inference/gemma_libero_v1.yaml` (example contract). For the system design overview see `docs/superpowers/specs/2026-05-05-vla-inference-interface-design.md` §6.

---

## You are implementing

A small HTTP server that MimicRec calls in a closed control loop. On each call you receive **camera images + proprioceptive state + a natural-language instruction**, and you return a short **chunk of future actions** the robot should execute. MimicRec will run those actions through a safety filter and dispatch them to a real arm at 15–30 Hz.

There is **no retry**, no idempotency, no batching. Latency matters. Wrong output shapes are partially coerced: extra columns past index 6 are ignored, and a missing column 6 (gripper) becomes `None`; rows with fewer than 6 ee_delta floats will fail or produce wrong motion when the pose is constructed. See "Current client gaps" below for what is *not* yet validated. Wrong output magnitudes get clamped (safe) but break performance.

---

## HTTP endpoint

- One route: **`POST /predict`** (or any path you choose; the client's contract YAML names it).
- Request: `Content-Type: application/json`
- Response: `Content-Type: application/json`
- Status: `200 OK` on success, anything else is treated as an inference error (logged, dropped, slow-stop kicks in).
- Auth: client passes through whatever headers the contract YAML declares under `endpoint.headers` verbatim (env vars in values are interpolated). `Authorization: Bearer <token>` is just the conventional choice in the example config — any header name/value the server expects works.
- Concurrency: client uses `max_inflight=1` in MVP. You can serialize requests.

## Latency budget

Hard upper bound: **client timeout 5 s** (configurable, but increasing it just delays the inevitable slow-stop). Practical target derived from the chunk math:

```
chunk_duration = chunk_size / fps
latency_budget = chunk_duration / 2     # half-prefetch fires at 50% consumed
```

Examples:
- `chunk_size=16` @ 30 fps → 533 ms chunk → **~266 ms latency target**
- `chunk_size=8` @ 15 fps → 533 ms chunk → **~266 ms target**

Miss the target and `InferenceSafety` enters slow-stop (linear ramp to halt over 5 ticks). The next chunk usually catches up; chronic misses ruin the closed loop.

---

## Request body schema

Field names below are **examples**; the contract YAML on the client side maps your real field names. The shapes/types below are non-negotiable.

```jsonc
{
  // --- Images (one entry per camera the client is configured to send) ---
  // base64-encoded JPEG bytes. Already resized client-side to your declared
  // dimensions (default 224x224). Color space is RGB. JPEG quality is
  // configurable per camera (default 90).
  "image_primary": "<base64 jpeg>",      // typically a front-mounted camera
  "image_wrist":   "<base64 jpeg>",      // typically a wrist-mounted camera

  // --- Proprioceptive state ---
  // Flat array of floats. The order is dictated by the contract's
  // `request.state.components` list. For SO-101 with
  //   components: [joint_pos, gripper_pos]
  // the array is length 7: SO-101's `read_state()` returns joint_pos as a
  // 6-vector (5 arm joints + 1 packed gripper, all DEGREES) followed by
  // gripper_pos as a single scalar. **CAVEAT** (real-code gotcha, not
  // aspirational doc): SO101Adapter.read_state currently leaves
  // RobotState.gripper_pos as 0.0 — the gripper value lives in joint_pos[5].
  // So today the actual proprio is [j1..j5, gripper_packed, 0.0]. If you
  // condition on element 6 hoping for a redundant gripper signal, you'll
  // be reading a constant zero. This is a SO-101 adapter quirk, not the
  // contract's intent.
  // Units: joint_pos in DEGREES; gripper_pos normalized [-1, +1] (when populated).
  // Normalization: the contract YAML allows declaring
  // `request.state.normalization`, but the CLIENT DOES NOT APPLY IT TODAY
  // (see "Current client gaps" below). Today the values you receive are
  // always RAW. Plan accordingly.
  "proprio": [-8.31, -93.71, 96.44, 61.05, 20.88, 4.26, 0.00],

  // --- Natural-language instruction ---
  // UTF-8 string. May be empty in pre-start states; the client guards against
  // dispatching when state is None, so an empty instruction during READY is
  // valid (you should still produce a no-op-ish chunk; it's safer than 500).
  "instruction": "pick up the bottle",

  // --- Optional extra fields ---
  // Anything the contract declared as `extra_fields`. Usually fixed strings
  // like `model_version`. Use to disambiguate requests if you serve multiple
  // model variants from the same endpoint.
  "model_version": "gemma-libero-v1",

  // --- Optional timestamp map ---
  // The client sends per-source monotonic timestamps so you can verify the
  // images and state were captured at compatible times. If the spread is
  // huge (>1 chunk_duration), the chunk you produce is going to be stale
  // by the time it dispatches — return a smaller / safer chunk in that case.
  // (The `done` field is NOT a runtime escape hatch today — see
  // "Current client gaps".) Optional.
  "_t_mono_ns": {
    "state": 488772663507753,
    "image:front": 488772692294906,
    "image:wrist": 488772692451200,
    "instruction": 488772693000000
  }
}
```

### Hard request constraints

- All numeric values are JSON numbers (not strings).
- Image base64 strings are pure JPEG bytes, no `data:image/jpeg;base64,` prefix.
- `proprio` is a flat list, NOT nested. Length must be predictable.
- `instruction` is a string, never null.

---

## Response body schema

```jsonc
{
  // --- Action chunk ---
  // The client extracts this via JSONPath (`response.actions_path` in the
  // contract; default "actions"). Shape: N rows × 7 columns for SO-101 with
  // components: [ee_delta, gripper].
  // Each row is one future timestep; rows are in temporal order
  // (row[0] = next tick, row[-1] = furthest future).
  "actions": [
    [dx0, dy0, dz0, drx0, dry0, drz0, gripper0],
    [dx1, dy1, dz1, drx1, dry1, drz1, gripper1],
    ...
  ],

  // --- Optional model-side termination signal (NOT yet consumed at runtime) ---
  // OMIT this field entirely; it is currently a no-op. The contract schema
  // accepts `done.path / type / threshold / scope / action_on_done`, but
  // the producer does not read the field today. See "Current client gaps".
  // The shape is reserved as: type=float compares `value >= threshold`,
  // type=bool coerces directly, scope="chunk" applies to the whole chunk.
  // Per-step done is rejected at load time.
  "done": 0.7
}
```

### Hard response constraints

These are validated/exploited by `ActionDecoder`. Violations produce wrong robot motion.

1. **Action vector layout** matches the contract's `response.action.components`. For the default SO-101 contract:
   ```
   row = [ee_delta_x, ee_delta_y, ee_delta_z,         # position delta (3)
          ee_delta_rx, ee_delta_ry, ee_delta_rz,      # rotation as axis-angle (3)
          gripper]                                     # gripper command (1)
   ```
   Total length per row = 7. Order and length are non-negotiable.

2. **Pose units** are `meter_axisangle_rad`:
   - Position deltas in **meters**.
   - Rotation deltas as **axis-angle in radians** (NOT Euler, NOT quaternion). Magnitude of the 3-vector = rotation angle in radians; direction = rotation axis. A zero vector means no rotation.
   - This is the **only** units mode implemented in MVP. Submitting `mm_euler_deg` causes the client to reject the contract at load time.

3. **Pose frame** is what the contract declares (`ee_local` or `world`):
   - `ee_local` (default): each delta is expressed in the **end-effector's** local frame at the moment of that step. Rotation deltas compose right-multiplicatively: `T_next = T_curr · ΔT_local`.
   - `world`: deltas are in the world/base frame. `T_next = ΔT_world · T_curr`.

4. **Per-step deltas should be small.** The robot config has `max_joint_delta_per_step_deg = 2.0`; deltas larger than that are clamped. Clamping doesn't kill the robot but it makes your model's intended trajectory diverge from what's executed. Aim for **< 5 mm position, < 0.1 rad orientation** per step at 15 fps.

5. **Gripper convention** is per the contract YAML's `response.action.gripper`:
   - `kind: absolute, units: normalized_0_1` (default): float in `[0, 1]`. 0 = closed, 1 = open. Out-of-range values are passed through but the dispatcher may saturate.
   - `kind: delta`: emit the **change** from the current gripper position. Client adds it to the current value.
   - `kind: binary, units: binary_threshold_0p5`: emit any float; client returns `1.0` if `>= 0.5` else `0.0`.

6. **Normalization mode** is per `response.action.normalization.method`:
   - `none` (default and recommended): you emit physical units directly. No scaling on the client side.
   - `mean_std`: you emit normalized values. Client de-normalizes via `physical = mean + arr * std` using stats at `${MIMICREC_VLA_DEST_ROOT}/<dataset>/meta/action_stats.json`.
   - `minmax_neg1_pos1`: same formula. Convention: stats encode midpoint (`mean`) and half-range (`std`), so values in `[-1, +1]` map to `[mean - std, mean + std]`. Confirm your stats producer agrees.
   - **If the contract declares any non-`none` mode, the stats file MUST exist and its `mean`/`std` arrays MUST have length = sum(action.components dims) = 7 for the default SO-101 setup.** Mismatched length is a hard load-time error.

7. **Chunk size** SHOULD match `response.chunk.expected_size` (default 16). The contract declares `on_size_mismatch: use_actual | reject`, but **the client does not actually enforce `reject` today** — it always uses what you return (see "Current client gaps" below). Don't rely on chunk-size validation as a safety check; produce the right size yourself.

---

## Current client gaps (declared by the contract, NOT enforced today)

The contract YAML accepts these fields but the client doesn't act on them yet. If your design assumes any of these will save you, **it won't** — handle them yourself or ignore them.

1. **Request-side state normalization is not applied.** `request.state.normalization.method` is parseable as `none | mean_std | minmax_neg1_pos1`, but `_build_request_body()` always sends raw `RobotState` values. If your model needs normalized proprio, do the normalization server-side until this gap is closed.

2. **The `done` signal is parsed but not consumed.** You can include `done` in your response and the contract YAML can declare `done.path/type/threshold/scope/action_on_done`, but the producer doesn't read the field at runtime. `auto_stop` will not actually stop the episode today. The `gemma_libero_v1.yaml` example has the `done` block commented out for this reason.

3. **`response.chunk.on_size_mismatch: reject` is not enforced.** The decoder/producer accept whatever chunk you return; size mismatch is silent. Only `use_actual` semantics are implemented.

4. **Wrong action-row width is not validated as a hard error.** `ActionDecoder.decode` slices `arr[:6]` for the ee_delta and reads `arr[6]` only if `arr.shape[0] >= 7`. Specifically: extra columns past index 6 are silently ignored; a missing gripper column (length 6) becomes `gripper=None` and the safety filter holds the last gripper command; **rows shorter than 6 floats will not be caught** — the pose construction will use a too-short slice and produce wrong motion. Validate your row width yourself.

These are tracked as future-work items in `docs/superpowers/specs/2026-05-05-vla-inference-interface-design.md` §13. Don't design around them; design assuming they're not there.

## What MimicRec does on the client side (so you don't have to)

You **do not** need to:

- Apply joint limits (the safety filter clips per-step joint targets to robot config bounds).
- Smooth deltas across chunk boundaries (slow-stop covers the gap).
- Implement IK (the client uses placo IK on the configured URDF; your output is EE deltas).
- Predict an absolute EE pose (the client maintains `T_curr` and chains `ΔT` through the chunk).
- Worry about gripper passthrough during empty buffer; client holds last gripper command.

You **do** need to:

- Be deterministic enough that disabled retry isn't a problem (don't sample stochastically without a seed unless you accept the variance).
- Produce small, smooth deltas. Spiky outputs cause the safety filter to clamp constantly, which the operator will see as `clamps_per_chunk` rising.
- Respect the latency budget. Sustained misses ruin the closed loop.

---

## Failure semantics

When you fail (non-200, malformed JSON, schema mismatch), MimicRec:

1. Logs an `inference_error` event to its WebSocket telemetry.
2. Does NOT retry the same request.
3. Drops the dispatcher into slow-stop until the next chunk arrives.
4. Continues the producer loop with exponential backoff (100 ms → 1 s) before the next request.

This means **transient errors are graceful but visible**. A 500 every other request will keep the robot in slow-stop limbo. Aim for ≥ 99% success in steady state.

---

## A minimal reference server (Python, FastAPI)

```python
# A skeleton you can fill in with your real model.
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
import base64
import io
import numpy as np
from PIL import Image

app = FastAPI()


class PredictRequest(BaseModel):
    # populate_by_name + alias is required because pydantic v2 reserves
    # leading-underscore names as private fields. The wire format uses
    # `_t_mono_ns` (underscore-prefixed); we expose it as `t_mono_ns`.
    model_config = ConfigDict(populate_by_name=True)

    image_primary: str
    image_wrist: str | None = None
    proprio: list[float]
    instruction: str
    model_version: str | None = None
    t_mono_ns: dict | None = Field(default=None, alias="_t_mono_ns")


class PredictResponse(BaseModel):
    actions: list[list[float]]
    done: float | None = None


def decode_image(b64: str) -> np.ndarray:
    raw = base64.b64decode(b64)
    return np.array(Image.open(io.BytesIO(raw)).convert("RGB"))   # H×W×3 uint8 RGB


@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest) -> PredictResponse:
    if len(req.proprio) != 7:                         # SO-101 default contract
        raise HTTPException(400, f"proprio must be length 7, got {len(req.proprio)}")
    img_front = decode_image(req.image_primary)        # 224×224 RGB
    img_wrist = decode_image(req.image_wrist) if req.image_wrist else None

    # ----------------------- YOUR MODEL GOES HERE -----------------------
    # Inputs: img_front, img_wrist, np.array(req.proprio), req.instruction
    # Outputs: list of 16 (or chunk_size) action vectors, each length 7:
    #   [Δx, Δy, Δz, Δrx, Δry, Δrz, gripper] in meters / axis-angle radians
    #   / normalized [0,1] gripper.
    # Keep |Δposition| < 5 mm and |Δorientation| < 0.1 rad per step.
    chunk_size = 16
    actions = [[0.001, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5] for _ in range(chunk_size)]
    # --------------------------------------------------------------------

    return PredictResponse(actions=actions)
```

---

## Pre-flight checks before pointing the real client at you

Run MimicRec's `scripts/smoke_inference_real_data.py` against your server (just change `endpoint.url` in `configs/inference/<your-config>.yaml`). If it prints `✅ inference mock pipeline works end-to-end with real data` and the IK failures are `0/N` for a sane initial pose, the wire format is correct.

If you fail any of:

- `proprio length: 7` — you sent the wrong number of floats in your test rig
- `IK failures: 0/N` — your deltas may be too large; try smaller magnitudes
- `step 0 joint drift from seed: <5° (OK)` — same as above; check magnitudes

Then your contract or your model output is misconfigured.

---

## Notes for future expansion (NOT MVP, do not implement yet)

- **Per-step `done`** (`response.done.scope: step`): client rejects this at load time today.
- **`mm_euler_deg` units**: same.
- **Other action types** (`joint_position`, `joint_delta`, `ee_pose` absolute): the client only implements `ee_delta`. Adding more requires a coordinated client + server change.
- **`max_inflight > 1`**: the client pins it to 1; you don't need to support overlapping requests yet.

If you need any of these, file a request that points at this document so we can update the spec and the client together.
