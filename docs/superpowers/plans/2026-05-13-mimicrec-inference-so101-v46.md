# MimicRec → X-VLA-Adapter so101_v46 inference integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire MimicRec's existing inference mode to a running X-VLA-Adapter
HTTP server (deploy `so101_v46.yaml`, predictor `xvla_adapter`), so it can
send EE-pose proprio + JPEG images and decode the returned ee_delta chunks
back to joint commands. Smoke verification against the sim bridge only;
real-arm motion is explicitly out of scope (`wire_only_smoke: true`).

**Architecture:** Add `ee_pos`/`ee_rotvec` as supported `state.components`
in `contract.py`'s `_COMPONENT_DIM`. Refactor `InferenceClient` to compute
EE pose from `RobotState.joint_pos` via the existing `FKService`, and
normalize the gripper from raw units via the adapter's `GripperConvention`
+ `ProprioLayout`. Wire the three new dependencies into `InferenceClient`
from `session/lifecycle.py`, with broadened startup-time validation. Bundle
three adjacent fixes in `ActionDecoder` (correct `narm`, validate action
row length, recompute `T_curr` from `FK(q_next)` on IK success) and enforce
`on_size_mismatch: reject` (the literal exists in `contract.py:88` but has
no enforcement). Ship a new contract YAML at `configs/inference/so101_v46.yaml`.

**Tech Stack:** Python 3.12 / `uv`, pydantic v2 (`contract.py`), `httpx`
async client, `numpy`, `scipy.spatial.transform.Rotation`, `placo`/pinocchio
via `FKService`, pytest, `aiohttp.web` for in-process mocked server.

**Spec reference:** `docs/superpowers/specs/2026-05-13-mimicrec-inference-so101-v46-design.md`

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `backend/mimicrec/inference/contract.py` | Modify | Add `ee_pos`/`ee_rotvec` to `_COMPONENT_DIM` |
| `backend/mimicrec/inference/client.py` | Modify | Add `fk`/`gripper_convention`/`proprio_layout` fields; refactor `_build_request_body` to use `_encode_state`; enforce required images |
| `backend/mimicrec/inference/action_decoder.py` | Modify | Validate row length; recompute `T_curr` on IK success; enforce `on_size_mismatch: reject` |
| `backend/mimicrec/session/lifecycle.py` | Modify | Inject 3 new deps into `InferenceClient`; broaden startup validation; fix `narm` |
| `configs/inference/so101_v46.yaml` | Create | New contract paired with X-VLA-Adapter so101_v46 deploy |
| `tests/unit/test_inference_contract.py` | Extend | Cover new components in registry |
| `tests/unit/test_inference_client.py` | Extend + Modify | Cover state encoding + required image enforcement; update legacy `test_client_round_trip` to inject convention+layout |
| `tests/unit/test_inference_action_decoder.py` | Extend | Cover row length, T_curr-on-success, reject mode |
| `tests/unit/test_inference_so101_v46_contract.py` | Create | Snapshot test for the new YAML |
| `tests/integration/test_inference_lifecycle.py` | Extend | Cover lifecycle wiring + startup validation |
| `tests/integration/test_inference_so101_v46_e2e.py` | Create | Mocked-server end-to-end shape verification |

Test files live under a flat `tests/unit/test_inference_*.py` layout (no
nested `tests/unit/inference/` subdir).

**Task ordering note:** Task 8 ships the `so101_v46.yaml` contract BEFORE
Tasks 9-10 (lifecycle), so the integration-style tests can `from_yaml_text(
path.read_text())` the real file rather than maintaining a parallel fixture.
The unit tests in Tasks 5-7 keep using inline YAML for isolation.

**Lifecycle API truth:** `SessionManager.start_inference_session(contract:
ContractSpec, instruction: str, inference_config_name: str)` — takes a
**`ContractSpec` object**, NOT a path. Load the YAML in the test via
`ContractSpec.from_yaml_text(Path(...).read_text())`.

---

## Task 1: contract.py — add ee_pos, ee_rotvec to component registry

**Files:**
- Modify: `backend/mimicrec/inference/contract.py:131-136`
- Test: `tests/unit/test_inference_contract.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_inference_contract.py`:

```python
def test_component_registry_includes_ee_pose():
    from mimicrec.inference.contract import _COMPONENT_DIM, _expected_dim
    assert _COMPONENT_DIM["ee_pos"] == 3
    assert _COMPONENT_DIM["ee_rotvec"] == 3
    assert _expected_dim(["ee_pos", "ee_rotvec", "gripper_pos"]) == 7


def test_contract_loads_with_ee_pose_components():
    yaml_with_ee = YAML_OK.replace(
        "components: [joint_pos, gripper_pos]",
        "components: [ee_pos, ee_rotvec, gripper_pos]",
    )
    spec = ContractSpec.from_yaml_text(yaml_with_ee)
    assert spec.request.state.components == ["ee_pos", "ee_rotvec", "gripper_pos"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_inference_contract.py -v -k "ee_pose"`
Expected: FAIL — `KeyError: 'ee_pos'` or `_expected_dim` raise.

- [ ] **Step 3: Add the registry entries**

Edit `backend/mimicrec/inference/contract.py:131-136`:

```python
_COMPONENT_DIM: dict[str, int | str] = {
    "joint_pos": "Narm",
    "gripper_pos": 1,
    "ee_pos": 3,
    "ee_rotvec": 3,
    "ee_delta": 6,
    "gripper": 1,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_inference_contract.py -v`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/inference/contract.py tests/unit/test_inference_contract.py
git commit -m "feat(inference): register ee_pos/ee_rotvec state components"
```

---

## Task 2: ActionDecoder — validate action row length

**Files:**
- Modify: `backend/mimicrec/inference/action_decoder.py:73-77`
- Test: `tests/unit/test_inference_action_decoder.py`

- [ ] **Step 1: Read the existing test file to copy its YAML/factory style**

Run: `sed -n '1,80p' tests/unit/test_inference_action_decoder.py` to see
the existing fixtures. Reuse them — do not introduce a parallel factory.

- [ ] **Step 2: Write the failing test**

Append to `tests/unit/test_inference_action_decoder.py` (assumes
`YAML_CONTRACT` and decoder construction helpers exist in that file; if
not, copy the pattern from the first existing test in the file):

```python
def test_decode_rejects_wrong_row_length():
    import numpy as np
    from mimicrec.inference.action_decoder import ActionDecoder
    from mimicrec.inference.contract import ContractSpec
    from mimicrec.kinematics.fk import FKService, KinematicsConfig
    from mimicrec.kinematics.ik import IKService
    from mimicrec.types import RobotState

    spec = ContractSpec.from_yaml_text(YAML_CONTRACT)  # reuse existing top-of-file YAML
    fk_cfg = KinematicsConfig(
        urdf_path="configs/urdf/so101/so101.urdf",
        target_frame="gripper_frame_link",
        joint_names=["shoulder_pan","shoulder_lift","elbow_flex","wrist_flex","wrist_roll"],
    )
    fk = FKService(fk_cfg); ik = IKService(fk_cfg)
    decoder = ActionDecoder(spec=spec, fk=fk, ik=ik, narm=fk.n_kin_joints, action_stats=None)

    state = RobotState(
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
    )
    bad = {"actions": [[0.0]*6]}  # 6 floats instead of 7 (missing gripper)

    with pytest.raises(ValueError, match="action row length 6 != expected 7"):
        decoder.decode(bad, state)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_inference_action_decoder.py::test_decode_rejects_wrong_row_length -v`
Expected: FAIL — silent slicing of `arr[:6]` does not raise.

- [ ] **Step 4: Implement the length check**

Edit `backend/mimicrec/inference/action_decoder.py`. First add the import
near the existing `from mimicrec.inference.contract import ContractSpec`:

```python
from mimicrec.inference.contract import ContractSpec, _expected_dim
```

Then modify `decode()` (around line 73). Replace:

```python
def decode(self, response_body: dict, current_state: RobotState) -> list[StepAction]:
    actions = self._extract_actions(response_body)
    seed_q = current_state.joint_pos[:self.narm].copy()
    T_curr = self.fk.matrix(seed_q)
    chunk: list[StepAction] = []
    for raw in actions:
        arr = np.asarray(raw, dtype=np.float64)
```

with:

```python
def decode(self, response_body: dict, current_state: RobotState) -> list[StepAction]:
    actions = self._extract_actions(response_body)
    expected_action_dim = _expected_dim(self.spec.response.action.components)
    seed_q = current_state.joint_pos[:self.narm].copy()
    T_curr = self.fk.matrix(seed_q)
    chunk: list[StepAction] = []
    for raw in actions:
        if len(raw) != expected_action_dim:
            raise ValueError(
                f"action row length {len(raw)} != expected {expected_action_dim} "
                f"from components {self.spec.response.action.components}"
            )
        arr = np.asarray(raw, dtype=np.float64)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_inference_action_decoder.py -v`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add backend/mimicrec/inference/action_decoder.py tests/unit/test_inference_action_decoder.py
git commit -m "fix(inference): validate action row length in ActionDecoder.decode"
```

---

## Task 3: ActionDecoder — recompute T_curr from FK(q_next) on IK success

**Files:**
- Modify: `backend/mimicrec/inference/action_decoder.py:97-102`
- Test: `tests/unit/test_inference_action_decoder.py`

This task proves the fix by asserting that with chained chunks, IK's
second target equals `FK(q_next_step1)` rather than the idealized
`T_next_step1`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_inference_action_decoder.py`:

```python
def test_t_curr_chains_from_achieved_fk_not_ideal(monkeypatch):
    """When IK returns an approximate q_next, step 2's seed-pose must equal
    FK(q_next_step1), not the ideal T_delta1 @ T_curr0. We force the
    approximation by stubbing IK to return a known q that does NOT
    realize the ideal pose, then capture the matrix passed to step-2 IK."""
    import numpy as np
    from mimicrec.inference.action_decoder import ActionDecoder
    from mimicrec.inference.contract import ContractSpec
    from mimicrec.kinematics.fk import FKService, KinematicsConfig
    from mimicrec.kinematics.ik import IKService
    from mimicrec.types import RobotState

    spec = ContractSpec.from_yaml_text(YAML_CONTRACT)
    fk_cfg = KinematicsConfig(
        urdf_path="configs/urdf/so101/so101.urdf",
        target_frame="gripper_frame_link",
        joint_names=["shoulder_pan","shoulder_lift","elbow_flex","wrist_flex","wrist_roll"],
    )
    fk = FKService(fk_cfg); ik = IKService(fk_cfg)
    decoder = ActionDecoder(spec=spec, fk=fk, ik=ik, narm=fk.n_kin_joints, action_stats=None)

    # Force IK to return a fixed, intentionally-non-target q on step 1.
    # Both ok=True paths exercise the success branch we are testing.
    forced_q1 = np.array([5.0, 5.0, 5.0, 5.0, 5.0], dtype=np.float64)  # degrees
    ik_targets: list[np.ndarray] = []
    def fake_solve(T, seed):
        ik_targets.append(T.copy())
        return forced_q1.copy(), True
    monkeypatch.setattr(decoder.ik, "solve", fake_solve)

    delta_row = [0.001, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5]
    state = RobotState(
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
    )
    decoder.decode({"actions": [delta_row, delta_row]}, state)

    # Two IK calls captured: step 1 and step 2.
    assert len(ik_targets) == 2
    # Step 2's target must equal T_delta2 @ FK(forced_q1), the achieved-pose
    # composition. If the bug is present, step 2's target would equal
    # T_delta2 @ (T_delta1 @ FK(seed_q)), the idealized chain.
    achieved_T1 = fk.matrix(forced_q1)
    from mimicrec.inference.action_decoder import _to_T
    expected_step2_T = _to_T(np.array(delta_row[:3]), np.array(delta_row[3:6])) @ achieved_T1
    np.testing.assert_allclose(ik_targets[1], expected_step2_T, atol=1e-6)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_inference_action_decoder.py::test_t_curr_chains_from_achieved_fk_not_ideal -v`
Expected: FAIL — current code's `T_curr = T_next` makes step-2 target =
`T_delta2 @ T_delta1 @ FK(seed_q)`, not `T_delta2 @ FK(forced_q1)`.

- [ ] **Step 3: Implement the fix**

Edit `backend/mimicrec/inference/action_decoder.py:97-102`. Replace:

```python
            if not ok:
                q_next = seed_q
                T_curr = self.fk.matrix(seed_q)
            else:
                T_curr = T_next
```

with:

```python
            if not ok:
                q_next = seed_q
                T_curr = self.fk.matrix(seed_q)
            else:
                # Chain step N+1 from the pose the robot will actually reach,
                # not the idealized T_next. IK may converge approximately;
                # using T_next compounds residuals across the 8-step chunk.
                T_curr = self.fk.matrix(q_next)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_inference_action_decoder.py -v`
Expected: green (including all prior tests).

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/inference/action_decoder.py tests/unit/test_inference_action_decoder.py
git commit -m "fix(inference): chain chunk steps from achieved FK pose, not idealized T_next"
```

---

## Task 4: ActionDecoder — enforce `on_size_mismatch: reject`

**Files:**
- Modify: `backend/mimicrec/inference/action_decoder.py` inside `decode`
- Test: `tests/unit/test_inference_action_decoder.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_inference_action_decoder.py`:

```python
def test_decode_rejects_chunk_size_mismatch_in_reject_mode():
    import numpy as np
    import yaml as _yaml
    from mimicrec.inference.action_decoder import ActionDecoder
    from mimicrec.inference.contract import ContractSpec
    from mimicrec.kinematics.fk import FKService, KinematicsConfig
    from mimicrec.kinematics.ik import IKService
    from mimicrec.types import RobotState

    d = _yaml.safe_load(YAML_CONTRACT)
    d["response"]["chunk"] = {"expected_size": 2, "on_size_mismatch": "reject"}
    spec = ContractSpec.from_yaml_text(_yaml.safe_dump(d))
    fk_cfg = KinematicsConfig(
        urdf_path="configs/urdf/so101/so101.urdf",
        target_frame="gripper_frame_link",
        joint_names=["shoulder_pan","shoulder_lift","elbow_flex","wrist_flex","wrist_roll"],
    )
    fk = FKService(fk_cfg); ik = IKService(fk_cfg)
    decoder = ActionDecoder(spec=spec, fk=fk, ik=ik, narm=fk.n_kin_joints, action_stats=None)

    state = RobotState(
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
    )
    only_one = {"actions": [[0.0]*7]}  # 1 row, expected 2

    with pytest.raises(ValueError, match="chunk size 1 != expected 2"):
        decoder.decode(only_one, state)


def test_decode_accepts_any_chunk_in_use_actual_mode():
    """Default `use_actual` keeps processing whatever the server returned."""
    import numpy as np
    from mimicrec.inference.action_decoder import ActionDecoder
    from mimicrec.inference.contract import ContractSpec
    from mimicrec.kinematics.fk import FKService, KinematicsConfig
    from mimicrec.kinematics.ik import IKService
    from mimicrec.types import RobotState

    spec = ContractSpec.from_yaml_text(YAML_CONTRACT)  # default use_actual
    fk_cfg = KinematicsConfig(
        urdf_path="configs/urdf/so101/so101.urdf",
        target_frame="gripper_frame_link",
        joint_names=["shoulder_pan","shoulder_lift","elbow_flex","wrist_flex","wrist_roll"],
    )
    fk = FKService(fk_cfg); ik = IKService(fk_cfg)
    decoder = ActionDecoder(spec=spec, fk=fk, ik=ik, narm=fk.n_kin_joints, action_stats=None)

    state = RobotState(
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
    )
    out = decoder.decode({"actions": [[0.0]*7, [0.0]*7, [0.0]*7]}, state)
    assert len(out) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_inference_action_decoder.py -v -k "size_mismatch or use_actual"`
Expected: `test_decode_rejects_chunk_size_mismatch_in_reject_mode` FAILS
(no raise); `test_decode_accepts_any_chunk_in_use_actual_mode` likely passes.

- [ ] **Step 3: Implement the reject enforcement**

Edit `backend/mimicrec/inference/action_decoder.py`. Add a check inside
`decode()` immediately after `actions = self._extract_actions(response_body)`:

```python
def decode(self, response_body: dict, current_state: RobotState) -> list[StepAction]:
    actions = self._extract_actions(response_body)
    chunk_spec = self.spec.response.chunk
    if chunk_spec.on_size_mismatch == "reject" and len(actions) != chunk_spec.expected_size:
        raise ValueError(
            f"chunk size {len(actions)} != expected {chunk_spec.expected_size}; "
            f"contract on_size_mismatch=reject"
        )
    expected_action_dim = _expected_dim(self.spec.response.action.components)
    seed_q = current_state.joint_pos[:self.narm].copy()
    # ... rest unchanged ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_inference_action_decoder.py -v`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/inference/action_decoder.py tests/unit/test_inference_action_decoder.py
git commit -m "feat(inference): enforce on_size_mismatch=reject in ActionDecoder"
```

---

## Task 5: InferenceClient — refactor for ee_pos/ee_rotvec + gripper + required images

**Files:**
- Modify: `backend/mimicrec/inference/client.py` (full rewrite of the dataclass + helpers)
- Modify: `tests/unit/test_inference_client.py` (update legacy `test_client_round_trip`)

- [ ] **Step 1: Update the legacy round-trip test FIRST**

The existing `test_client_round_trip` constructs `InferenceClient(spec=spec,
url=url)` for a contract using `[joint_pos, gripper_pos]`. After this task,
the encoder always normalizes `gripper_pos` via convention+layout, so the
legacy test must inject those. Edit the construction in
`tests/unit/test_inference_client.py:54` (approx):

```python
from mimicrec.adapters.so101 import SO101Adapter
spec = ContractSpec.from_yaml_text(YAML.replace("REPLACED_AT_TEST", url))
client = InferenceClient(
    spec=spec,
    gripper_convention=SO101Adapter.default_gripper_convention(),
    proprio_layout=SO101Adapter.proprio_layout(),
)
```

(If the existing test exposes the URL differently, follow its existing
mechanism — the only required change is the two new kwargs.)

- [ ] **Step 2: Write new failing tests for the EE encode path**

Append to `tests/unit/test_inference_client.py`:

```python
import numpy as np
from pathlib import Path
from scipy.spatial.transform import Rotation as R

from mimicrec.adapters.so101 import SO101Adapter
from mimicrec.adapters.types import GripperConvention, ProprioLayout
from mimicrec.inference.client import InferenceClient
from mimicrec.inference.contract import ContractSpec
from mimicrec.kinematics.fk import FKService, KinematicsConfig
from mimicrec.types import Frame, RobotState, Stamped


_REPO_ROOT = Path(__file__).resolve().parents[2]
_FK_CFG = KinematicsConfig(
    urdf_path=str(_REPO_ROOT / "configs" / "urdf" / "so101" / "so101.urdf"),
    target_frame="gripper_frame_link",
    joint_names=["shoulder_pan","shoulder_lift","elbow_flex","wrist_flex","wrist_roll"],
)

_EE_YAML = """
name: t
endpoint: { url: "http://x", method: POST, retry: { max_attempts: 0 } }
request:
  images: { front: { field: image_primary, encoding: jpeg_base64, resize: [16,16], jpeg_quality: 90 } }
  state:
    field: proprio
    components: [ee_pos, ee_rotvec, gripper_pos]
    normalization: { method: none }
  instruction: { field: instruction }
response:
  actions_path: actions
  chunk: { expected_size: 1, on_size_mismatch: use_actual }
  action:
    type: ee_delta
    frame: world
    pose: { units: meter_axisangle_rad }
    gripper: { kind: absolute, units: normalized_0_1 }
    components: [ee_delta, gripper]
    normalization: { method: none }
loop: { prefetch_threshold: 0.5, max_inflight: 1 }
"""


def _make_state(joint_pos, ee_pos=None, ee_rotvec=None, gripper_pos=None):
    n = joint_pos.shape[0]
    return RobotState(
        joint_pos=joint_pos.astype(np.float32),
        joint_vel=np.zeros(n, dtype=np.float32),
        joint_effort=np.zeros(n, dtype=np.float32),
        ee_pos=ee_pos, ee_rotvec=ee_rotvec, gripper_pos=gripper_pos,
    )


def _make_client_so101(**overrides):
    spec = overrides.pop("spec", ContractSpec.from_yaml_text(_EE_YAML))
    fk = overrides.pop("fk", FKService(_FK_CFG))
    gc = overrides.pop("gripper_convention", SO101Adapter.default_gripper_convention())
    pl = overrides.pop("proprio_layout", SO101Adapter.proprio_layout())
    return InferenceClient(spec=spec, fk=fk, gripper_convention=gc, proprio_layout=pl, **overrides)


def test_encode_state_returns_seven_floats_in_contract_order():
    client = _make_client_so101()
    state = _make_state(joint_pos=np.zeros(6))
    out = client._encode_state(state)
    assert len(out) == 7
    # First 3 = ee_pos, next 3 = ee_rotvec, last 1 = gripper.
    # Concrete values: SO101 at q=0 deg → FK gives a specific pose; assert
    # they match FK(zeros) to prove we're not returning hardcoded zeros.
    expected_T = FKService(_FK_CFG).matrix(np.zeros(5))
    np.testing.assert_allclose(out[:3], expected_T[:3, 3].tolist(), atol=1e-6)
    expected_rotvec = R.from_matrix(expected_T[:3, :3]).as_rotvec().tolist()
    np.testing.assert_allclose(out[3:6], expected_rotvec, atol=1e-6)
    assert out[6] == pytest.approx(0.0, abs=1e-6)  # gripper raw=0 → normalized 0.0


def test_encode_state_skips_fk_when_ee_pre_populated(monkeypatch):
    client = _make_client_so101()
    calls: list = []
    monkeypatch.setattr(client.fk, "matrix", lambda q: (calls.append(q), np.eye(4))[1])

    ee_pos = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    ee_rotvec = np.array([0.0, 0.0, 0.5], dtype=np.float32)
    state = _make_state(joint_pos=np.zeros(6), ee_pos=ee_pos, ee_rotvec=ee_rotvec)
    out = client._encode_state(state)

    assert len(calls) == 0
    np.testing.assert_allclose(out[:3], ee_pos.tolist(), atol=1e-6)
    # ee_rotvec out should equal the input rotvec when FK is skipped.
    np.testing.assert_allclose(out[3:6], ee_rotvec.tolist(), atol=1e-6)


def test_encode_state_calls_fk_exactly_once_for_both_components(monkeypatch):
    client = _make_client_so101()
    calls: list = []
    real_matrix = client.fk.matrix
    monkeypatch.setattr(client.fk, "matrix", lambda q: (calls.append(q.copy()), real_matrix(q))[1])
    state = _make_state(joint_pos=np.array([0.1]*6))
    client._encode_state(state)
    assert len(calls) == 1


def test_encode_state_raises_when_ee_required_but_fk_missing():
    spec = ContractSpec.from_yaml_text(_EE_YAML)
    client = InferenceClient(spec=spec, fk=None)
    state = _make_state(joint_pos=np.zeros(6))
    with pytest.raises(ValueError, match="ee_pos/ee_rotvec"):
        client._encode_state(state)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_inference_client.py -v`
Expected: FAIL — `InferenceClient` does not yet accept `fk`/
`gripper_convention`/`proprio_layout` kwargs, no `_encode_state` method.

- [ ] **Step 4: Rewrite `backend/mimicrec/inference/client.py`**

Replace the file contents with:

```python
from __future__ import annotations
import base64
import io
from dataclasses import dataclass
import numpy as np
from scipy.spatial.transform import Rotation as R
import httpx
from PIL import Image

from mimicrec.adapters.types import GripperConvention, ProprioLayout
from mimicrec.inference.contract import ContractSpec
from mimicrec.kinematics.fk import FKService
from mimicrec.types import Frame, RobotState, Stamped


@dataclass
class InferenceClient:
    spec: ContractSpec
    fk: FKService | None = None
    gripper_convention: GripperConvention | None = None
    proprio_layout: ProprioLayout | None = None
    _client: httpx.AsyncClient | None = None

    async def predict(
        self,
        frames: dict[str, Stamped[Frame]],
        state: Stamped[RobotState],
        instr: Stamped[str],
        extras: dict | None = None,
    ) -> dict:
        body = self._build_request_body(frames, state.value, instr.value, extras or {})
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.spec.endpoint.timeout_s)
        resp = await self._client.post(
            self.spec.endpoint.url,
            json=body,
            headers=self.spec.endpoint.headers,
        )
        resp.raise_for_status()
        return resp.json()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _build_request_body(self, frames, state: RobotState, instruction: str, extras: dict) -> dict:
        body: dict = {}
        for cam_name, image_spec in self.spec.request.images.items():
            stamped = frames.get(cam_name)
            if stamped is None:
                raise ValueError(
                    f"contract requires image role {cam_name!r} but frames dict "
                    f"has no entry for it"
                )
            body[image_spec.field] = self._encode_image(
                stamped.value.image, image_spec.resize, image_spec.jpeg_quality,
            )
        body[self.spec.request.state.field] = self._encode_state(state)
        body[self.spec.request.instruction.field] = instruction
        body.update(self.spec.request.extra_fields)
        body.update(extras)
        return body

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
        """Always normalize raw → [0,1] via convention. The unit of
        `state.gripper_pos` varies per adapter — use proprio_layout to locate
        the raw value, then map via convention."""
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
            raise ValueError(
                f"unsupported gripper_via_column {pl.gripper_via_column!r}; "
                f"expected 'observation.state.joint_pos' or "
                f"'observation.state.gripper_pos'"
            )

        span = gc.open_at - gc.closed_at
        return float(np.clip((raw - gc.closed_at) / span, 0.0, 1.0))

    @staticmethod
    def _encode_image(img: np.ndarray, resize: tuple[int, int], jpeg_quality: int) -> str:
        rgb = img[..., ::-1].copy()
        pil = Image.fromarray(rgb)
        if pil.size != tuple(resize):
            pil = pil.resize(tuple(resize))
        buf = io.BytesIO()
        pil.save(buf, format="JPEG", quality=jpeg_quality)
        return base64.b64encode(buf.getvalue()).decode("ascii")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_inference_client.py -v`
Expected: green — the legacy `test_client_round_trip` (now injecting
convention+layout) plus the four new EE-encode tests.

- [ ] **Step 6: Commit**

```bash
git add backend/mimicrec/inference/client.py tests/unit/test_inference_client.py
git commit -m "feat(inference): encode ee_pos/ee_rotvec via FK + normalize gripper"
```

---

## Task 6: InferenceClient — gripper normalization coverage (both source columns)

**Files:**
- Test: `tests/unit/test_inference_client.py`

The implementation is in Task 5. This task adds dedicated coverage for
both `gripper_via_column` paths and the error cases.

- [ ] **Step 1: Write the tests**

Append to `tests/unit/test_inference_client.py`:

```python
def test_gripper_normalized_from_joint_pos_column():
    """SO101: gripper raw 0..100 packed at joint_pos[5]. raw=50 → 0.5."""
    client = _make_client_so101()
    joint_pos = np.zeros(6); joint_pos[5] = 50.0
    state = _make_state(joint_pos=joint_pos)
    out = client._encode_state(state)
    assert out[6] == pytest.approx(0.5, abs=1e-6)


@pytest.mark.parametrize("raw,expected", [(-10.0, 0.0), (0.0, 0.0), (50.0, 0.5), (100.0, 1.0), (200.0, 1.0)])
def test_gripper_normalization_clips_to_unit_interval(raw, expected):
    client = _make_client_so101()
    joint_pos = np.zeros(6); joint_pos[5] = raw
    state = _make_state(joint_pos=joint_pos)
    assert client._encode_state(state)[6] == pytest.approx(expected, abs=1e-6)


def test_gripper_from_state_gripper_pos_column():
    """reBot-style: raw gripper lives in state.gripper_pos. With convention
    closed_at=0, open_at=1, raw value passes through normalization."""
    pl = ProprioLayout(
        columns=("observation.state.joint_pos", "observation.state.gripper_pos"),
        output_names=("j0","j1","j2","j3","j4","gripper"),
        gripper_via_column="observation.state.gripper_pos",
        gripper_index_in_column=0,
    )
    gc = GripperConvention(closed_at=0.0, open_at=1.0)
    client = _make_client_so101(gripper_convention=gc, proprio_layout=pl)

    state = _make_state(joint_pos=np.zeros(6), gripper_pos=0.7)
    assert client._encode_state(state)[6] == pytest.approx(0.7, abs=1e-6)


def test_gripper_from_state_gripper_pos_column_raises_when_none():
    pl = ProprioLayout(
        columns=("observation.state.joint_pos", "observation.state.gripper_pos"),
        output_names=("j0","j1","j2","j3","j4","gripper"),
        gripper_via_column="observation.state.gripper_pos",
        gripper_index_in_column=0,
    )
    gc = GripperConvention(closed_at=0.0, open_at=1.0)
    client = _make_client_so101(gripper_convention=gc, proprio_layout=pl)
    state = _make_state(joint_pos=np.zeros(6), gripper_pos=None)
    with pytest.raises(ValueError, match="state.gripper_pos is None"):
        client._encode_state(state)


def test_gripper_index_out_of_range_raises():
    pl = ProprioLayout(
        columns=("observation.state.joint_pos",),
        output_names=("j0","j1","j2","j3","j4","gripper"),
        gripper_via_column="observation.state.joint_pos",
        gripper_index_in_column=99,
    )
    gc = GripperConvention(closed_at=0.0, open_at=100.0)
    client = _make_client_so101(gripper_convention=gc, proprio_layout=pl)
    state = _make_state(joint_pos=np.zeros(6))
    with pytest.raises(ValueError, match="out of range"):
        client._encode_state(state)


def test_gripper_without_convention_or_layout_raises():
    spec = ContractSpec.from_yaml_text(_EE_YAML)
    fk = FKService(_FK_CFG)
    client = InferenceClient(spec=spec, fk=fk)
    state = _make_state(joint_pos=np.zeros(6))
    with pytest.raises(ValueError, match="gripper_convention / proprio_layout"):
        client._encode_state(state)
```

- [ ] **Step 2: Run tests to verify they pass (no impl change needed)**

Run: `uv run pytest tests/unit/test_inference_client.py -v -k "gripper"`
Expected: green.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_inference_client.py
git commit -m "test(inference): cover gripper normalization (both source columns + error paths)"
```

---

## Task 7: InferenceClient — required image enforcement coverage

**Files:**
- Test: `tests/unit/test_inference_client.py`

Implementation landed in Task 5 (`if stamped is None: raise`); this task
adds explicit unit coverage.

- [ ] **Step 1: Write the test**

Append to `tests/unit/test_inference_client.py`:

```python
def test_build_request_body_raises_when_required_image_missing():
    """The so101_v46 contract requires both front and wrist; missing one
    must raise, not silently drop the field."""
    yaml_two_cams = _EE_YAML.replace(
        "images: { front: { field: image_primary, encoding: jpeg_base64, resize: [16,16], jpeg_quality: 90 } }",
        "images:\n    front: { field: image_primary, encoding: jpeg_base64, resize: [16,16], jpeg_quality: 90 }\n"
        "    wrist: { field: image_wrist, encoding: jpeg_base64, resize: [16,16], jpeg_quality: 90 }",
    )
    spec = ContractSpec.from_yaml_text(yaml_two_cams)
    client = _make_client_so101(spec=spec)

    img = np.zeros((16, 16, 3), dtype=np.uint8)
    frames = {"front": Stamped(value=Frame(image=img, t_mono_ns=0), t_mono_ns=0)}
    state = _make_state(joint_pos=np.zeros(6))

    with pytest.raises(ValueError, match="image role 'wrist'"):
        client._build_request_body(frames, state, "pick", {})
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_inference_client.py::test_build_request_body_raises_when_required_image_missing -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_inference_client.py
git commit -m "test(inference): cover required-image enforcement in InferenceClient"
```

---

## Task 8: New contract YAML — `configs/inference/so101_v46.yaml`

Ship the contract YAML before the lifecycle tasks so they can load it
directly via `ContractSpec.from_yaml_text(path.read_text())`.

**Files:**
- Create: `configs/inference/so101_v46.yaml`
- Create: `tests/unit/test_inference_so101_v46_contract.py`

- [ ] **Step 1: Write the failing snapshot test**

Create `tests/unit/test_inference_so101_v46_contract.py`:

```python
"""Snapshot tests for configs/inference/so101_v46.yaml.

The pair on the X-VLA-Adapter side is
~/X-VLA-Adapter/configs/deploy/so101_v46.yaml. Cross-repo drift is the
operator's responsibility; this test pins the MimicRec-side fields so an
unintentional edit breaks a clear test rather than producing silent
runtime errors against the server."""
from pathlib import Path

from mimicrec.inference.contract import ContractSpec


REPO_ROOT = Path(__file__).resolve().parents[2]
SO101_V46 = REPO_ROOT / "configs" / "inference" / "so101_v46.yaml"


def test_so101_v46_loads_and_pins_critical_fields():
    spec = ContractSpec.from_yaml_text(SO101_V46.read_text())
    assert spec.name == "so101_v46"
    assert spec.endpoint.url == "http://localhost:8001/predict"
    assert spec.endpoint.method == "POST"
    assert spec.endpoint.retry.max_attempts == 0

    assert spec.request.state.components == ["ee_pos", "ee_rotvec", "gripper_pos"]
    assert spec.request.state.normalization.method == "none"
    assert set(spec.request.images.keys()) == {"front", "wrist"}
    assert spec.request.images["front"].field == "image_primary"
    assert spec.request.images["wrist"].field == "image_wrist"

    assert spec.response.action.frame == "world"
    assert spec.response.action.type == "ee_delta"
    assert spec.response.action.normalization.method == "none"
    assert spec.response.action.components == ["ee_delta", "gripper"]
    assert spec.response.chunk.expected_size == 8
    assert spec.response.chunk.on_size_mismatch == "reject"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_inference_so101_v46_contract.py -v`
Expected: FAIL — `FileNotFoundError` on the YAML path.

- [ ] **Step 3: Create the contract YAML**

Create `configs/inference/so101_v46.yaml`:

```yaml
# configs/inference/so101_v46.yaml
#
# Pairs with X-VLA-Adapter server invoked as:
#   uv run python scripts/serve.py \
#     --predictor xvla_adapter \
#     --checkpoint <ckpt_export_dir> \
#     --deploy-config configs/deploy/so101_v46.yaml \
#     --domain-id 0 --port 8001
#
# Smoke-only. Server has wire_only_smoke=true (frame=world +
# frame_conversion=none); commands are not validated for real-arm
# correctness. Run smoke against the sim bridge, NOT the physical SO101.
# See docs/superpowers/specs/2026-05-13-mimicrec-inference-so101-v46-design.md

name: so101_v46
description: "X-VLA-Adapter SO101 v46 FT ckpt (wire_only_smoke; not validated on real arm)."

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
    normalization: { method: none }
  instruction:
    field: instruction
  extra_fields:
    model_version: x_vla_so101_v46

response:
  actions_path: actions
  chunk:
    expected_size: 8
    on_size_mismatch: reject
  action:
    type: ee_delta
    frame: world
    pose: { units: meter_axisangle_rad }
    gripper: { kind: absolute, units: normalized_0_1 }
    components: [ee_delta, gripper]
    normalization: { method: none }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_inference_so101_v46_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add configs/inference/so101_v46.yaml tests/unit/test_inference_so101_v46_contract.py
git commit -m "feat(inference): ship configs/inference/so101_v46.yaml contract"
```

---

## Task 9: Lifecycle — inject fk/gripper_convention/proprio_layout + fix narm

**Files:**
- Modify: `backend/mimicrec/session/lifecycle.py:936-944`
- Test: `tests/integration/test_inference_lifecycle.py` (extend)

`SessionManager` does NOT store `_action_decoder` as an instance attribute
(it's a local in `_start_inference_session_locked`). To assert `narm`, we
monkeypatch `ActionDecoder.__init__` to capture its kwargs.

- [ ] **Step 1: Read the existing lifecycle test patterns**

Run: `sed -n '1,50p' tests/integration/test_inference_lifecycle.py` to
copy the `SessionManager` setup pattern. Reuse whatever fixture builds a
ready-to-start `SessionManager` with FK and cameras.

- [ ] **Step 2: Write the failing tests**

Append to `tests/integration/test_inference_lifecycle.py`:

```python
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_inference_client_receives_fk_convention_layout(monkeypatch, ready_session_manager):
    """sm._inference_client must be constructed with fk, gripper_convention,
    and proprio_layout when starting inference against the so101_v46 contract.

    `ready_session_manager` is the existing fixture used by other tests in
    this file — adapt the call signature to whatever it provides."""
    sm = ready_session_manager  # SO101 + 'front'/'wrist' cameras configured
    contract = ContractSpec.from_yaml_text(
        (REPO_ROOT / "configs/inference/so101_v46.yaml").read_text()
    )
    await sm.start_inference_session(
        contract=contract, instruction="pick", inference_config_name="so101_v46"
    )
    try:
        assert sm._inference_client is not None
        assert sm._inference_client.fk is sm._fk
        assert sm._inference_client.gripper_convention is not None
        assert sm._inference_client.proprio_layout is not None
    finally:
        await sm.stop_inference_session()


@pytest.mark.asyncio
async def test_action_decoder_narm_equals_n_kin_joints(monkeypatch, ready_session_manager):
    """The decoder must be constructed with narm = fk.n_kin_joints (=5 for
    SO101), NOT robot.dof (=6). We capture via monkeypatching ActionDecoder."""
    captured = {}
    from mimicrec.inference import action_decoder as ad_mod
    orig = ad_mod.ActionDecoder
    def capturing_init(self, *args, **kwargs):
        captured.update(kwargs)
        orig.__init__(self, *args, **kwargs)
    monkeypatch.setattr(ad_mod.ActionDecoder, "__init__", capturing_init)

    sm = ready_session_manager
    contract = ContractSpec.from_yaml_text(
        (REPO_ROOT / "configs/inference/so101_v46.yaml").read_text()
    )
    await sm.start_inference_session(
        contract=contract, instruction="pick", inference_config_name="so101_v46"
    )
    try:
        assert captured["narm"] == sm._fk.n_kin_joints
        assert captured["narm"] == 5  # SO101 specifically
    finally:
        await sm.stop_inference_session()
```

If `ready_session_manager` does not exist in the file, copy the smallest
existing fixture/helper that produces a started-but-not-inference-mode
`SessionManager` for SO101 (look at the first existing `@pytest.mark.asyncio`
test in the file). Build it as a local fixture in the new test if needed.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_inference_lifecycle.py -v -k "fk_convention_layout or narm_equals"`
Expected: FAIL — `InferenceClient` constructed without the three deps,
and `narm` set to `self._robot.dof` not `self._fk.n_kin_joints`.

- [ ] **Step 4: Implement the lifecycle change**

Edit `backend/mimicrec/session/lifecycle.py` around lines 939-944.
Replace:

```python
new_decoder = ActionDecoder(
    spec=contract, fk=self._fk, ik=new_ik,
    narm=self._robot.dof,
    action_stats=action_stats,
)
new_client = InferenceClient(spec=contract)
```

with:

```python
new_decoder = ActionDecoder(
    spec=contract, fk=self._fk, ik=new_ik,
    narm=self._fk.n_kin_joints,  # NOT self._robot.dof — FK excludes gripper
    action_stats=action_stats,
)
new_client = InferenceClient(
    spec=contract,
    fk=self._fk,
    gripper_convention=self._robot.default_gripper_convention(),
    proprio_layout=self._robot.proprio_layout(),
)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_inference_lifecycle.py -v`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add backend/mimicrec/session/lifecycle.py tests/integration/test_inference_lifecycle.py
git commit -m "fix(session): wire FK/convention/layout into InferenceClient; correct narm"
```

---

## Task 10: Lifecycle — startup validation for required wiring

**Files:**
- Modify: `backend/mimicrec/session/lifecycle.py` (inside `_start_inference_session_locked`, Phase 1, BEFORE the destructive Phase 2)
- Test: `tests/integration/test_inference_lifecycle.py`

Camera attribute fact: lifecycle reads camera dict via
`self._cameras._cameras` (see lifecycle.py:452, 518, 1023). Use the same.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_inference_lifecycle.py`:

```python
@pytest.mark.asyncio
async def test_start_raises_when_contract_needs_ee_but_fk_unconfigured(
    session_manager_without_fk,
):
    """contract.state.components contains ee_pos/ee_rotvec but self._fk is
    None → InvalidTransitionError at session start, NOT a delayed predict
    failure. `session_manager_without_fk` is a local helper / fixture that
    builds a `SessionManager` where FK construction yielded None."""
    from mimicrec.errors import InvalidTransitionError
    sm = session_manager_without_fk
    contract = ContractSpec.from_yaml_text(
        (REPO_ROOT / "configs/inference/so101_v46.yaml").read_text()
    )
    with pytest.raises(InvalidTransitionError, match="FKService is not configured"):
        await sm.start_inference_session(
            contract=contract, instruction="x", inference_config_name="so101_v46"
        )


@pytest.mark.asyncio
async def test_start_raises_when_required_image_role_unconfigured(
    session_manager_front_only,
):
    """The contract lists 'wrist' but only the 'front' camera is configured."""
    from mimicrec.errors import InvalidTransitionError
    sm = session_manager_front_only
    contract = ContractSpec.from_yaml_text(
        (REPO_ROOT / "configs/inference/so101_v46.yaml").read_text()
    )
    with pytest.raises(InvalidTransitionError, match="image roles"):
        await sm.start_inference_session(
            contract=contract, instruction="x", inference_config_name="so101_v46"
        )


@pytest.mark.asyncio
async def test_start_raises_on_unsupported_gripper_column(
    monkeypatch, ready_session_manager,
):
    """Adapter whose ProprioLayout.gripper_via_column is unsupported by the
    encoder must fail at session start, not at predict time."""
    from mimicrec.errors import InvalidTransitionError
    from mimicrec.adapters.types import ProprioLayout

    sm = ready_session_manager
    bad_layout = ProprioLayout(
        columns=("observation.state.joint_pos",),
        output_names=("j0","j1","j2","j3","j4","gripper"),
        gripper_via_column="observation.state.bogus",
        gripper_index_in_column=0,
    )
    # ProprioLayout validates `gripper_via_column in columns`; the bogus
    # value above WILL raise at construction. To exercise the lifecycle
    # path we monkeypatch the adapter's accessor to return an arbitrary
    # object exposing the same attrs but bypassing the columns check.
    class FakeLayout:
        columns = ("observation.state.joint_pos",)
        output_names = ("j0","j1","j2","j3","j4","gripper")
        gripper_via_column = "observation.state.bogus"
        gripper_index_in_column = 0
    monkeypatch.setattr(sm._robot, "proprio_layout", classmethod(lambda cls: FakeLayout()).__func__)

    contract = ContractSpec.from_yaml_text(
        (REPO_ROOT / "configs/inference/so101_v46.yaml").read_text()
    )
    with pytest.raises(InvalidTransitionError, match="gripper_via_column"):
        await sm.start_inference_session(
            contract=contract, instruction="x", inference_config_name="so101_v46"
        )
```

Define `session_manager_without_fk` / `session_manager_front_only` as
local fixtures or helpers in the file by copying the existing
`ready_session_manager` setup and stripping FK / wrist camera respectively.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_inference_lifecycle.py -v -k "startup or unsupported_gripper or required_image"`
Expected: FAIL — no validation in place.

- [ ] **Step 3: Implement the validation block**

Edit `backend/mimicrec/session/lifecycle.py`, inside
`_start_inference_session_locked`, in Phase 1 (BEFORE the destructive
Phase 2 marker comment). A good anchor: immediately AFTER
`action_stats = contract.resolve_action_stats()` and BEFORE the
`if self._fk is None: raise InvalidTransitionError(...)` line. Insert:

```python
# --- Phase 1 validation: contract ↔ adapter wiring sanity ---
state_components = set(contract.request.state.components)

if {"ee_pos", "ee_rotvec"} & state_components and self._fk is None:
    raise InvalidTransitionError(
        f"contract requires {state_components & {'ee_pos', 'ee_rotvec'}} "
        f"but FKService is not configured for this robot"
    )

if "gripper_pos" in state_components:
    gc = self._robot.default_gripper_convention()
    if gc is None:
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
            f"supported for inference encoding; supported: "
            f"{sorted(SUPPORTED_GRIPPER_COLS)}"
        )

required_image_keys = set(contract.request.images.keys())
configured_cameras = set(self._cameras._cameras.keys())
missing = required_image_keys - configured_cameras
if missing:
    raise InvalidTransitionError(
        f"contract requires image roles {sorted(missing)} but those camera "
        f"slots are not configured (got {sorted(configured_cameras)})"
    )
# --- end Phase 1 validation ---
```

The pre-existing FK check at line 936-937 can stay; it's a more specific
duplicate that now becomes unreachable when state_components requires EE
(our validation fires first with a clearer message). Leave it for the
joint_pos-only contract case where EE-aware validation does not fire but
the decoder still needs FK.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_inference_lifecycle.py -v`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/session/lifecycle.py tests/integration/test_inference_lifecycle.py
git commit -m "feat(session): fail fast on missing FK/gripper/image-role wiring"
```

---

## Task 11: Integration test — mocked server end-to-end

**Files:**
- Create: `tests/integration/test_inference_so101_v46_e2e.py`

Pure HTTP-shape + decode round trip; does NOT touch the producer/control
loop pipeline (those have their own integration tests).

- [ ] **Step 1: Write the integration tests**

Create `tests/integration/test_inference_so101_v46_e2e.py`:

```python
"""End-to-end shape verification: InferenceClient → mocked X-VLA-Adapter
server → ActionDecoder. Confirms a so101_v46-shaped request lands at the
server with the right field names + proprio length + image keys, and that
a well-formed response decodes into joint commands via FK+IK."""
import numpy as np
import pytest
from aiohttp import web
from pathlib import Path

from mimicrec.adapters.so101 import SO101Adapter
from mimicrec.inference.action_decoder import ActionDecoder
from mimicrec.inference.client import InferenceClient
from mimicrec.inference.contract import ContractSpec
from mimicrec.kinematics.fk import FKService, KinematicsConfig
from mimicrec.kinematics.ik import IKService
from mimicrec.types import Frame, RobotState, Stamped


REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT_PATH = REPO_ROOT / "configs" / "inference" / "so101_v46.yaml"
_URDF_PATH = REPO_ROOT / "configs" / "urdf" / "so101" / "so101.urdf"


def _img():
    return np.zeros((16, 16, 3), dtype=np.uint8)


def _state():
    jp = np.zeros(6, dtype=np.float32); jp[5] = 50.0  # gripper raw midpoint
    return RobotState(
        joint_pos=jp,
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
    )


def _build_client_decoder(url: str):
    spec = ContractSpec.from_yaml_text(_CONTRACT_PATH.read_text())
    spec.endpoint.url = url

    fk_cfg = KinematicsConfig(
        urdf_path=str(_URDF_PATH),
        target_frame="gripper_frame_link",
        joint_names=["shoulder_pan","shoulder_lift","elbow_flex","wrist_flex","wrist_roll"],
    )
    fk = FKService(fk_cfg); ik = IKService(fk_cfg)
    client = InferenceClient(
        spec=spec, fk=fk,
        gripper_convention=SO101Adapter.default_gripper_convention(),
        proprio_layout=SO101Adapter.proprio_layout(),
    )
    decoder = ActionDecoder(spec=spec, fk=fk, ik=ik, narm=fk.n_kin_joints, action_stats=None)
    return client, decoder


async def test_so101_v46_request_decode_round_trip(aiohttp_client):
    received: dict = {}

    async def handler(request):
        received.update(await request.json())
        return web.json_response({"actions": [[0.001, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5] for _ in range(8)]})

    app = web.Application()
    app.router.add_post("/predict", handler)
    test_client = await aiohttp_client(app)
    url = str(test_client.make_url("/predict"))

    client, decoder = _build_client_decoder(url)

    frames = {
        "front": Stamped(value=Frame(image=_img(), t_mono_ns=0), t_mono_ns=0),
        "wrist": Stamped(value=Frame(image=_img(), t_mono_ns=0), t_mono_ns=0),
    }
    body = await client.predict(
        frames,
        Stamped(value=_state(), t_mono_ns=0),
        Stamped(value="pick up the cube", t_mono_ns=0),
        extras={},
    )
    chunk = decoder.decode(body, _state())

    assert set(received.keys()) >= {"image_primary", "image_wrist", "proprio", "instruction", "model_version"}
    assert len(received["proprio"]) == 7
    assert received["instruction"] == "pick up the cube"
    assert received["model_version"] == "x_vla_so101_v46"
    assert len(chunk) == 8
    for step in chunk:
        assert step.q.shape[0] == 5
        assert 0.0 <= step.gripper <= 1.0
    await client.aclose()


async def test_so101_v46_rejects_wrong_chunk_size(aiohttp_client):
    async def handler(request):
        return web.json_response({"actions": [[0.0]*7 for _ in range(7)]})  # WRONG: 7 rows
    app = web.Application()
    app.router.add_post("/predict", handler)
    test_client = await aiohttp_client(app)
    url = str(test_client.make_url("/predict"))

    client, decoder = _build_client_decoder(url)

    frames = {
        "front": Stamped(value=Frame(image=_img(), t_mono_ns=0), t_mono_ns=0),
        "wrist": Stamped(value=Frame(image=_img(), t_mono_ns=0), t_mono_ns=0),
    }
    body = await client.predict(
        frames,
        Stamped(value=_state(), t_mono_ns=0),
        Stamped(value="x", t_mono_ns=0),
        extras={},
    )
    with pytest.raises(ValueError, match="chunk size 7 != expected 8"):
        decoder.decode(body, _state())
    await client.aclose()
```

The `aiohttp_client` fixture comes from `pytest-aiohttp`, already used in
`tests/unit/test_inference_client.py`. If pytest cannot find it, confirm
the plugin is installed: `uv pip list | grep aiohttp` should show
`pytest-aiohttp`.

- [ ] **Step 2: Run the integration tests**

Run: `uv run pytest tests/integration/test_inference_so101_v46_e2e.py -v`
Expected: both pass.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_inference_so101_v46_e2e.py
git commit -m "test(inference): e2e round-trip against mocked X-VLA-Adapter server"
```

---

## Task 12: Full test suite + manual smoke against sim_bridge

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `uv run pytest tests/unit tests/integration -x -q`
Expected: green. Pre-existing failures unrelated to modified files can be
noted and skipped if confirmed unrelated.

- [ ] **Step 2: Verify sim bridge tooling exists**

Run: `ls configs/robot/sim_so101.yaml scripts/sim_bridge_dummy.py`
Expected: both present.

- [ ] **Step 3: Manual smoke against sim_bridge (NOT physical SO101)**

Server is `wire_only_smoke: true`; do NOT point this at the real arm.

Terminal 1 (VLA server):
```bash
cd ~/X-VLA-Adapter
uv run python scripts/serve.py \
  --predictor xvla_adapter \
  --checkpoint <ckpt_export_dir> \
  --deploy-config configs/deploy/so101_v46.yaml \
  --domain-id 0 --port 8001
```

Terminal 2 (sim bridge):
```bash
cd ~/MimicRec
.venv/bin/python scripts/sim_bridge_dummy.py
```

Terminal 3 (MimicRec backend + frontend, pointed at sim adapter):
```bash
cd ~/MimicRec
ROBOT_CONFIG=configs/robot/sim_so101.yaml bash scripts/run.sh
# UI → select so101_v46 contract → start inference
```

Pass criteria:
- Server log shows `POST /predict 200` at the control-loop rate
- MimicRec UI shows inference active with no error_bus events
- Terminal 2 (sim bridge) sees incoming joint commands

If any step fails, capture the symptom and treat as a defect against this
branch.

- [ ] **Step 4: Final commit (only if cleanup was needed)**

```bash
# Only if smoke turned up small typos or log noise:
git add -p
git commit -m "fix(inference): smoke-test cleanup"
```

---

## Self-review map (delete before merge)

| Spec section | Tasks |
|---|---|
| §3.1 contract YAML | Task 8 |
| §3.2 _COMPONENT_DIM | Task 1 |
| §3.3 client refactor (FK + gripper + required image) | Tasks 5, 6, 7 |
| §3.4 lifecycle wiring + startup validation | Tasks 9, 10 |
| §3.5 ActionDecoder adjacent fixes | Tasks 2, 3, 4 |
| §6.1-6.2 unit/snapshot tests | Tasks 1-8 |
| §6.3 integration test | Task 11 |
| §6.4 manual smoke | Task 12 |
| §7 known limitations | (no implementation; documented in YAML comment + spec) |
