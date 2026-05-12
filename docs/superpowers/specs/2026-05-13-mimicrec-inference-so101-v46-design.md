# MimicRec → X-VLA-Adapter SO101 v46 inference integration

**Date**: 2026-05-13
**Status**: design — implementation plan pending
**Scope**: connect MimicRec's existing inference mode to the user's running
X-VLA-Adapter HTTP server (deploy config `so101_v46.yaml`, predictor
`xvla_adapter`). Smoke verification of end-to-end wire is the goal; real-arm
action correctness is **not** in scope (`wire_only_smoke: true` on the server).

## 1. Background

MimicRec already has a complete inference subsystem in
`backend/mimicrec/inference/` (client, contract loader, chunk buffer, control
loop, safety, producer, action decoder). The action decoder handles both
`frame: ee_local` and `frame: world` via left/right matrix multiplication. The
existing contract YAMLs in `configs/inference/` pair with LIBERO-style
checkpoints whose proprio is `[joint_pos, gripper_pos]`.

The new server is `~/X-VLA-Adapter`, deploy config
`configs/deploy/so101_v46.yaml`. It expects proprio
`[ee_pos(3, m) + ee_rotvec(3, rad) + gripper(1, normalized 0..1)]` = 7 floats,
returns `actions: list[list[float]]` with chunk_len=8 and action dim 7
(`[dxyz, d_rotvec_logmap, gripper]`). Server-side q99 normalization on both
proprio (in) and action (out), so MimicRec sends/receives physical units.

MimicRec's existing `InferenceClient._build_request_body` only knows how to
encode `joint_pos` and `gripper_pos` as proprio components; it has no
`ee_pos`/`ee_rotvec` support and no gripper raw-to-normalized mapping.

## 2. Goals & non-goals

**Goals**
- Add `ee_pos`, `ee_rotvec` as supported `state.components` in MimicRec's
  contract + client.
- Compute EE pose via the existing `FKService` (`self._fk` in lifecycle).
- Normalize SO101's packed-gripper (0..100) to 0..1 via `GripperConvention` +
  the adapter's proprio layout.
- Ship a new contract YAML at `configs/inference/so101_v46.yaml` paired with
  the server's `so101_v46.yaml` deploy.
- Fail fast at session start when contract requires wiring the adapter cannot
  satisfy (FK, gripper source, required image roles).
- Fix three adjacent pre-existing defects on paths we are already touching
  (action_decoder narm, IK-success T_curr drift, action row length check).

**Non-goals**
- Real-arm correctness. Server's `wire_only_smoke: true` means action chunks
  are not expected to move the SO101 correctly. Smoke verification is the goal.
- A frame-conversion implementation in X-VLA-Adapter (world → ee_local). Out
  of scope; sits on the server side.
- SO101 gripper actuation from server's action chunk. SO101 currently has no
  `send_gripper_command`; the returned gripper value is dropped in the
  dispatcher. Documented as a known limitation; consistent with smoke-only.
- UI smoke-mode banner / confirmation. Separate task.

## 3. Design

### 3.1 New contract YAML — `configs/inference/so101_v46.yaml`

```yaml
name: so101_v46
description: "X-VLA-Adapter SO101 v46 FT ckpt (wire_only_smoke; actions not validated on real arm)."

endpoint:
  url: "http://localhost:8001/predict"
  method: POST
  timeout_s: 5.0
  retry: { max_attempts: 0 }

request:
  images:
    front: { field: image_primary, encoding: jpeg_base64, resize: [224, 224], jpeg_quality: 90 }
    wrist: { field: image_wrist,   encoding: jpeg_base64, resize: [224, 224], jpeg_quality: 90 }
  state:
    field: proprio
    components: [ee_pos, ee_rotvec, gripper_pos]
    normalization: { method: none }   # server normalizes via q99
  instruction:
    field: instruction
  extra_fields:
    model_version: x_vla_so101_v46

response:
  actions_path: actions
  chunk:
    expected_size: 8
    on_size_mismatch: reject           # fixed-8 ckpt; refuse any mismatch
  action:
    type: ee_delta
    frame: world                      # matches deploy.contract.frame=world
    pose: { units: meter_axisangle_rad }
    gripper: { kind: absolute, units: normalized_0_1 }
    components: [ee_delta, gripper]
    normalization: { method: none }   # server denormalizes via q99
```

Notes:
- `state.components` order matches the server's deploy
  `proprio.source.components` order (ee_pos, ee_rotvec, gripper).
- `frame: world` is the server's truth. The decoder's world-frame branch
  (`T_next = T_delta @ T_curr`, `action_decoder.py:90`) already exists.
- `on_size_mismatch: reject` — server returns fixed 8; the loosely-permissive
  `use_actual` default would silently mask checkpoint mismatches. The
  `reject` literal is already declared in `contract.py:88` but has no
  enforcement; §3.5 adds the enforcement.

### 3.2 contract.py — component registry

`backend/mimicrec/inference/contract.py`:

```python
_DIM_REGISTRY: dict[str, int | str] = {
    "joint_pos": "Narm",
    "gripper_pos": 1,
    "ee_pos": 3,        # new
    "ee_rotvec": 3,     # new
}
```

Additionally, post-load validation:
- Compute `expected_state_dim = _expected_dim(request.state.components)`.
- Log it at INFO. Out-of-band consistency checking against the server is not
  possible (we don't know server's deploy yaml at runtime), so this is for
  developer feedback when authoring contracts.

### 3.3 InferenceClient — state encoding with FK + gripper normalization

`backend/mimicrec/inference/client.py`:

```python
from mimicrec.adapters.types import GripperConvention, ProprioLayout

@dataclass
class InferenceClient:
    spec: ContractSpec
    fk: "FKLike | None" = None
    gripper_convention: GripperConvention | None = None
    proprio_layout: ProprioLayout | None = None
    _client: httpx.AsyncClient | None = None
```

State encode (`_encode_state`, refactored out of `_build_request_body`):

```python
def _encode_state(self, state: RobotState) -> list[float]:
    out: list[float] = []
    T_ee: np.ndarray | None = None

    def _ensure_T() -> np.ndarray:
        nonlocal T_ee
        if T_ee is not None:
            return T_ee
        if state.ee_pos is not None and state.ee_rotvec is not None:
            T = np.eye(4); T[:3, 3] = state.ee_pos
            if np.linalg.norm(state.ee_rotvec) > 1e-9:
                T[:3, :3] = R.from_rotvec(state.ee_rotvec).as_matrix()
            T_ee = T
        else:
            if self.fk is None:
                raise ValueError(
                    "contract requires ee_pos/ee_rotvec but FKService is not wired"
                )
            n = self.fk.n_kin_joints
            T_ee = self.fk.matrix(state.joint_pos[:n].astype(np.float64))
        return T_ee

    for comp in self.spec.request.state.components:
        if comp == "joint_pos":
            out.extend(state.joint_pos.tolist())
        elif comp == "ee_pos":
            T = _ensure_T()
            out.extend(T[:3, 3].tolist())
        elif comp == "ee_rotvec":
            T = _ensure_T()
            out.extend(R.from_matrix(T[:3, :3]).as_rotvec().tolist())
        elif comp == "gripper_pos":
            out.append(self._normalized_gripper(state))
        else:
            raise ValueError(f"unsupported state component: {comp}")
    return out

def _normalized_gripper(self, state: RobotState) -> float:
    """Always normalize via convention. Do NOT trust the unit of
    `state.gripper_pos` blindly — different adapters populate it from
    different sources. The convention maps raw → [0,1]; the proprio_layout
    tells us *where* the raw value lives.

    Supported `gripper_via_column`:
      - "observation.state.joint_pos": raw = state.joint_pos[index]  (SO101)
      - "observation.state.gripper_pos": raw = state.gripper_pos      (reBot)
    """
    if self.gripper_convention is None or self.proprio_layout is None:
        raise ValueError(
            "contract requires gripper_pos but gripper_convention / "
            "proprio_layout are not wired"
        )
    gc = self.gripper_convention
    pl = self.proprio_layout

    if pl.gripper_via_column == "observation.state.joint_pos":
        if pl.gripper_index_in_column >= state.joint_pos.shape[0]:
            raise ValueError(
                f"gripper index {pl.gripper_index_in_column} out of range "
                f"for joint_pos length {state.joint_pos.shape[0]}"
            )
        raw = float(state.joint_pos[pl.gripper_index_in_column])
    elif pl.gripper_via_column == "observation.state.gripper_pos":
        if state.gripper_pos is None:
            raise ValueError(
                "contract requires gripper_pos sourced from state.gripper_pos, "
                "but state.gripper_pos is None"
            )
        raw = float(state.gripper_pos)
    else:
        # Should be unreachable when startup validation is in place; defensive.
        raise ValueError(
            f"unsupported gripper_via_column {pl.gripper_via_column!r}; "
            f"expected 'observation.state.joint_pos' or "
            f"'observation.state.gripper_pos'"
        )

    span = gc.open_at - gc.closed_at  # non-zero by GripperConvention.__post_init__
    return float(np.clip((raw - gc.closed_at) / span, 0.0, 1.0))
```

Image-missing handling (`_build_request_body`):
- Required image roles (those listed in `request.images`) MUST be present.
- Today's silent `if stamped is None: continue` is preserved only for cameras
  flagged as optional in a future contract version. For so101_v46 every
  `request.images` key is required → raise `ValueError` if any is missing.
  Initial implementation: simple — every key in `request.images` is required.

### 3.4 Lifecycle wiring

`backend/mimicrec/session/lifecycle.py`:

1. **Construct `InferenceClient` with the three injections** (line ~944):

```python
new_client = InferenceClient(
    spec=contract,
    fk=self._fk,
    gripper_convention=self._robot.default_gripper_convention(),
    proprio_layout=self._robot.proprio_layout(),
)
```

`SO101Adapter.proprio_layout()` exists as a classmethod
(`backend/mimicrec/adapters/so101.py:71`, also on `RebotArmZmqAdapter:40`,
consumed in `api/deps.py:338`), so the accessor is already in place.

2. **Broadened startup validation** (Phase 1, before destructive phase):

```python
state_components = set(contract.request.state.components)

# (a) ee_pos / ee_rotvec require FK
if {"ee_pos", "ee_rotvec"} & state_components and self._fk is None:
    raise InvalidTransitionError(
        f"contract requires {state_components & {'ee_pos','ee_rotvec'}} "
        f"but FKService is not configured"
    )

# (b) gripper_pos requires both convention + proprio_layout + supported source
if "gripper_pos" in state_components:
    if self._robot.default_gripper_convention() is None:
        raise InvalidTransitionError(
            "contract requires gripper_pos but adapter has no GripperConvention"
        )
    pl = self._robot.proprio_layout()
    if pl is None:
        raise InvalidTransitionError(
            "contract requires gripper_pos but adapter has no ProprioLayout"
        )
    SUPPORTED_GRIPPER_COLS = {
        "observation.state.joint_pos",
        "observation.state.gripper_pos",
    }
    if pl.gripper_via_column not in SUPPORTED_GRIPPER_COLS:
        raise InvalidTransitionError(
            f"adapter's gripper_via_column={pl.gripper_via_column!r} is not "
            f"a supported source for inference encoding; supported: "
            f"{sorted(SUPPORTED_GRIPPER_COLS)}"
        )

# (c) every image role in the contract must be a configured camera slot
required_image_keys = set(contract.request.images.keys())
configured_cameras = set(self._camera_slots.keys())
missing = required_image_keys - configured_cameras
if missing:
    raise InvalidTransitionError(
        f"contract requires image roles {sorted(missing)} but those camera "
        f"slots are not configured"
    )
```

3. **Pre-existing bug fix: `narm`** (line ~941):

```python
new_decoder = ActionDecoder(
    spec=contract, fk=self._fk, ik=new_ik,
    narm=self._fk.n_kin_joints,    # was: self._robot.dof
    action_stats=action_stats,
)
```

For SO101 this changes 6 → 5. placo's `forward_kinematics` is currently
"accidentally tolerant" of a 6-vec because it only reads the 5 joints it knows
about, but the design intent is explicit: pass the kinematic-joint vector,
not the full robot DoF (which packs the gripper).

### 3.5 ActionDecoder — adjacent fixes

`backend/mimicrec/inference/action_decoder.py`:

1. **Validate action row length** before slicing `arr[:6]`/`arr[6]`:

```python
expected_action_dim = _expected_dim(self.spec.response.action.components)
# in decode():
for raw in actions:
    if len(raw) != expected_action_dim:
        raise ValueError(
            f"action row length {len(raw)} != expected {expected_action_dim} "
            f"from components {self.spec.response.action.components}"
        )
```

2. **Use achieved FK after IK success** (line 102):

```python
# was: T_curr = T_next
T_curr = self.fk.matrix(q_next)
```

This makes subsequent chunk steps chain from the actually-achieved pose, not
the model's ideal. The failure path already does this (line 100); the
success path was inconsistent. Eight-step chunks especially benefit because
small per-step residuals compound.

3. **`on_size_mismatch: reject` enforcement**:

The `reject` literal already exists in `contract.py:88` but is dead — no
code branches on it. Add enforcement in `ActionDecoder.decode`, right after
`_extract_actions` and before the row loop:

```python
chunk = self._extract_actions(response_body)
expected = self.spec.response.chunk.expected_size
mode = self.spec.response.chunk.on_size_mismatch
if mode == "reject" and len(chunk) != expected:
    raise ValueError(
        f"chunk size {len(chunk)} != expected {expected}; "
        f"contract on_size_mismatch=reject"
    )
# mode == "use_actual": existing behavior — process whatever length we got
```

For so101_v46 (fixed-8 ckpt), this fails fast on checkpoint/contract mismatch.

## 4. Data flow (so101_v46)

```
SO101Adapter.read_state()
  → RobotState(joint_pos=[6 floats incl gripper@5], ee_pos=None, ee_rotvec=None, gripper_pos=None)
InferenceClient._build_request_body
  - jpeg_b64(front frame) → image_primary
  - jpeg_b64(wrist frame) → image_wrist
  - _encode_state:
      T = fk.matrix(joint_pos[:5])
      ee_pos = T[:3,3]                                    (3 floats, meter)
      ee_rotvec = R.from_matrix(T[:3,:3]).as_rotvec()     (3 floats, rad)
      gripper = (joint_pos[5] - 0) / (100 - 0)            (1 float, [0,1])
  → proprio = [ee_pos(3), ee_rotvec(3), gripper(1)] = 7 floats
  - instruction passthrough
  - extras: model_version, _t_mono_ns
POST http://localhost:8001/predict
  ← {"actions": [[dxyz(3), drotvec(3), gripper(1)], ... × 8]}  (physical units, world frame)
ActionDecoder.decode (per row)
  - length check: len(row) == 7
  - de_normalize: pass-through (method=none)
  - T_delta = SE3(dxyz, drotvec)
  - T_next = T_delta @ T_curr                             (world-frame compose)
  - q_next = IK(T_next, seed=seed_q)
  - T_curr = fk.matrix(q_next)                            (use achieved pose)
  - StepAction(q=q_next, gripper=row[6], ik_failed=...)
Dispatcher
  - send_joint_command(q_next)
  - SO101 has no send_gripper_command → step.gripper dropped (known smoke
    limitation; spec §2 non-goals).
```

## 5. Error handling

All error paths flow through the existing `error_bus` + WS publish mechanism.
Failure modes added by this work:

| Trigger | Where | Type | Surface |
|---|---|---|---|
| FK unavailable + contract needs ee_pos | lifecycle Phase 1 | `InvalidTransitionError` | start_inference_session 4xx + UI toast |
| Gripper source missing | lifecycle Phase 1 | `InvalidTransitionError` | same |
| Required image role not in cameras | lifecycle Phase 1 | `InvalidTransitionError` | same |
| Required image missing at predict time | client `_build_request_body` | `ValueError` | producer `classify` → `schema` → error_bus |
| Server 4xx (e.g. typo guard, instruction too long) | client `predict` | `httpx.HTTPStatusError` | producer → `transport` → error_bus |
| Action row length mismatch | action_decoder | `ValueError` | producer → `schema` |
| Chunk size mismatch in `reject` mode | action_decoder | `ValueError` | producer → `schema` |
| Gripper index out of range | client `_normalized_gripper` | `ValueError` | producer → `schema` |
| Unsupported `gripper_via_column` | lifecycle Phase 1 | `InvalidTransitionError` | start_inference_session 4xx + UI toast |
| IK failure | action_decoder | `StepAction.ik_failed=True` | safety slow-stop (existing) |

## 6. Testing

### 6.1 Unit tests

| File | Cases |
|---|---|
| `tests/unit/inference/test_contract.py` (extend) | `_DIM_REGISTRY` resolves ee_pos→3, ee_rotvec→3; `_expected_dim([ee_pos, ee_rotvec, gripper_pos]) == 7`; contract loads with new components |
| `tests/unit/inference/test_client_state_encode.py` (new) | (a) FK called once even with both ee_pos+ee_rotvec; (b) FK skipped when state.ee_pos/ee_rotvec pre-populated; (c) gripper normalized via convention via joint_pos column (0→0.0, 50→0.5, 100→1.0); (d) gripper normalized via state.gripper_pos column (reBot-style); (e) clipping at bounds; (f) fk=None + ee_pos in contract → ValueError; (g) gripper_convention/proprio_layout=None + gripper_pos in contract → ValueError; (h) gripper_index_in_column out of range for joint_pos → ValueError; (i) gripper_via_column = "observation.state.gripper_pos" with state.gripper_pos=None → ValueError |
| `tests/unit/inference/test_client_request_body.py` (new) | Field names match contract (image_primary/_wrist, proprio, instruction, model_version); proprio order = contract.state.components order; missing required image → ValueError |
| `tests/unit/session/test_lifecycle_inference_start.py` (extend) | (a) ee_pos contract + fk=None → InvalidTransitionError; (b) gripper_pos contract + no convention → InvalidTransitionError; (c) missing camera role → InvalidTransitionError; (d) unsupported gripper_via_column → InvalidTransitionError; (e) happy path: InferenceClient constructed with fk + gripper_convention + proprio_layout; (f) narm passed to ActionDecoder == fk.n_kin_joints |
| `tests/unit/inference/test_action_decoder.py` (extend) | (a) row-length mismatch raises; (b) T_curr after success == FK(q_next), not T_next; (c) `on_size_mismatch: reject` raises on size mismatch, `use_actual` passes through |

### 6.2 Contract snapshot

`tests/unit/inference/test_so101_v46_contract.py` (new):

```python
def test_so101_v46_yaml_fields():
    spec = ContractSpec.from_yaml("configs/inference/so101_v46.yaml")
    assert spec.request.state.components == ["ee_pos", "ee_rotvec", "gripper_pos"]
    assert spec.response.action.frame == "world"
    assert spec.response.chunk.expected_size == 8
    assert spec.response.chunk.on_size_mismatch == "reject"
    assert spec.response.action.normalization.method == "none"
    assert spec.endpoint.url == "http://localhost:8001/predict"
```

Catches drift between contract YAML and code interpretation. The deploy YAML
on the server side is not validated against (different repo); operator
discipline keeps them aligned, with the contract YAML's `description` field
documenting the pairing.

### 6.3 Integration test

`tests/integration/test_inference_so101_v46_e2e.py` (new):

- Spin up an in-process `pytest-httpx` mock that asserts request body shape
  (`image_primary`, `image_wrist`, `proprio` length 7, etc.) and returns a
  fixed chunk of 8 rows × 7 floats.
- Feed `RobotState(joint_pos=[0]*5 + [50], ...)` (gripper raw at 50).
- Run client.predict → decoder.decode end-to-end.
- Assert each decoded `StepAction.q` has the right dim, IK either solved or
  marked failed (whichever the test fixture targets), gripper carries through.
- Verify per-row length validation rejects malformed responses.

### 6.4 Manual smoke (CI exempt)

**MUST run against the sim bridge, not the physical SO101.** The server is
`wire_only_smoke: true`; action chunks are not expected to be correct in
world-frame. Sending them to a real arm risks unsafe motion. The smoke run
exercises HTTP shape + decode + dispatch intent — it does NOT validate that
the policy moves an arm correctly.

```bash
# Terminal 1: VLA server
cd ~/X-VLA-Adapter
uv run python scripts/serve.py \
  --predictor xvla_adapter \
  --checkpoint <ckpt_export_dir> \
  --deploy-config configs/deploy/so101_v46.yaml \
  --domain-id 0 --port 8001

# Terminal 2: sim bridge (publishes joint state and accepts joint commands)
cd ~/MimicRec
.venv/bin/python scripts/sim_bridge_dummy.py   # or one of scripts/sim_bridge_*.py

# Terminal 3: MimicRec backend pointed at the sim adapter, not the real arm
ROBOT_CONFIG=configs/robot/sim_so101.yaml bash scripts/run.sh
# UI: select so101_v46 contract → start inference
```

Pass criteria:
- Server log shows `POST /predict 200` rate consistent with control loop.
- UI shows "inference active" with no error_bus events.
- Action chunks reach `dispatcher.send_joint_command` and the sim bridge
  observes incoming commands. Sim motion correctness is not asserted —
  this is wire verification only.

**Real-arm physical smoke is explicitly NOT a pass criterion for this
work.** Promotion to physical SO101 requires (at minimum) a
contract-frame-trained checkpoint and a separate go/no-go review. See §7.

## 7. Known limitations

0. **No physical-arm actuation in this work.** The server is
   `wire_only_smoke: true` with `frame: world` + `frame_conversion: none`,
   which is not safe for the physical SO101. The deliverable validates HTTP
   wire + decode + dispatch intent only, against the sim bridge. Physical
   actuation is gated on a follow-up that requires a contract-frame-trained
   checkpoint and a separate review.
1. **Gripper actions not actuated on SO101.** SO101 has no
   `send_gripper_command`; `StepAction.gripper` is silently dropped in the
   dispatcher. Server's gripper output has no effect on the physical arm.
   Acceptable for smoke testing the HTTP/decode path. Fix is out of scope.
2. **`wire_only_smoke: true` on the server side.** The server's `so101_v46`
   deploy declares `frame: world` and `frame_conversion: none`, but real SO101
   deployment would want `ee_local`. The server explicitly skips that assert
   for smoke testing. MimicRec mirrors `frame: world` to stay consistent, but
   the resulting commands are not expected to be correct for real-arm use.
3. **No automated contract-vs-deploy YAML validation across the two repos.**
   When upgrading the server checkpoint or deploy config, the operator must
   manually align MimicRec's `configs/inference/so101_v46.yaml`. The
   `description` field is the only cross-repo documentation hook.

## 8. Implementation order

1. Add `ee_pos`/`ee_rotvec` to `_DIM_REGISTRY` + contract loader tests.
2. Refactor `InferenceClient._build_request_body` → `_encode_state` helper,
   add fk/gripper_convention/proprio_layout fields and the new component
   handlers. Required-image enforcement. Unit tests.
3. Lifecycle: inject fk/convention/layout; broaden startup validation;
   change `narm` to `n_kin_joints`. Tests.
4. ActionDecoder: row-length check + `T_curr = fk.matrix(q_next)` on
   success + `on_size_mismatch: reject` enforcement. Tests.
5. Write `configs/inference/so101_v46.yaml` + snapshot test.
6. Integration test (mocked server).
7. Manual smoke against real server.

Each step keeps existing contract YAMLs (gemma_libero_v1, x_vla_v36_*)
working — additions are opt-in via new component names or new error modes.
