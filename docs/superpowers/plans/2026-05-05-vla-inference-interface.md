# VLA Inference Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add closed-loop VLA inference to MimicRec — a YAML-configurable HTTP client that drives a real robot from a Vision-Language-Action server, records rollouts as datasets, and exposes a new `InferencePage` UI. Supports SO-101 first; reBot is designed-in but verified later.

**Architecture:** New `inference/` Python module mirrors the existing teleop control-loop pattern but pulls actions from an async HTTP producer + chunk buffer. Action format is 6-dim ΔEE pose + 1-dim gripper; an `IKService` wraps lerobot's `InverseKinematicsEEToJoints`. A new `SessionMode.INFERENCE` slots into `lifecycle.py`. Recording reuses the existing parquet/mp4 pipeline. Three new WS event types stream to a new `inference_hub`.

**Tech Stack:** Python 3.10+ (FastAPI / pyarrow / numpy / httpx / pydantic), pytest + asyncio_mode=auto, React/TypeScript frontend (Vite, TanStack Query, Zustand).

**Spec:** `docs/superpowers/specs/2026-05-05-vla-inference-interface-design.md`

**Test runner:** From `backend/` cwd:

```
env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/<path> -v
```

`pytest.ini` has `asyncio_mode = auto`, so async tests don't need `@pytest.mark.asyncio`.

---

## File structure

### New files

```
backend/mimicrec/
├── inference/
│   ├── __init__.py
│   ├── types.py            StepAction, SafetyEvent, ContractSpec re-exports
│   ├── contract.py         pydantic ContractSpec + YAML loader + validation
│   ├── chunk_buffer.py     ChunkBuffer (FIFO, half-prefetch, flush, generation)
│   ├── safety.py           InferenceSafety (clamp, joint limit, slow-stop, gripper hold)
│   ├── action_decoder.py   ActionDecoder (ee_delta → q chain via IKService)
│   ├── client.py           InferenceClient (httpx-based HTTP wrapper)
│   ├── producer.py         run_inference_producer (async task)
│   └── control_loop.py     run_inference_control_loop
├── kinematics/
│   └── ik.py               IKService (wraps lerobot.so_follower IK)
├── api/
│   ├── routes/inference.py REST endpoints (start/stop/instruction/state/configs)
│   └── ws/inference_hub.py inference_hub WS channel
└── config/
    └── inference_loader.py configs/inference/*.yaml discovery + load

configs/inference/
├── gemma_libero_v1.yaml    template for the user's first VLA
└── README.md               contract reference

frontend/src/
├── pages/InferencePage.tsx
├── api/inference.ts        REST + WS hooks
└── stores/inference-store.ts

tests/
├── unit/
│   ├── test_inference_contract.py
│   ├── test_inference_chunk_buffer.py
│   ├── test_inference_safety.py
│   ├── test_inference_action_decoder.py
│   ├── test_inference_client.py
│   └── test_inference_ik_service.py
├── integration/
│   ├── test_inference_producer_loop.py
│   ├── test_inference_lifecycle.py
│   └── test_inference_recording.py
├── e2e/
│   └── test_inference_e2e.py
└── fixtures/
    └── fake_vla_server.py
```

### Modified files

```
backend/mimicrec/types.py                    + SessionMode.INFERENCE
backend/mimicrec/session/lifecycle.py        + start/stop_inference + helpers + watchdog + instruction slot
backend/mimicrec/api/app.py                  + register /session/inference routes + inference_hub WS
backend/mimicrec/recording/metadata.py       + 3 columns on episodes.jsonl (source, inference_config, stop_reason)
configs/robot/so101.yaml                     + inference_safety block
frontend/src/App.tsx                         + /inference route
```

---

## Phase 1 — Types + ContractSpec foundation

### Task 1: Add `SessionMode.INFERENCE`

**Files:**
- Modify: `backend/mimicrec/types.py:17-19`
- Test: `tests/unit/test_inference_session_mode.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_inference_session_mode.py
from mimicrec.types import SessionMode


def test_session_mode_inference_exists():
    assert SessionMode.INFERENCE.value == "inference"


def test_session_mode_full_set():
    assert {m.value for m in SessionMode} >= {"teleop", "hand_teach", "inference"}
```

- [ ] **Step 2: Run to fail**

```
cd backend && env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_inference_session_mode.py -v
```

Expected: `AttributeError: INFERENCE`.

- [ ] **Step 3: Implement** — edit `backend/mimicrec/types.py`, add to `SessionMode`:

```python
class SessionMode(str, Enum):
    TELEOP = "teleop"
    HAND_TEACH = "hand_teach"
    INFERENCE = "inference"
```

(Preserve existing values; only add `INFERENCE`.)

- [ ] **Step 4: Verify pass**

```
cd backend && env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_inference_session_mode.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/types.py tests/unit/test_inference_session_mode.py
git commit -m "feat(types): add SessionMode.INFERENCE"
```

### Task 2: `inference/types.py` — StepAction + SafetyEvent

**Files:**
- Create: `backend/mimicrec/inference/__init__.py` (empty)
- Create: `backend/mimicrec/inference/types.py`
- Test: `tests/unit/test_inference_types.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_inference_types.py
import numpy as np

from mimicrec.inference.types import StepAction, SafetyEvent


def test_step_action_basic():
    s = StepAction(q=np.array([0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float64),
                   gripper=0.5)
    assert s.gripper == 0.5
    assert s.ik_failed is False


def test_step_action_ik_failed():
    s = StepAction(q=np.zeros(5), gripper=None, ik_failed=True)
    assert s.ik_failed is True


def test_safety_event_serialization():
    e = SafetyEvent(kind="delta_clamp", step_index=3, joint="elbow_flex")
    d = e.as_dict()
    assert d == {"type": "safety_event", "kind": "delta_clamp",
                 "step_index": 3, "joint": "elbow_flex"}
```

- [ ] **Step 2: Run to fail**

```
cd backend && env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_inference_types.py -v
```

Expected: `ModuleNotFoundError: mimicrec.inference`.

- [ ] **Step 3: Implement**

`backend/mimicrec/inference/__init__.py`: empty file.

`backend/mimicrec/inference/types.py`:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal
import numpy as np


SafetyKind = Literal["delta_clamp", "joint_limit", "slow_stop", "ik_fail"]


@dataclass
class StepAction:
    """One step of decoded action: target joints (degrees) + optional gripper.
    `ik_failed=True` when IK could not solve for this step (caller used the seed).
    """
    q: np.ndarray
    gripper: float | None
    ik_failed: bool = False


@dataclass
class SafetyEvent:
    kind: SafetyKind
    step_index: int | None = None
    joint: str | None = None

    def as_dict(self) -> dict:
        d: dict = {"type": "safety_event", "kind": self.kind}
        if self.step_index is not None:
            d["step_index"] = self.step_index
        if self.joint is not None:
            d["joint"] = self.joint
        return d
```

- [ ] **Step 4: Verify pass**

Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/inference/__init__.py backend/mimicrec/inference/types.py tests/unit/test_inference_types.py
git commit -m "feat(inference): add StepAction and SafetyEvent types"
```

### Task 3: `inference/contract.py` — pydantic ContractSpec data model

**Files:**
- Create: `backend/mimicrec/inference/contract.py`
- Test: `tests/unit/test_inference_contract.py`
- Reference: spec §6.1 (full skeleton), §6.2 (validation), §14 (full sample YAML)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_inference_contract.py
import pytest

from mimicrec.inference.contract import ContractSpec


YAML_OK = """
name: gemma_test
description: "test"
endpoint:
  url: "http://localhost:8001/predict"
  method: POST
  timeout_s: 5.0
  retry: { max_attempts: 0 }
request:
  images:
    front: { field: image_primary, encoding: jpeg_base64, resize: [224, 224], jpeg_quality: 90 }
  state:
    field: proprio
    components: [joint_pos, gripper_pos]
    normalization: { method: none }
  instruction:
    field: instruction
response:
  actions_path: actions
  chunk: { expected_size: 16, on_size_mismatch: use_actual }
  action:
    type: ee_delta
    frame: ee_local
    pose: { units: meter_axisangle_rad }
    gripper: { kind: absolute, units: normalized_0_1 }
    components: [ee_delta, gripper]
    normalization:
      method: mean_std
      stats_ref: { type: vla_export, dataset: SO101 }
loop:
  prefetch_threshold: 0.5
  max_inflight: 1
"""


def test_loads_minimal_yaml():
    spec = ContractSpec.from_yaml_text(YAML_OK)
    assert spec.name == "gemma_test"
    assert spec.endpoint.url.startswith("http://")
    assert spec.response.action.type == "ee_delta"
    assert spec.loop.max_inflight == 1


def test_endpoint_url_must_be_http():
    bad = YAML_OK.replace("http://localhost:8001/predict", "ftp://nope")
    with pytest.raises(ValueError, match="http"):
        ContractSpec.from_yaml_text(bad)
```

- [ ] **Step 2: Run to fail**

Expected: `ModuleNotFoundError: mimicrec.inference.contract`.

- [ ] **Step 3: Implement** — `backend/mimicrec/inference/contract.py`:

```python
from __future__ import annotations
from typing import Literal
import yaml
from pydantic import BaseModel, Field, field_validator


# ---- Endpoint ----
class RetrySpec(BaseModel):
    max_attempts: int = 0


class EndpointSpec(BaseModel):
    url: str
    method: Literal["POST"] = "POST"
    timeout_s: float = 5.0
    headers: dict[str, str] = Field(default_factory=dict)
    retry: RetrySpec = Field(default_factory=RetrySpec)

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str) -> str:
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("endpoint.url must be http(s)")
        return v


# ---- Request ----
class ImageSpec(BaseModel):
    field: str
    encoding: Literal["jpeg_base64"] = "jpeg_base64"
    resize: tuple[int, int] = (224, 224)
    jpeg_quality: int = 90


class NormalizationSpec(BaseModel):
    method: Literal["none", "minmax_neg1_pos1", "mean_std"] = "none"
    stats_ref: "StatsRef | None" = None


class StateSpec(BaseModel):
    field: str
    components: list[str]
    normalization: NormalizationSpec = Field(default_factory=NormalizationSpec)


class InstructionSpec(BaseModel):
    field: str


class RequestSpec(BaseModel):
    images: dict[str, ImageSpec]
    state: StateSpec
    instruction: InstructionSpec
    extra_fields: dict[str, str | int | float | bool] = Field(default_factory=dict)


# ---- Response ----
class StatsRef(BaseModel):
    type: Literal["vla_export", "absolute"]
    dataset: str | None = None
    path: str | None = None


class ChunkSpec(BaseModel):
    expected_size: int
    on_size_mismatch: Literal["use_actual", "reject"] = "use_actual"


class PoseSpec(BaseModel):
    units: Literal["meter_axisangle_rad", "mm_euler_deg"] = "meter_axisangle_rad"


class GripperSpec(BaseModel):
    kind: Literal["absolute", "delta", "binary"]
    units: Literal["normalized_0_1", "percent_0_100", "binary_threshold_0p5"] = "normalized_0_1"


class ActionSpec(BaseModel):
    type: Literal["ee_delta"]
    frame: Literal["ee_local", "world"] = "ee_local"
    pose: PoseSpec = Field(default_factory=PoseSpec)
    gripper: GripperSpec
    components: list[str]
    normalization: NormalizationSpec = Field(default_factory=NormalizationSpec)


class DoneSpec(BaseModel):
    path: str
    type: Literal["bool", "float"] = "float"
    threshold: float = 0.5
    scope: Literal["chunk", "step"] = "chunk"
    action_on_done: Literal["auto_stop", "notify_only"] = "notify_only"


class ResponseSpec(BaseModel):
    actions_path: str
    chunk: ChunkSpec
    action: ActionSpec
    done: DoneSpec | None = None


# ---- Loop ----
class LoopSpec(BaseModel):
    prefetch_threshold: float = 0.5
    max_inflight: int = 1


class ContractSpec(BaseModel):
    name: str
    description: str = ""
    endpoint: EndpointSpec
    request: RequestSpec
    response: ResponseSpec
    loop: LoopSpec = Field(default_factory=LoopSpec)

    @classmethod
    def from_yaml_text(cls, text: str) -> "ContractSpec":
        data = yaml.safe_load(text)
        return cls.model_validate(data)
```

(Note: `NormalizationSpec.stats_ref` is a forward-reference; pydantic v2 handles via `model_rebuild()`. Add `NormalizationSpec.model_rebuild()` at the bottom of the file if pydantic warns.)

- [ ] **Step 4: Verify pass**

Expected: 2 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/inference/contract.py tests/unit/test_inference_contract.py
git commit -m "feat(inference): add ContractSpec pydantic model + YAML loader"
```

### Task 4: ContractSpec env-var interpolation + validation

**Files:**
- Modify: `backend/mimicrec/inference/contract.py`
- Modify: `tests/unit/test_inference_contract.py`
- Reference: spec §6.2

- [ ] **Step 1: Write the failing tests** — append to `tests/unit/test_inference_contract.py`:

```python
import os


def test_env_var_interpolation(monkeypatch):
    monkeypatch.setenv("VLA_API_TOKEN", "secret123")
    yaml_with_env = YAML_OK.replace(
        '  retry: { max_attempts: 0 }',
        '  headers: { Authorization: "Bearer ${VLA_API_TOKEN}" }\n  retry: { max_attempts: 0 }',
    )
    spec = ContractSpec.from_yaml_text(yaml_with_env)
    assert spec.endpoint.headers["Authorization"] == "Bearer secret123"


def test_missing_env_var_fails(monkeypatch):
    monkeypatch.delenv("VLA_API_TOKEN", raising=False)
    yaml_with_env = YAML_OK.replace(
        '  retry: { max_attempts: 0 }',
        '  headers: { Authorization: "Bearer ${VLA_API_TOKEN}" }\n  retry: { max_attempts: 0 }',
    )
    with pytest.raises(ValueError, match="VLA_API_TOKEN"):
        ContractSpec.from_yaml_text(yaml_with_env)


def test_image_fields_must_be_unique():
    bad = YAML_OK.replace(
        "images:\n    front: { field: image_primary",
        "images:\n    front: { field: SAME, encoding: jpeg_base64, resize: [224, 224], jpeg_quality: 90 }\n    wrist: { field: SAME"
    ).replace(", encoding: jpeg_base64, resize: [224, 224], jpeg_quality: 90 }\n  state:",
              ", encoding: jpeg_base64, resize: [224, 224], jpeg_quality: 90 }\n  state:")
    with pytest.raises(ValueError, match="unique"):
        ContractSpec.from_yaml_text(bad)


def test_done_scope_step_rejected():
    yaml_done = YAML_OK + """
"""
    yaml_done = YAML_OK.replace(
        "loop:",
        "  done: { path: done, type: bool, scope: step, action_on_done: auto_stop }\nloop:",
    )
    with pytest.raises(ValueError, match="done.scope"):
        ContractSpec.from_yaml_text(yaml_done)
```

- [ ] **Step 2: Run to fail**

Expected: 4 failures.

- [ ] **Step 3: Implement** — modify `contract.py`:

Add at top:

```python
import os
import re

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _interpolate_env(value):
    if isinstance(value, str):
        def repl(m):
            name = m.group(1)
            v = os.environ.get(name)
            if v is None:
                raise ValueError(f"contract references missing env var: {name}")
            return v
        return _ENV_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(v) for v in value]
    return value
```

Modify `from_yaml_text`:

```python
@classmethod
def from_yaml_text(cls, text: str) -> "ContractSpec":
    data = yaml.safe_load(text)
    data = _interpolate_env(data)
    spec = cls.model_validate(data)
    spec._post_validate()
    return spec
```

Add `_post_validate` to `ContractSpec`:

```python
def _post_validate(self) -> None:
    # image field uniqueness
    fields = [img.field for img in self.request.images.values()]
    if len(fields) != len(set(fields)):
        raise ValueError("request.images.<cam>.field values must be unique")
    # done scope MVP=chunk only
    if self.response.done and self.response.done.scope != "chunk":
        raise ValueError(
            f"done.scope='{self.response.done.scope}' not implemented in MVP "
            "(only 'chunk' is supported)"
        )
```

- [ ] **Step 4: Verify pass**

Expected: 6 passed (2 + 4 new).

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/inference/contract.py tests/unit/test_inference_contract.py
git commit -m "feat(inference): contract env-var interpolation + post-validation"
```

### Task 5: ContractSpec stats_ref resolution + components→dim registry

**Files:**
- Modify: `backend/mimicrec/inference/contract.py`
- Modify: `tests/unit/test_inference_contract.py`
- Reference: spec §6.2 (registry + length assertion + stats_ref resolution)

- [ ] **Step 1: Write the failing tests** — append:

```python
import json


COMPONENTS_DIM = {
    "joint_pos": "Narm",      # robot-config-dependent
    "gripper_pos": 1,
    "ee_delta": 6,
    "gripper": 1,
}


def test_stats_path_resolution_vla_export(tmp_path, monkeypatch):
    # set up a fake VLA export tree
    monkeypatch.setenv("MIMICREC_VLA_DEST_ROOT", str(tmp_path))
    (tmp_path / "SO101" / "meta").mkdir(parents=True)
    stats_file = tmp_path / "SO101" / "meta" / "action_stats.json"
    stats_file.write_text(json.dumps({"mean": [0.0]*7, "std": [1.0]*7}))

    spec = ContractSpec.from_yaml_text(YAML_OK)
    resolved = spec.resolve_action_stats()
    assert resolved == {"mean": [0.0]*7, "std": [1.0]*7}


def test_stats_path_missing_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("MIMICREC_VLA_DEST_ROOT", str(tmp_path))
    spec = ContractSpec.from_yaml_text(YAML_OK)
    with pytest.raises(FileNotFoundError, match="action_stats.json"):
        spec.resolve_action_stats()


def test_stats_length_mismatch_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("MIMICREC_VLA_DEST_ROOT", str(tmp_path))
    (tmp_path / "SO101" / "meta").mkdir(parents=True)
    stats_file = tmp_path / "SO101" / "meta" / "action_stats.json"
    stats_file.write_text(json.dumps({"mean": [0.0]*5, "std": [1.0]*5}))  # wrong length

    spec = ContractSpec.from_yaml_text(YAML_OK)
    with pytest.raises(ValueError, match="length"):
        spec.resolve_action_stats()
```

- [ ] **Step 2: Run to fail**

Expected: 3 failures (no `resolve_action_stats`).

- [ ] **Step 3: Implement** — append in `contract.py`:

```python
import json
from pathlib import Path


# Registry of component dims. "Narm"-keyed components require an explicit Narm at resolve time.
_COMPONENT_DIM = {
    "joint_pos": "Narm",
    "gripper_pos": 1,
    "ee_delta": 6,
    "gripper": 1,
}


def _expected_dim(components: list[str], narm: int | None = None) -> int:
    total = 0
    for c in components:
        if c not in _COMPONENT_DIM:
            raise ValueError(f"unknown component '{c}'")
        d = _COMPONENT_DIM[c]
        if d == "Narm":
            if narm is None:
                raise ValueError(f"component '{c}' requires Narm context")
            total += narm
        else:
            total += d
    return total


def _resolve_stats_path(spec: "ContractSpec") -> Path:
    sr = spec.response.action.normalization.stats_ref
    if sr is None or spec.response.action.normalization.method == "none":
        raise ValueError("action normalization is not configured (method=none)")
    if sr.type == "vla_export":
        root = Path(os.environ.get("MIMICREC_VLA_DEST_ROOT",
                                   str(Path.home() / "vla-gemma-4" / "data" / "local"))).expanduser()
        return root / sr.dataset / "meta" / "action_stats.json"
    if sr.type == "absolute":
        return Path(sr.path)
    raise ValueError(f"unknown stats_ref.type: {sr.type}")
```

Add to `ContractSpec`:

```python
def resolve_action_stats(self) -> dict:
    """Load action_stats.json and assert length matches sum(action.components dims)."""
    path = _resolve_stats_path(self)
    if not path.exists():
        raise FileNotFoundError(f"action_stats.json not found: {path}")
    stats = json.loads(path.read_text())
    expected = _expected_dim(self.response.action.components)
    if len(stats["mean"]) != expected or len(stats["std"]) != expected:
        raise ValueError(
            f"action_stats length mismatch: got mean[{len(stats['mean'])}], "
            f"std[{len(stats['std'])}], expected {expected} from components "
            f"{self.response.action.components}"
        )
    return stats
```

- [ ] **Step 4: Verify pass**

Expected: 9 passed (6 + 3 new).

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/inference/contract.py tests/unit/test_inference_contract.py
git commit -m "feat(inference): contract stats_ref resolution + length validation"
```

---

## Phase 2 — Kinematics IK service

### Task 6: `kinematics/ik.py` — IKService wrapping lerobot

**Files:**
- Create: `backend/mimicrec/kinematics/ik.py`
- Test: `tests/unit/test_inference_ik_service.py`
- Reference: spec §7.5; lerobot at `lerobot/src/lerobot/model/kinematics.py:84` (`RobotKinematics.inverse_kinematics`). FKService already wraps the same class for FK — mirror its construction (`backend/mimicrec/kinematics/fk.py:30-43`). Note `KinematicsConfig.target_frame` (MimicRec) maps to `target_frame_name` (lerobot).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_inference_ik_service.py
import numpy as np
import pytest

from mimicrec.kinematics.fk import FKService, KinematicsConfig
from mimicrec.kinematics.ik import IKService


@pytest.fixture
def cfg() -> KinematicsConfig:
    return KinematicsConfig(
        urdf_path="configs/urdf/so101/so101.urdf",
        target_frame="gripper_frame_link",
        joint_names=[
            "shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll",
        ],
    )


@pytest.fixture
def ik(cfg) -> IKService:
    return IKService(cfg)


@pytest.fixture
def fk(cfg) -> FKService:
    return FKService(cfg)


def test_ik_round_trip(ik, fk):
    """FK(q) -> T, IK(T, seed=q) -> q' should be close to q."""
    q = np.array([10.0, -20.0, 30.0, -10.0, 5.0])
    T = fk._k.forward_kinematics(q)  # access underlying RobotKinematics for the 4x4
    q2, ok = ik.solve(T, seed=q)
    assert ok
    assert np.allclose(q, q2, atol=0.5)


def test_ik_unreachable_returns_not_ok(ik):
    """A pose far outside the workspace should fail the FK round-trip check."""
    T_far = np.eye(4)
    T_far[:3, 3] = [10.0, 0.0, 0.0]  # 10 m away — clearly unreachable
    q_seed = np.zeros(5)
    q, ok = ik.solve(T_far, seed=q_seed)
    assert not ok
```

- [ ] **Step 2: Run to fail**

Expected: `ModuleNotFoundError: mimicrec.kinematics.ik`.

- [ ] **Step 3: Implement** — `backend/mimicrec/kinematics/ik.py`:

```python
from __future__ import annotations
import numpy as np

from mimicrec.kinematics.fk import KinematicsConfig


class IKService:
    """Inverse kinematics for SO-101-class arms.

    Wraps `lerobot.model.kinematics.RobotKinematics.inverse_kinematics`
    (the same class FKService wraps for FK). Joint values are in **degrees**.
    Returns `(q_solved, success)`. Because placo always returns *a*
    solution, success is computed by a FK round-trip: position error < 2 cm
    AND orientation error < 0.1 rad (≈6°). Failures don't raise — they are
    surfaced as `success=False` so the action decoder can hold the seed.
    """

    POS_TOL_M = 0.02
    ANG_TOL_RAD = 0.1

    def __init__(self, cfg: KinematicsConfig):
        from lerobot.model.kinematics import RobotKinematics

        self._cfg = cfg
        self._k = RobotKinematics(
            urdf_path=cfg.urdf_path,
            target_frame_name=cfg.target_frame,
            joint_names=cfg.joint_names,
        )

    def solve(self, T_target: np.ndarray, seed: np.ndarray) -> tuple[np.ndarray, bool]:
        """Solve IK for a 4x4 target pose. `seed` is in degrees.

        Returns (q_solved_degrees, success).
        """
        try:
            q = self._k.inverse_kinematics(seed.astype(np.float64), T_target.astype(np.float64))
            q = np.asarray(q, dtype=np.float64)
        except Exception:
            return seed.copy(), False

        # Verify by FK round-trip
        T_actual = self._k.forward_kinematics(q)
        pos_err = float(np.linalg.norm(T_target[:3, 3] - T_actual[:3, 3]))
        R_err = T_target[:3, :3].T @ T_actual[:3, :3]
        cos_ang = (np.trace(R_err) - 1.0) / 2.0
        ang_err = float(np.arccos(np.clip(cos_ang, -1.0, 1.0)))
        ok = (pos_err < self.POS_TOL_M) and (ang_err < self.ANG_TOL_RAD)
        return q, ok
```

(`KinematicsConfig.target_frame` is the MimicRec field name, mapped to lerobot's `target_frame_name` parameter — same mapping FKService uses at `kinematics/fk.py:38`.)

- [ ] **Step 4: Verify pass**

Expected: 2 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/kinematics/ik.py tests/unit/test_inference_ik_service.py
git commit -m "feat(kinematics): IKService wraps RobotKinematics.inverse_kinematics"
```

---

## Phase 3 — Buffer + safety

### Task 7: `inference/chunk_buffer.py` — push/pop + half-prefetch

**Files:**
- Create: `backend/mimicrec/inference/chunk_buffer.py`
- Test: `tests/unit/test_inference_chunk_buffer.py`
- Reference: spec §7.1

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_inference_chunk_buffer.py
import asyncio

import numpy as np
import pytest

from mimicrec.inference.chunk_buffer import ChunkBuffer
from mimicrec.inference.types import StepAction


def _step(i: int) -> StepAction:
    return StepAction(q=np.full(5, float(i)), gripper=0.0)


def _make_buffer(prefetch_threshold: float = 0.5) -> ChunkBuffer:
    return ChunkBuffer.create(prefetch_threshold=prefetch_threshold)


def test_pop_empty_returns_none():
    b = _make_buffer()
    assert b.pop_next() is None


def test_push_then_pop():
    b = _make_buffer()
    b.try_push_chunk([_step(0), _step(1), _step(2)], generation=b.current_generation())
    assert b.pop_next().q[0] == 0.0
    assert b.pop_next().q[0] == 1.0


def test_half_prefetch_fires_event_once():
    b = _make_buffer(prefetch_threshold=0.5)
    b.try_push_chunk([_step(i) for i in range(4)], generation=b.current_generation())
    # consume first two = 50%
    b.pop_next(); b.pop_next()
    assert b._refill_event.is_set()
    b._refill_event.clear()
    # consuming third must NOT re-fire (already in_flight)
    b.pop_next()
    assert not b._refill_event.is_set()
```

- [ ] **Step 2: Run to fail**

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement** — `backend/mimicrec/inference/chunk_buffer.py`:

```python
from __future__ import annotations
import asyncio
from collections import deque
from dataclasses import dataclass, field

from mimicrec.inference.types import StepAction


@dataclass
class ChunkBuffer:
    """Action chunk buffer with half-prefetch trigger and instruction-flush.

    Concurrency contract: SINGLE producer (run_inference_producer), SINGLE
    consumer (run_inference_control_loop), BOTH on the same asyncio loop.
    """
    _steps: deque[StepAction]
    _origin_size: int = 0
    _refill_event: asyncio.Event = field(default_factory=asyncio.Event)
    _refill_in_flight: bool = False
    _generation: int = 0
    prefetch_threshold: float = 0.5

    @classmethod
    def create(cls, prefetch_threshold: float = 0.5) -> "ChunkBuffer":
        return cls(_steps=deque(), prefetch_threshold=prefetch_threshold)

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
        if generation != self._generation:
            return False
        self._steps.extend(chunk)
        self._origin_size = len(self._steps)
        self._refill_in_flight = False
        return True

    def current_generation(self) -> int:
        return self._generation

    def depth(self) -> int:
        return len(self._steps)

    def origin_size(self) -> int:
        return self._origin_size
```

- [ ] **Step 4: Verify pass**

Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/inference/chunk_buffer.py tests/unit/test_inference_chunk_buffer.py
git commit -m "feat(inference): ChunkBuffer push/pop + half-prefetch trigger"
```

### Task 8: ChunkBuffer.flush + wait_for_refill + request_refill_now

**Files:**
- Modify: `backend/mimicrec/inference/chunk_buffer.py`
- Modify: `tests/unit/test_inference_chunk_buffer.py`
- Reference: spec §7.1 (flush returns flushed count; producer-side `wait_for_refill`)

- [ ] **Step 1: Write the failing test** — append:

```python
def test_flush_returns_count_and_bumps_generation():
    b = _make_buffer()
    b.try_push_chunk([_step(0), _step(1), _step(2)], generation=b.current_generation())
    assert b.depth() == 3
    flushed = b.flush()
    assert flushed == 3
    assert b.depth() == 0
    assert b.current_generation() == 1


def test_try_push_with_stale_generation_returns_false():
    b = _make_buffer()
    g0 = b.current_generation()
    b.flush()  # bumps to 1
    pushed = b.try_push_chunk([_step(0)], generation=g0)
    assert not pushed
    assert b.depth() == 0


async def test_wait_for_refill_clears_event():
    b = _make_buffer()
    b.request_refill_now()
    await b.wait_for_refill()
    assert not b._refill_event.is_set()
```

- [ ] **Step 2: Run to fail** — 3 new failures.

- [ ] **Step 3: Implement** — append to `ChunkBuffer`:

```python
def flush(self) -> int:
    flushed = len(self._steps)
    self._steps.clear()
    self._origin_size = 0
    self._generation += 1
    self._refill_in_flight = False
    self._refill_event.set()
    return flushed

def request_refill_now(self) -> None:
    self._refill_in_flight = False
    self._refill_event.set()

async def wait_for_refill(self) -> None:
    await self._refill_event.wait()
    self._refill_event.clear()
```

- [ ] **Step 4: Verify pass** — 6 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/inference/chunk_buffer.py tests/unit/test_inference_chunk_buffer.py
git commit -m "feat(inference): ChunkBuffer flush + wait_for_refill + generation"
```

### Task 9: `inference/safety.py` — clamp + joint limit + gripper pass-through

**Files:**
- Create: `backend/mimicrec/inference/safety.py`
- Test: `tests/unit/test_inference_safety.py`
- Reference: spec §7.4

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_inference_safety.py
import numpy as np
import pytest

from mimicrec.inference.safety import InferenceSafety
from mimicrec.inference.types import StepAction


def _make_safety(max_delta: float = 2.0, slow_stop_ticks: int = 5) -> InferenceSafety:
    return InferenceSafety(
        max_delta=max_delta,
        joint_min=np.array([-90.0]*5),
        joint_max=np.array([+90.0]*5),
        slow_stop_ticks=slow_stop_ticks,
    )


def test_filter_passes_within_limits():
    s = _make_safety()
    cmd = s.filter(StepAction(q=np.full(5, 1.0), gripper=0.5),
                   q_curr=np.zeros(5), tick_t_ns=1)
    assert np.allclose(cmd.q, 1.0)
    assert cmd.gripper == 0.5


def test_filter_clamps_delta():
    s = _make_safety(max_delta=1.0)
    cmd = s.filter(StepAction(q=np.full(5, 5.0), gripper=None),
                   q_curr=np.zeros(5), tick_t_ns=1)
    assert np.allclose(cmd.q, 1.0)        # clamped to ±1.0


def test_filter_clips_at_joint_limit():
    s = _make_safety(max_delta=100.0)
    cmd = s.filter(StepAction(q=np.full(5, 200.0), gripper=None),
                   q_curr=np.full(5, 80.0), tick_t_ns=1)
    assert np.allclose(cmd.q, 90.0)
```

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: Implement** — `backend/mimicrec/inference/safety.py`:

```python
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

from mimicrec.inference.types import StepAction
from mimicrec.types import RobotCommand


@dataclass
class InferenceSafety:
    max_delta: float
    joint_min: np.ndarray
    joint_max: np.ndarray
    slow_stop_ticks: int = 5

    _last_safe_q: np.ndarray | None = None
    _last_gripper_cmd: float | None = None
    _slow_stop_remaining: int = 0
    _clamps_in_current_chunk: int = 0

    def filter(self, step: StepAction | None, q_curr: np.ndarray, tick_t_ns: int) -> RobotCommand:
        if step is None:
            return self._slow_stop(q_curr, tick_t_ns)
        delta = step.q - q_curr
        clamped = np.clip(delta, -self.max_delta, self.max_delta)
        if not np.array_equal(clamped, delta):
            self._clamps_in_current_chunk += 1
        q_safe = np.clip(q_curr + clamped, self.joint_min, self.joint_max)
        self._last_safe_q = q_safe
        gripper_cmd = step.gripper if step.gripper is not None else self._last_gripper_cmd
        if gripper_cmd is not None:
            self._last_gripper_cmd = gripper_cmd
        self._slow_stop_remaining = 0
        return RobotCommand(q=q_safe, gripper=gripper_cmd, t_mono_ns=tick_t_ns)

    def _slow_stop(self, q_curr: np.ndarray, tick_t_ns: int) -> RobotCommand:
        if self._last_safe_q is None:
            q = q_curr.copy()
        else:
            if self._slow_stop_remaining == 0:
                self._slow_stop_remaining = self.slow_stop_ticks
            n = self._slow_stop_remaining
            alpha = 1.0 - ((n - 1) / self.slow_stop_ticks)
            q = self._last_safe_q + (q_curr - self._last_safe_q) * alpha
            self._slow_stop_remaining = max(0, n - 1)
            if self._slow_stop_remaining == 0:
                self._last_safe_q = q
        return RobotCommand(q=q, gripper=self._last_gripper_cmd, t_mono_ns=tick_t_ns)

    def on_new_chunk(self) -> None:
        self._clamps_in_current_chunk = 0

    def clamps_in_current_chunk(self) -> int:
        return self._clamps_in_current_chunk
```

- [ ] **Step 4: Verify pass** — 3 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/inference/safety.py tests/unit/test_inference_safety.py
git commit -m "feat(inference): InferenceSafety clamp + joint limit"
```

### Task 10: Safety slow-stop alpha series + gripper hold + on_new_chunk

**Files:**
- Modify: `tests/unit/test_inference_safety.py`
- Reference: spec §7.4 (alpha series 0.2 → 1.0 for N=5; gripper hold)

- [ ] **Step 1: Write the failing tests** — append:

```python
def test_slow_stop_alpha_series():
    s = _make_safety(slow_stop_ticks=5)
    s.filter(StepAction(q=np.full(5, 5.0), gripper=0.5),
             q_curr=np.zeros(5), tick_t_ns=1)
    # _last_safe_q is now ~ [2,2,2,2,2] (clamped to max_delta=2)
    # Now buffer empty -> slow-stop tries to converge to q_curr=10
    expected_alphas = [0.2, 0.4, 0.6, 0.8, 1.0]
    last = s._last_safe_q.copy()
    for tick, expected_alpha in enumerate(expected_alphas, start=1):
        cmd = s.filter(None, q_curr=np.full(5, 10.0), tick_t_ns=tick)
        # alpha-interpolated between last and 10.0
        expected_q = last + (np.full(5, 10.0) - last) * expected_alpha
        if expected_alpha < 1.0:
            assert np.allclose(cmd.q, expected_q, atol=1e-6), \
                f"tick {tick}: alpha {expected_alpha}"


def test_filter_with_step_gripper_none_holds_last():
    s = _make_safety()
    s.filter(StepAction(q=np.zeros(5), gripper=0.7), q_curr=np.zeros(5), tick_t_ns=1)
    cmd = s.filter(StepAction(q=np.zeros(5), gripper=None), q_curr=np.zeros(5), tick_t_ns=2)
    assert cmd.gripper == 0.7


def test_on_new_chunk_resets_clamp_count():
    s = _make_safety(max_delta=0.1)
    s.filter(StepAction(q=np.full(5, 5.0), gripper=0.0), q_curr=np.zeros(5), tick_t_ns=1)
    assert s.clamps_in_current_chunk() == 1
    s.on_new_chunk()
    assert s.clamps_in_current_chunk() == 0
```

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: No code changes if Task 9 implementation is correct.** All three tests should pass given the implementation in Task 9.

- [ ] **Step 4: Verify pass** — 6 total.

- [ ] **Step 5: Commit (test-only)**

```
git add tests/unit/test_inference_safety.py
git commit -m "test(inference): safety alpha series, gripper hold, on_new_chunk"
```

---

## Phase 4 — Action decoder + HTTP client

### Task 11: `inference/action_decoder.py` — ee_delta basic chain

**Files:**
- Create: `backend/mimicrec/inference/action_decoder.py`
- Test: `tests/unit/test_inference_action_decoder.py`
- Reference: spec §7.3, §6 contract

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_inference_action_decoder.py
import numpy as np
import pytest

from mimicrec.inference.action_decoder import ActionDecoder
from mimicrec.inference.contract import ContractSpec
from mimicrec.types import RobotState


YAML_CONTRACT = """
name: test
endpoint:
  url: http://x:1/p
  method: POST
  retry: { max_attempts: 0 }
request:
  images: { front: { field: img, encoding: jpeg_base64, resize: [224,224], jpeg_quality: 90 } }
  state:  { field: proprio, components: [joint_pos, gripper_pos], normalization: { method: none } }
  instruction: { field: instr }
response:
  actions_path: actions
  chunk: { expected_size: 4, on_size_mismatch: use_actual }
  action:
    type: ee_delta
    frame: ee_local
    pose: { units: meter_axisangle_rad }
    gripper: { kind: absolute, units: normalized_0_1 }
    components: [ee_delta, gripper]
    normalization: { method: none }
loop:
  prefetch_threshold: 0.5
  max_inflight: 1
"""


def _state(joint_pos=None) -> RobotState:
    if joint_pos is None:
        joint_pos = np.array([0.0, 0.0, 0.0, 0.0, 0.0])
    return RobotState(
        joint_pos=np.asarray(joint_pos, dtype=np.float64),
        joint_vel=np.zeros_like(joint_pos),
        joint_effort=np.zeros_like(joint_pos),
        gripper_pos=0.0,
        t_mono_ns=0,
    )


class FakeIK:
    def __init__(self):
        self.calls = []
    def solve(self, T, seed):
        # Round-trip: assume FK followed by IK returns the seed plus a small bias.
        self.calls.append((T.copy(), seed.copy()))
        return seed + 0.01, True


class FakeFK:
    def matrix(self, q):
        # Identity matrix as a stand-in
        T = np.eye(4)
        T[:3, 3] = q[:3] * 0.001
        return T


def test_decode_zero_delta_chunk_round_trips():
    spec = ContractSpec.from_yaml_text(YAML_CONTRACT)
    dec = ActionDecoder(spec=spec, fk=FakeFK(), ik=FakeIK(), narm=5)
    raw = {"actions": [
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5],
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5],
    ]}
    chunk = dec.decode(raw, current_state=_state())
    assert len(chunk) == 2
    assert chunk[0].gripper == 0.5
    assert chunk[0].ik_failed is False
```

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: Implement** — `backend/mimicrec/inference/action_decoder.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
import numpy as np
from scipy.spatial.transform import Rotation as R

from mimicrec.inference.contract import ContractSpec
from mimicrec.inference.types import StepAction
from mimicrec.types import RobotState


class FKLike(Protocol):
    def matrix(self, q: np.ndarray) -> np.ndarray: ...


class IKLike(Protocol):
    def solve(self, T: np.ndarray, seed: np.ndarray) -> tuple[np.ndarray, bool]: ...


def _to_T(pos: np.ndarray, axisangle: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, 3] = pos
    if np.linalg.norm(axisangle) > 1e-9:
        T[:3, :3] = R.from_rotvec(axisangle).as_matrix()
    return T


@dataclass
class ActionDecoder:
    spec: ContractSpec
    fk: FKLike
    ik: IKLike
    narm: int

    def decode(self, response_body: dict, current_state: RobotState) -> list[StepAction]:
        actions = self._extract_actions(response_body)
        seed_q = current_state.joint_pos[:self.narm].copy()
        T_curr = self.fk.matrix(seed_q)
        chunk: list[StepAction] = []
        for raw in actions:
            arr = np.asarray(raw, dtype=np.float64)
            ee_delta_norm = arr[:6]
            gripper_raw = float(arr[6]) if arr.shape[0] >= 7 else None
            # MVP: normalization=none → de-normalize is identity
            pos = ee_delta_norm[:3]
            axisangle = ee_delta_norm[3:6]
            T_delta = _to_T(pos, axisangle)
            if self.spec.response.action.frame == "ee_local":
                T_next = T_curr @ T_delta
            else:
                T_next = T_delta @ T_curr
            q_next, ok = self.ik.solve(T_next, seed=seed_q)
            if not ok:
                q_next = seed_q
            gripper_cmd = self._decode_gripper(gripper_raw, current_state.gripper_pos)
            chunk.append(StepAction(q=q_next, gripper=gripper_cmd, ik_failed=not ok))
            T_curr = T_next
            seed_q = q_next
        return chunk

    def _extract_actions(self, body: dict) -> list:
        path = self.spec.response.actions_path
        node = body
        for key in path.split("."):
            node = node[key]
        return node

    def _decode_gripper(self, raw: float | None, current: float | None) -> float | None:
        if raw is None:
            return None
        kind = self.spec.response.action.gripper.kind
        if kind == "absolute":
            return raw
        if kind == "delta":
            return (current or 0.0) + raw
        if kind == "binary":
            return 1.0 if raw >= 0.5 else 0.0
        raise ValueError(f"unknown gripper.kind: {kind}")
```

- [ ] **Step 4: Verify pass** — 1 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/inference/action_decoder.py tests/unit/test_inference_action_decoder.py
git commit -m "feat(inference): ActionDecoder ee_delta chain"
```

### Task 12: Action decoder gripper kinds + frame variants + IK fail hold

**Files:**
- Modify: `tests/unit/test_inference_action_decoder.py`
- Reference: spec §7.3 (each gripper kind, ee_local vs world, IK-fail seed-hold)

- [ ] **Step 1: Write the failing tests** — append three tests:

```python
def test_gripper_binary_kind():
    yaml_bin = YAML_CONTRACT.replace("kind: absolute", "kind: binary").replace(
        "units: normalized_0_1", "units: binary_threshold_0p5",
    )
    spec = ContractSpec.from_yaml_text(yaml_bin)
    dec = ActionDecoder(spec=spec, fk=FakeFK(), ik=FakeIK(), narm=5)
    raw = {"actions": [[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.7]]}
    chunk = dec.decode(raw, current_state=_state())
    assert chunk[0].gripper == 1.0


def test_gripper_delta_kind_accumulates():
    yaml_delta = YAML_CONTRACT.replace("kind: absolute", "kind: delta")
    spec = ContractSpec.from_yaml_text(yaml_delta)
    dec = ActionDecoder(spec=spec, fk=FakeFK(), ik=FakeIK(), narm=5)
    raw = {"actions": [[0.0]*6 + [0.1]]}
    state = _state(); state.gripper_pos = 0.4
    chunk = dec.decode(raw, current_state=state)
    assert chunk[0].gripper == pytest.approx(0.5)


def test_ik_failure_falls_back_to_seed():
    class FailingIK:
        def solve(self, T, seed):
            return seed.copy(), False
    spec = ContractSpec.from_yaml_text(YAML_CONTRACT)
    dec = ActionDecoder(spec=spec, fk=FakeFK(), ik=FailingIK(), narm=5)
    raw = {"actions": [[0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5]]}
    chunk = dec.decode(raw, current_state=_state(joint_pos=np.full(5, 7.0)))
    assert chunk[0].ik_failed
    assert np.allclose(chunk[0].q, 7.0)
```

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: No code changes** — Task 11 should already cover these branches. Verify failing tests indicate any missing logic; otherwise these tests pass directly.

- [ ] **Step 4: Verify pass** — 4 total.

- [ ] **Step 5: Commit**

```
git add tests/unit/test_inference_action_decoder.py
git commit -m "test(inference): action decoder gripper kinds + IK-fail hold"
```

### Task 13: `inference/client.py` — HTTP request + parse

**Files:**
- Create: `backend/mimicrec/inference/client.py`
- Test: `tests/unit/test_inference_client.py`
- Reference: spec §7.2 (snapshot extras), §6 (request/response shape)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_inference_client.py
import asyncio
import base64
import json

import numpy as np
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient

from mimicrec.inference.client import InferenceClient
from mimicrec.inference.contract import ContractSpec
from mimicrec.types import Frame, RobotState, Stamped


YAML = """
name: test
endpoint:
  url: REPLACED_AT_TEST
  method: POST
  retry: { max_attempts: 0 }
request:
  images: { front: { field: image_primary, encoding: jpeg_base64, resize: [16,16], jpeg_quality: 90 } }
  state:  { field: proprio, components: [joint_pos, gripper_pos], normalization: { method: none } }
  instruction: { field: instruction }
response:
  actions_path: actions
  chunk: { expected_size: 2, on_size_mismatch: use_actual }
  action:
    type: ee_delta
    frame: ee_local
    pose: { units: meter_axisangle_rad }
    gripper: { kind: absolute, units: normalized_0_1 }
    components: [ee_delta, gripper]
    normalization: { method: none }
loop:
  prefetch_threshold: 0.5
  max_inflight: 1
"""


async def test_client_round_trip(aiohttp_client):
    received: list[dict] = []

    async def handler(request):
        body = await request.json()
        received.append(body)
        return web.json_response({"actions": [[0.0]*7, [0.1]*7]})

    app = web.Application()
    app.router.add_post("/predict", handler)
    server = await aiohttp_client(app)
    url = str(server.make_url("/predict"))

    spec = ContractSpec.from_yaml_text(YAML.replace("REPLACED_AT_TEST", url))
    client = InferenceClient(spec)
    img = np.zeros((16, 16, 3), dtype=np.uint8)
    frames = {"front": Stamped(value=Frame(image=img, t_mono_ns=1), t_mono_ns=1)}
    state = Stamped(value=RobotState(
        joint_pos=np.zeros(5), joint_vel=np.zeros(5),
        joint_effort=np.zeros(5), gripper_pos=0.0, t_mono_ns=2), t_mono_ns=2)
    instr = Stamped(value="pick", t_mono_ns=3)

    body = await client.predict(frames, state, instr, extras={"_t_mono_ns": {"x": 0}})

    assert "actions" in body
    assert len(received) == 1
    sent = received[0]
    assert sent["instruction"] == "pick"
    assert "image_primary" in sent
    # decode confirms it's a valid jpeg base64 of a 16x16 image
    raw = base64.b64decode(sent["image_primary"])
    assert raw.startswith(b"\xff\xd8")  # JPEG magic
```

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: Implement** — `backend/mimicrec/inference/client.py`:

```python
from __future__ import annotations
import base64
import io
from dataclasses import dataclass
import numpy as np
import httpx
from PIL import Image

from mimicrec.inference.contract import ContractSpec
from mimicrec.types import Frame, RobotState, Stamped


@dataclass
class InferenceClient:
    spec: ContractSpec
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
        # Images
        for cam_name, image_spec in self.spec.request.images.items():
            stamped = frames.get(cam_name)
            if stamped is None:
                continue
            img = stamped.value.image
            body[image_spec.field] = self._encode_image(img, image_spec.resize, image_spec.jpeg_quality)
        # State
        state_components = self.spec.request.state.components
        state_vec: list[float] = []
        for comp in state_components:
            if comp == "joint_pos":
                state_vec.extend(state.joint_pos.tolist())
            elif comp == "gripper_pos":
                state_vec.append(float(state.gripper_pos or 0.0))
            else:
                raise ValueError(f"unsupported state component: {comp}")
        body[self.spec.request.state.field] = state_vec
        # Instruction
        body[self.spec.request.instruction.field] = instruction
        # Extras
        body.update(self.spec.request.extra_fields)
        body.update(extras)
        return body

    @staticmethod
    def _encode_image(img: np.ndarray, resize: tuple[int, int], jpeg_quality: int) -> str:
        pil = Image.fromarray(img)
        if pil.size != tuple(resize):
            pil = pil.resize(tuple(resize))
        buf = io.BytesIO()
        pil.save(buf, format="JPEG", quality=jpeg_quality)
        return base64.b64encode(buf.getvalue()).decode("ascii")
```

(Confirm `Frame` shape from `backend/mimicrec/types.py`. If it has different field names, adjust `stamped.value.image`.)

- [ ] **Step 4: Verify pass** — 1 passed.

Run: `cd backend && env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit/test_inference_client.py -v`

If `aiohttp_client` fixture isn't available, install `pytest-aiohttp` (`uv add --dev pytest-aiohttp` from repo root, then re-run).

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/inference/client.py tests/unit/test_inference_client.py
git commit -m "feat(inference): InferenceClient HTTP request + JPEG encoding"
```

---

## Phase 5 — Producer + control loop

### Task 14: `inference/producer.py` — basic loop with deadlock-safe re-arm

**Files:**
- Create: `backend/mimicrec/inference/producer.py`
- Test: `tests/integration/test_inference_producer_loop.py`
- Reference: spec §7.2 (full producer code; `stop_aware_sleep`, snapshot, generation, on_new_chunk)

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_inference_producer_loop.py
import asyncio
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pytest

from mimicrec.inference.chunk_buffer import ChunkBuffer
from mimicrec.inference.producer import run_inference_producer
from mimicrec.inference.types import StepAction
from mimicrec.types import Frame, RobotState, Stamped


@dataclass
class FakeClient:
    calls: int = 0
    fail_first_n: int = 0
    def __post_init__(self):
        self._lock = asyncio.Lock()
    async def predict(self, frames, state, instr, extras=None):
        self.calls += 1
        if self.calls <= self.fail_first_n:
            raise ConnectionError("boom")
        return {"actions": [[0.0]*7]*4}


@dataclass
class FakeDecoder:
    def decode(self, body, current_state):
        return [StepAction(q=np.zeros(5), gripper=0.0) for _ in range(4)]


@dataclass
class FakeSafety:
    new_chunk_calls: int = 0
    def on_new_chunk(self):
        self.new_chunk_calls += 1


class FakeMetrics:
    def __init__(self):
        self.events = []
    def inc(self, k, v=1): self.events.append(("inc", k, v))
    def observe(self, k, v): self.events.append(("observe", k, v))


class FakeErrorBus:
    def __init__(self):
        self.errors = []
    async def publish_inference_error(self, kind, message):
        self.errors.append((kind, message))


class FakeSession:
    def __init__(self):
        self.stopped = asyncio.Event()
        self.producer_paused = False
        self.state = "ready"


def _slot(value, t=0):
    s = type("Slot", (), {})()
    s._v = Stamped(value=value, t_mono_ns=t)
    s.peek = lambda: s._v
    return s


async def test_producer_pushes_one_chunk():
    buf = ChunkBuffer.create()
    state_slot = _slot(RobotState(
        joint_pos=np.zeros(5), joint_vel=np.zeros(5),
        joint_effort=np.zeros(5), gripper_pos=0.0, t_mono_ns=1))
    instr_slot = _slot("hi")
    img = np.zeros((16, 16, 3), dtype=np.uint8)
    cam_slot = _slot(Frame(image=img, t_mono_ns=1))
    safety = FakeSafety()
    session = FakeSession()
    task = asyncio.create_task(run_inference_producer(
        client=FakeClient(), decoder=FakeDecoder(), buffer=buf,
        camera_slots={"front": cam_slot},
        robot_state_slot=state_slot, instruction_slot=instr_slot,
        safety=safety, session=session,
        metrics=FakeMetrics(), error_bus=FakeErrorBus(),
    ))
    # wait until first push
    for _ in range(50):
        await asyncio.sleep(0.02)
        if buf.depth() > 0:
            break
    assert buf.depth() > 0
    assert safety.new_chunk_calls == 1
    session.stopped.set()
    await task


async def test_producer_recovers_from_initial_state_none():
    buf = ChunkBuffer.create()
    state_holder = type("H", (), {"value": None})()
    state_slot = type("S", (), {"peek": lambda self: state_holder.value})()
    instr_slot = _slot("hi")
    cam_slot = _slot(Frame(image=np.zeros((16,16,3), dtype=np.uint8), t_mono_ns=1))
    session = FakeSession()
    task = asyncio.create_task(run_inference_producer(
        client=FakeClient(), decoder=FakeDecoder(), buffer=buf,
        camera_slots={"front": cam_slot},
        robot_state_slot=state_slot, instruction_slot=instr_slot,
        safety=FakeSafety(), session=session,
        metrics=FakeMetrics(), error_bus=FakeErrorBus(),
    ))
    await asyncio.sleep(0.3)  # let it loop while not_ready
    assert buf.depth() == 0
    # Now make state available
    state_holder.value = Stamped(value=RobotState(
        joint_pos=np.zeros(5), joint_vel=np.zeros(5),
        joint_effort=np.zeros(5), gripper_pos=0.0, t_mono_ns=1), t_mono_ns=1)
    for _ in range(50):
        await asyncio.sleep(0.02)
        if buf.depth() > 0:
            break
    assert buf.depth() > 0
    session.stopped.set()
    await task


async def test_producer_recovers_after_3_errors():
    buf = ChunkBuffer.create()
    state_slot = _slot(RobotState(
        joint_pos=np.zeros(5), joint_vel=np.zeros(5),
        joint_effort=np.zeros(5), gripper_pos=0.0, t_mono_ns=1))
    instr_slot = _slot("hi")
    cam_slot = _slot(Frame(image=np.zeros((16,16,3), dtype=np.uint8), t_mono_ns=1))
    session = FakeSession()
    err = FakeErrorBus()
    client = FakeClient(fail_first_n=3)
    task = asyncio.create_task(run_inference_producer(
        client=client, decoder=FakeDecoder(), buffer=buf,
        camera_slots={"front": cam_slot},
        robot_state_slot=state_slot, instruction_slot=instr_slot,
        safety=FakeSafety(), session=session,
        metrics=FakeMetrics(), error_bus=err,
    ))
    for _ in range(150):
        await asyncio.sleep(0.05)
        if buf.depth() > 0:
            break
    assert buf.depth() > 0
    assert client.calls >= 4
    assert len(err.errors) == 3
    session.stopped.set()
    await task
```

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: Implement** — copy `run_inference_producer` from spec §7.2 verbatim into `backend/mimicrec/inference/producer.py`. Include:

```python
from __future__ import annotations
import asyncio
import time

# Map exception to short kind label used by error_bus + WS.
def classify(e: Exception) -> str:
    name = type(e).__name__
    if "Timeout" in name:
        return "http_timeout"
    if "JSONDecode" in name or "KeyError" in name:
        return "schema"
    return "transport"


async def run_inference_producer(
    client, decoder, buffer, camera_slots, robot_state_slot, instruction_slot,
    safety, session, metrics, error_bus,
):
    buffer.request_refill_now()
    backoff_s = 0.1
    NOT_READY_RETRY_S = 0.05

    async def stop_aware_sleep(seconds: float) -> bool:
        try:
            await asyncio.wait_for(session.stopped.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False

    while not session.stopped.is_set():
        await buffer.wait_for_refill()

        if session.producer_paused:
            continue

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
            buffer.request_refill_now()
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
                buffer.request_refill_now()
            else:
                safety.on_new_chunk()
                metrics.observe("inference_latency_ms",
                                (time.perf_counter() - t0) * 1000)
                backoff_s = 0.1
        except Exception as e:
            metrics.inc("inference_error_count")
            await error_bus.publish_inference_error(kind=classify(e), message=str(e))
            if await stop_aware_sleep(backoff_s):
                return
            backoff_s = min(backoff_s * 2, 1.0)
            buffer.request_refill_now()
```

- [ ] **Step 4: Verify pass** — 3 passed.

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/inference/producer.py tests/integration/test_inference_producer_loop.py
git commit -m "feat(inference): producer with re-arm, snapshot, generation, on_new_chunk"
```

### Task 15: `inference/control_loop.py` — run_inference_control_loop

**Files:**
- Create: `backend/mimicrec/inference/control_loop.py`
- Test: deferred to Task 17 (lifecycle integration)
- Reference: spec §7.6 (mirrors run_teleop_control_loop except action source + safety)

- [ ] **Step 1: Implement** — `backend/mimicrec/inference/control_loop.py`:

```python
from __future__ import annotations
import asyncio
from typing import Callable

from mimicrec.inference.chunk_buffer import ChunkBuffer
from mimicrec.inference.safety import InferenceSafety
from mimicrec.session.state import Session
from mimicrec.types import (
    RobotState, RobotCommand, SessionState, Stamped, SampleBundle,
)
from mimicrec.util.clock import Clock
from mimicrec.util.latest_value import LatestValue
from mimicrec.util.metrics import Metrics


async def run_inference_control_loop(
    session: Session,
    fps: int,
    robot_state_slot: LatestValue[RobotState],
    camera_slots: dict[str, LatestValue[object]],
    chunk_buffer: ChunkBuffer,
    safety: InferenceSafety,
    command_goal_slot: LatestValue[RobotCommand],
    enqueue: Callable[[SampleBundle], None],
    clock: Clock,
    metrics: Metrics,
) -> None:
    tick_interval_ns = 1_000_000_000 // fps
    next_tick_ns = clock.monotonic_ns() + tick_interval_ns

    while not session.stopped.is_set():
        tick_t = clock.monotonic_ns()

        if tick_t >= next_tick_ns + tick_interval_ns:
            skipped = (tick_t - next_tick_ns) // tick_interval_ns
            metrics.inc("ticks_skipped", int(skipped))
            next_tick_ns = tick_t + tick_interval_ns

        phase = session.state
        if phase == SessionState.REVIEW:
            # control_loop continues but pop_next() returns None → safety slow-stops
            pass

        state = robot_state_slot.peek()
        if state is None:
            await clock.sleep_until(next_tick_ns); next_tick_ns += tick_interval_ns; continue

        step = chunk_buffer.pop_next() if phase != SessionState.REVIEW else None
        command = safety.filter(step, state.value.joint_pos[:safety.joint_min.shape[0]], tick_t)

        if not session.replay_active:
            command_goal_slot.set(command, t_mono_ns=command.t_mono_ns)

        if phase == SessionState.RECORDING:
            frames = {name: slot.peek() for name, slot in camera_slots.items()}
            enqueue(SampleBundle(
                tick_t_mono_ns=tick_t, state=state, action=command, frames=frames,
            ))

        await clock.sleep_until(next_tick_ns)
        next_tick_ns += tick_interval_ns
```

- [ ] **Step 2: Commit (no separate test — Task 17 covers integration)**

```
git add backend/mimicrec/inference/control_loop.py
git commit -m "feat(inference): run_inference_control_loop"
```

---

## Phase 6 — Lifecycle integration

### Task 16: Lifecycle scaffolding — instruction_slot + start_inference_session

**Files:**
- Modify: `backend/mimicrec/session/lifecycle.py`
- Reference: spec §8 (full lifecycle integration)

This task adds the new fields, helper methods, and a basic `start_inference_session()`. Wiring is verified by Task 17.

- [ ] **Step 1: Read existing lifecycle.py to understand init/teardown**

```
cd backend && grep -n "def __init__\|def start_\|def stop_\|def episode_\|self\._teleop\|self\._control_loop_task" mimicrec/session/lifecycle.py | head -40
```

- [ ] **Step 2: Add fields to `SessionManager.__init__`**

In `__init__`, add:

```python
self._instruction_slot: LatestValue[str] = LatestValue()
self._chunk_buffer: ChunkBuffer | None = None
self._inference_safety: InferenceSafety | None = None
self._producer_task: asyncio.Task | None = None
self._inference_watchdog_task: asyncio.Task | None = None
```

Imports at top of file:

```python
from mimicrec.inference.chunk_buffer import ChunkBuffer
from mimicrec.inference.safety import InferenceSafety
from mimicrec.inference.producer import run_inference_producer
from mimicrec.inference.control_loop import run_inference_control_loop
from mimicrec.inference.action_decoder import ActionDecoder
from mimicrec.inference.client import InferenceClient
from mimicrec.inference.contract import ContractSpec
```

Also add to `Session` (in `state.py`):

```python
producer_paused: bool = False
locked_instruction: str | None = None
```

- [ ] **Step 3: Add `start_inference_session` method to `SessionManager`**

```python
async def start_inference_session(
    self,
    contract: ContractSpec,
    instruction: str,
    inference_config_name: str,
) -> None:
    """Replaces start_recording_session for INFERENCE mode."""
    if self.session.state != SessionState.READY:
        raise InvalidTransitionError(...)

    self.session.mode = SessionMode.INFERENCE
    self._inference_config_name = inference_config_name
    self._instruction_slot.set(instruction, t_mono_ns=0)
    self.session.locked_instruction = None
    self.session.producer_paused = False

    # Build inference subsystem
    action_stats = contract.resolve_action_stats() if contract.response.action.normalization.method != "none" else None
    self._chunk_buffer = ChunkBuffer.create(
        prefetch_threshold=contract.loop.prefetch_threshold,
    )
    safety_cfg = self._robot_safety_config()  # reads inference_safety from configs/robot/<name>.yaml
    if safety_cfg is None:
        raise InvalidTransitionError("inference_safety block is required in robot config")
    self._inference_safety = InferenceSafety(
        max_delta=safety_cfg["max_joint_delta_per_step_deg"],
        joint_min=safety_cfg["joint_min"],
        joint_max=safety_cfg["joint_max"],
        slow_stop_ticks=safety_cfg["slow_stop_ticks"],
    )

    # Spawn readers same as TELEOP, except teleop reader is NOT spawned
    self._robot_reader_task = asyncio.create_task(self._run_robot_reader())
    camera_slots = {name: self._cameras.latest(name) for name in self._cameras._cameras}

    fk = self._fk
    ik = IKService(fk._cfg)  # share KinematicsConfig
    decoder = ActionDecoder(spec=contract, fk=fk, ik=ik, narm=self._robot.dof)
    client = InferenceClient(spec=contract)
    self._inference_client = client

    self._producer_task = asyncio.create_task(run_inference_producer(
        client=client, decoder=decoder, buffer=self._chunk_buffer,
        camera_slots=camera_slots, robot_state_slot=self._robot_state_slot,
        instruction_slot=self._instruction_slot, safety=self._inference_safety,
        session=self.session, metrics=self._metrics, error_bus=self._error_bus,
    ))
    self._control_loop_task = asyncio.create_task(run_inference_control_loop(
        session=self.session, fps=self._fps,
        robot_state_slot=self._robot_state_slot, camera_slots=camera_slots,
        chunk_buffer=self._chunk_buffer, safety=self._inference_safety,
        command_goal_slot=self._command_goal_slot,
        enqueue=self._recorder_queue.put_nowait,
        clock=RealClock(), metrics=self._metrics,
    ))
    self._dispatcher_task = asyncio.create_task(run_command_dispatcher(
        self._robot, self._command_goal_slot, self._error_bus, self.session.stopped,
    ))
    self._writer_task = asyncio.create_task(run_writer(
        current_pending=self._current_pending,
        queue=self._recorder_queue, metrics=self._metrics,
        stopped=self.session.stopped, fk=self._fk,
    ))
```

- [ ] **Step 4: Add `_robot_safety_config()` helper**

```python
def _robot_safety_config(self) -> dict | None:
    """Read inference_safety: from the active robot's YAML config."""
    cfg = self._robot_config_dict.get("inference_safety")
    if cfg is None:
        return None
    joint_names = self._robot.joint_names
    limits = cfg["joint_limits_deg"]
    joint_min = np.array([limits[n][0] for n in joint_names])
    joint_max = np.array([limits[n][1] for n in joint_names])
    return {
        "max_joint_delta_per_step_deg": cfg["max_joint_delta_per_step_deg"],
        "slow_stop_ticks": cfg.get("slow_stop_ticks", 5),
        "joint_min": joint_min,
        "joint_max": joint_max,
    }
```

(The `_robot_config_dict` is populated when the session manager is built — verify by reading the existing code that loads `configs/robot/<name>.yaml`. If the dict isn't currently retained, add `self._robot_config_dict = robot_cfg` at the relevant `__init__` point. **See "Open implementation questions" at the bottom of this plan — confirm before coding.**)

- [ ] **Step 5: Add stop + pause/resume helpers**

```python
async def stop_inference_session(self) -> None:
    self.session.stopped.set()
    for t in (self._producer_task, self._control_loop_task, self._dispatcher_task, self._writer_task):
        if t is not None:
            t.cancel()
    if self._inference_client is not None:
        await self._inference_client.aclose()

def pause_producer_and_flush(self) -> int:
    """Order-locked: producer_paused FIRST, then flush.
    Returns the flushed step count for telemetry."""
    self.session.producer_paused = True
    return self._chunk_buffer.flush()

def resume_producer(self) -> None:
    self.session.producer_paused = False
    self._chunk_buffer.request_refill_now()
```

- [ ] **Step 6: Commit (compiles only; integration test follows)**

```
cd backend && env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -c "from mimicrec.session.lifecycle import SessionManager; print('ok')"
git add backend/mimicrec/session/lifecycle.py backend/mimicrec/session/state.py
git commit -m "feat(session): lifecycle scaffolding for SessionMode.INFERENCE"
```

### Task 17: Integration test — start/stop inference session

**Files:**
- Test: `tests/integration/test_inference_lifecycle.py`
- Reference: spec §8.1, §8.2 (409 if active session)
- **Ordering note**: this task's tests need the `fake_vla_server` fixture from **Task 26** and the `make_inference_session` helper from `tests/conftest.py` (also added during Task 26). Implement Task 26 first, then return here. The skeleton can be checked in earlier as a placeholder if helpful.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_inference_lifecycle.py
import asyncio
import pytest

from mimicrec.types import SessionMode, SessionState


async def test_start_inference_against_mock_robot(monkeypatch, tmp_path, fake_vla_server):
    """Start inference session, give it a brief moment, then stop. Expect:
    - control_loop and producer tasks spawned
    - SessionMode = INFERENCE, SessionState = READY
    - dispatcher + writer present
    """
    # Use the in-test fixture from conftest that sets up a SessionManager
    # with mock_robot adapter and ensures a configs/inference/test.yaml exists.
    # NOTE: This test depends on conftest.py providing a `make_session_manager`
    # fixture; if not present, add one in tests/conftest.py.
    ...


async def test_409_when_session_already_active():
    ...


async def test_pause_and_resume_helpers():
    ...
```

(Keep this test high-level to avoid duplicating producer-loop tests. Verifies wiring + tasks exist + 409 path.)

- [ ] **Step 2: Run the integration test against the fake server fixture (Task 26 prerequisite)** — defer if `fake_vla_server` fixture is not yet set up; revisit after Task 26.

- [ ] **Step 3: Commit (after Task 26 lands)**

---

## Phase 7 — REST + WS API

### Task 18: `api/routes/inference.py` — REST endpoints

**Files:**
- Create: `backend/mimicrec/api/routes/inference.py`
- Modify: `backend/mimicrec/api/app.py` (register router)
- Test: `tests/integration/test_inference_api.py`
- Reference: spec §8.2

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_inference_api.py
import pytest
from fastapi.testclient import TestClient

# This depends on conftest.py exposing an `app` fixture; if absent, add one
# that wires a SessionManager around mock_robot.


def test_get_configs_inference_lists(app):
    client = TestClient(app)
    r = client.get("/configs/inference")
    assert r.status_code == 200
    assert "items" in r.json()


def test_post_start_returns_session_id(app):
    client = TestClient(app)
    body = {
        "session_config_ref": "default",
        "inference_config_ref": "test",
        "dataset_ref": "SO101",
        "instruction": "pick the bottle",
    }
    r = client.post("/session/inference/start", json=body)
    assert r.status_code in (200, 409)


def test_put_instruction_409_during_recording(app):
    ...
```

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: Implement** — `backend/mimicrec/api/routes/inference.py`:

```python
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from mimicrec.api.deps import get_session_manager_or_none, get_configs_root
from mimicrec.config.inference_loader import list_inference_configs, load_inference_config
from mimicrec.types import SessionMode, SessionState

router = APIRouter()


class StartInferenceRequest(BaseModel):
    session_config_ref: str
    inference_config_ref: str
    dataset_ref: str
    instruction: str


class UpdateInstructionRequest(BaseModel):
    text: str


@router.post("/session/inference/start")
async def start_inference(request: Request, body: StartInferenceRequest):
    sm = get_session_manager_or_none(request.app)
    if sm is not None and sm.session.state != SessionState.READY:
        raise HTTPException(409, "another session is already active")
    contract = load_inference_config(get_configs_root(request.app), body.inference_config_ref)
    # build / get session manager via existing dep
    if sm is None:
        sm = build_session_manager_for_inference(request.app, body)  # implement in deps
    await sm.start_inference_session(
        contract=contract,
        instruction=body.instruction,
        inference_config_name=body.inference_config_ref,
    )
    return {"session_id": "inference-1", "state": sm.session.state.value}


@router.post("/session/inference/stop")
async def stop_inference(request: Request):
    sm = get_session_manager_or_none(request.app)
    if sm is None:
        raise HTTPException(409, "no active session")
    await sm.stop_inference_session()
    return {"ok": True}


@router.put("/session/inference/instruction")
async def update_instruction(request: Request, body: UpdateInstructionRequest):
    sm = get_session_manager_or_none(request.app)
    if sm is None:
        raise HTTPException(409, "no active session")
    if sm.session.state == SessionState.RECORDING:
        raise HTTPException(409, "cannot update instruction during RECORDING")
    # Per spec §8.1 Q17: PUT during READY just flushes and re-arms the producer.
    # We do NOT pause the producer here — that helper (pause_producer_and_flush)
    # is for REVIEW only, where we don't want a fresh fetch until the operator
    # commits/discards. During READY we WANT the producer to immediately fetch
    # a chunk under the new instruction.
    sm._instruction_slot.set(body.text, t_mono_ns=0)
    flushed = sm._chunk_buffer.flush()
    # Publish to inference_hub
    await sm.inference_hub.publish({
        "type": "instruction_updated", "text": body.text, "flushed_steps": flushed,
    })
    return {"ok": True}


@router.get("/session/inference/state")
async def inference_state(request: Request):
    sm = get_session_manager_or_none(request.app)
    if sm is None:
        return {"phase": "pre_start"}
    return sm.inference_state_snapshot()


@router.get("/configs/inference")
async def list_configs(request: Request):
    items = list_inference_configs(get_configs_root(request.app))
    return {"items": items}


@router.get("/configs/inference/{name}")
async def get_config(request: Request, name: str):
    contract = load_inference_config(get_configs_root(request.app), name)
    return contract.model_dump(exclude={"endpoint": {"headers"}})  # elide secrets
```

(The `build_session_manager_for_inference` and `inference_state_snapshot` are TODO bits to fill in — read existing `api/deps.py` for how the teleop session is built and mirror the path.)

Register in `api/app.py`:

```python
from mimicrec.api.routes import inference as inference_routes
app.include_router(inference_routes.router)
```

- [ ] **Step 4: Implement `config/inference_loader.py`**

```python
from __future__ import annotations
from pathlib import Path

from mimicrec.inference.contract import ContractSpec


def list_inference_configs(configs_root: Path) -> list[dict]:
    d = configs_root / "inference"
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.yaml")):
        spec = ContractSpec.from_yaml_text(p.read_text())
        out.append({"name": spec.name, "description": spec.description})
    return out


def load_inference_config(configs_root: Path, name: str) -> ContractSpec:
    p = configs_root / "inference" / f"{name}.yaml"
    if not p.exists():
        raise FileNotFoundError(p)
    return ContractSpec.from_yaml_text(p.read_text())
```

- [ ] **Step 5: Verify pass** (against fake server fixture from Task 26).

- [ ] **Step 6: Commit**

```
git add backend/mimicrec/api/routes/inference.py backend/mimicrec/config/inference_loader.py backend/mimicrec/api/app.py tests/integration/test_inference_api.py
git commit -m "feat(api): /session/inference/* + /configs/inference/* routes"
```

### Task 19: `api/ws/inference_hub.py` — WS hub

**Files:**
- Create: `backend/mimicrec/api/ws/inference_hub.py`
- Modify: `backend/mimicrec/api/app.py`
- Reference: spec §8.4 (event schemas)

- [ ] **Step 1: Read existing hub patterns**

```
cd backend && cat mimicrec/api/ws/teleop_hub.py
```

Mirror the publish/subscribe pattern exactly.

- [ ] **Step 2: Implement** — `backend/mimicrec/api/ws/inference_hub.py`:

Wire to identical FastAPI WebSocket pattern as `teleop_hub`. Endpoint: `/ws/inference`. Methods: `publish(event: dict)`, with internal subscriber list; on connect, subscribe; on disconnect, unsubscribe.

- [ ] **Step 3: Hook publish points**

In `lifecycle.py`:
- `pause_producer_and_flush` → `await self.inference_hub.publish({"type": "instruction_locked", ...})` (when used at episode_start)
- in `episode_start` for inference mode: publish `{"type": "instruction_locked", "text": locked}`
- in `episode_stop` and `episode_save/discard`: publish `{"type": "instruction_released"}` and `{"type": "episode_phase", "phase": ...}`
- in `_inference_watchdog_task`: publish `{"type": "watchdog_timeout", ...}` on fire

In `producer.py`: surface `inference_started` / `inference_done` / `inference_error` / `inference_chunk_dropped_stale` / `clamps_per_chunk`.

(Plumb the hub via a callback/queue; don't import the hub directly in `inference/` to keep the module standalone — pass an `events: asyncio.Queue` or a `publish_event: Callable[[dict], Awaitable]` parameter.)

- [ ] **Step 4: Commit**

```
git add backend/mimicrec/api/ws/inference_hub.py backend/mimicrec/api/app.py backend/mimicrec/session/lifecycle.py backend/mimicrec/inference/producer.py
git commit -m "feat(api): inference_hub WS channel + event plumbing"
```

### Task 20: Lifecycle — episode lock/release + watchdog + recording columns

**Files:**
- Modify: `backend/mimicrec/session/lifecycle.py`
- Modify: `backend/mimicrec/recording/metadata.py`
- Test: `tests/integration/test_inference_recording.py`
- Reference: spec §8.3 (lock semantics + 3 columns), §8.5 (watchdog)

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_inference_recording.py
import asyncio
import json

import pytest


async def test_inference_recording_round_trip(make_inference_session, fake_vla_server, tmp_path):
    """start session → episode_start → tick a few frames → episode_stop → save(success=True).
    Verify: parquet rows, mp4, tasks.parquet has instruction, episodes.jsonl has source/inference_config/stop_reason."""
    sm = await make_inference_session(instruction="pick X")
    await sm.episode_start()
    await asyncio.sleep(0.5)
    await sm.episode_stop()
    await sm.episode_save(success=True, comment=None)

    ds_root = sm._dataset_root
    eps_jsonl = (ds_root / "meta" / "episodes" / "chunk-000" / "file-000.parquet")
    # Or the .jsonl if that's the format on disk; adapt to whichever.

    # Read latest episode metadata and assert columns
    ...


async def test_max_episode_seconds_watchdog_fires(make_inference_session):
    sm = await make_inference_session(instruction="hold", max_seconds=0.5)
    await sm.episode_start()
    await asyncio.sleep(1.0)
    assert sm.session.state.value == "review"
    # Last broadcast event should be watchdog_timeout
    ...
```

- [ ] **Step 2: Implement episode_start/stop changes in `lifecycle.py`**

```python
async def episode_start(self) -> None:
    # ... existing teleop logic up to setting RECORDING state ...
    if self.session.mode == SessionMode.INFERENCE:
        self.session.locked_instruction = self._instruction_slot.peek().value
        await self.inference_hub.publish({
            "type": "instruction_locked",
            "text": self.session.locked_instruction,
        })
        # Spawn watchdog
        max_sec = self._session_config.max_episode_seconds or 120
        self._inference_watchdog_task = asyncio.create_task(
            self._run_watchdog(max_sec)
        )

async def episode_stop(self, *, stop_reason: str = "manual") -> None:
    if self._inference_watchdog_task is not None:
        self._inference_watchdog_task.cancel()
        self._inference_watchdog_task = None
    if self.session.mode == SessionMode.INFERENCE:
        await self.inference_hub.publish({"type": "instruction_released"})
        self.session.locked_instruction = None
        self._last_stop_reason = stop_reason
    # ... existing teleop logic ...

async def _run_watchdog(self, max_sec: float) -> None:
    try:
        await asyncio.sleep(max_sec)
        await self.inference_hub.publish({
            "type": "watchdog_timeout", "elapsed_sec": max_sec,
        })
        await self.episode_stop(stop_reason="timeout")
    except asyncio.CancelledError:
        pass
```

- [ ] **Step 3: Add 3 columns to `recording/metadata.py`**

Find the function that writes episode metadata:

```
cd backend && grep -n 'episodes.jsonl\|episodes_jsonl\|append_episode\|write_episode\|episode_record\|episodes_dir' mimicrec/recording/metadata.py
```

Then add (preserve existing keys):

```python
# In whichever function writes the episodes record:
record = {
    # existing keys ...
    "source": session.mode.value if session.mode == SessionMode.INFERENCE else None,
    "inference_config": getattr(session, "_inference_config_name", None),
    "stop_reason": getattr(session, "_last_stop_reason", None),
}
```

(`source` is `None` for legacy/teleop episodes — additive, non-breaking.)

- [ ] **Step 4: Verify pass.**

- [ ] **Step 5: Commit**

```
git add backend/mimicrec/session/lifecycle.py backend/mimicrec/recording/metadata.py tests/integration/test_inference_recording.py
git commit -m "feat(recording): inference instruction lock + watchdog + 3 episode columns"
```

---

## Phase 8 — Configs

### Task 21: `configs/robot/so101.yaml` — add inference_safety block

**Files:**
- Modify: `configs/robot/so101.yaml`
- Reference: spec §7.4

- [ ] **Step 1: Append**

```yaml
inference_safety:
  max_joint_delta_per_step_deg: 2.0
  slow_stop_ticks: 5
  joint_limits_deg:
    shoulder_pan: [-180.0, 180.0]
    shoulder_lift: [-110.0, 110.0]
    elbow_flex: [-110.0, 110.0]
    wrist_flex: [-110.0, 110.0]
    wrist_roll: [-180.0, 180.0]
```

- [ ] **Step 2: Commit**

```
git add configs/robot/so101.yaml
git commit -m "config(so101): inference_safety block (REQUIRED for inference)"
```

### Task 22: `configs/inference/gemma_libero_v1.yaml` + README.md

**Files:**
- Create: `configs/inference/gemma_libero_v1.yaml` (copy verbatim from spec §14)
- Create: `configs/inference/README.md`

- [ ] **Step 1: Copy YAML from spec §14**

(Take the full sample YAML from the spec appendix.)

- [ ] **Step 2: README**: explain each block (endpoint / request / response / loop), example for swapping in OpenVLA, env-var pattern.

- [ ] **Step 3: Commit**

```
git add configs/inference/gemma_libero_v1.yaml configs/inference/README.md
git commit -m "config(inference): gemma_libero_v1 template + README"
```

---

## Phase 9 — Frontend

### Task 23: `frontend/src/api/inference.ts` — REST + WS hooks

**Files:**
- Create: `frontend/src/api/inference.ts`
- Reference: spec §8.2 / §8.4

- [ ] **Step 1: Skeleton**

```typescript
import { apiClient } from "./client"

export interface ContractSpec { name: string; description: string; /* full type from openapi or hand-written */ }

export const inferenceApi = {
  listConfigs: () => apiClient.get("/configs/inference").json<{items: {name:string; description:string}[]}>(),
  getConfig: (name: string) => apiClient.get(`/configs/inference/${name}`).json<ContractSpec>(),
  start: (body: StartBody) => apiClient.post("/session/inference/start", { json: body }).json<{session_id: string; state: string}>(),
  stop: () => apiClient.post("/session/inference/stop").json(),
  updateInstruction: (text: string) =>
    apiClient.put("/session/inference/instruction", { json: { text } }).json(),
  state: () => apiClient.get("/session/inference/state").json(),
  estop: () => apiClient.post("/robot/estop").json(),
}

export interface InferenceTelemetryEvent {
  type: "buffer_state" | "inference_started" | "inference_done" | "inference_error"
      | "inference_chunk_dropped_stale" | "safety_event" | "clamps_per_chunk"
      | "instruction_updated" | "instruction_locked" | "instruction_released"
      | "next_action_preview" | "episode_phase" | "model_done" | "watchdog_timeout"
  // discriminated union — flesh out per spec §8.4
  [key: string]: any
}

export function subscribeInferenceWS(onEvent: (e: InferenceTelemetryEvent) => void): () => void {
  const ws = new WebSocket(`${wsBase()}/ws/inference`)
  ws.onmessage = (m) => onEvent(JSON.parse(m.data))
  return () => ws.close()
}
```

- [ ] **Step 2: Commit**

```
git add frontend/src/api/inference.ts
git commit -m "feat(frontend): inference REST client + WS hook"
```

### Task 24: `frontend/src/stores/inference-store.ts` — Zustand store

**Files:**
- Create: `frontend/src/stores/inference-store.ts`
- Reference: spec §9 store shape

- [ ] **Step 1: Implement** the store shape per spec §9, including reducer methods that drive UI and WS-event handlers that update telemetry.

- [ ] **Step 2: Commit**

```
git add frontend/src/stores/inference-store.ts
git commit -m "feat(frontend): inference Zustand store"
```

### Task 25: `frontend/src/pages/InferencePage.tsx`

**Files:**
- Create: `frontend/src/pages/InferencePage.tsx`
- Modify: `frontend/src/App.tsx` (route)
- Reference: spec §9 (4 phases, banner during READY, REVIEW success/failure)

- [ ] **Step 1: Implement skeleton with phase switch**

Pseudo:

```tsx
function InferencePage() {
  const { phase, telemetry, ... } = useInferenceStore()
  return (
    <div>
      <Header live={phase === "ready" || phase === "recording"} onEstop={inferenceApi.estop} />
      {phase === "pre-start" && <PreStartPanel />}
      {phase === "ready" && <ReadyPanel />}
      {phase === "recording" && <RecordingPanel />}
      {phase === "review" && <ReviewPanel />}
    </div>
  )
}
```

The READY panel includes the **yellow "Robot under model control" banner** at the top.

The REVIEW panel exposes Save (✓ success) / Save (✗ failure) / Discard, calling `POST /episode/save` with `{success: true|false}` or `POST /episode/discard`.

- [ ] **Step 2: Add route in `App.tsx`**

```tsx
import { InferencePage } from "./pages/InferencePage"
// ...
<Route path="/inference" element={<InferencePage />} />
```

- [ ] **Step 3: Verify by running dev server and clicking through**

```
cd frontend && npm run dev
```

Open `http://localhost:5173/inference`. Confirm: pre-start renders, dropdowns populate, Start session button is wired (will fail without a running backend or a configured contract — that's fine, just verify UI).

- [ ] **Step 4: Commit**

```
git add frontend/src/pages/InferencePage.tsx frontend/src/App.tsx
git commit -m "feat(frontend): InferencePage with 4-phase rendering + yellow banner"
```

---

## Phase 10 — E2E

### Task 26: `tests/fixtures/fake_vla_server.py`

**Files:**
- Create: `tests/fixtures/fake_vla_server.py`
- Reference: spec §11 E2E

- [ ] **Step 1: Implement** an aiohttp-based fixture that:
  - serves `POST /predict` with a configurable canned chunk emitter
  - allows error injection (return 500 N times then succeed)
  - returns latency-controllable responses (sleep before respond)
  - exposes `received_requests` for inspection

```python
# tests/fixtures/fake_vla_server.py
import asyncio
from aiohttp import web


class FakeVLAServer:
    def __init__(self, *, chunk_size=16, fail_first_n=0, latency_s=0.0):
        self.chunk_size = chunk_size
        self.fail_first_n = fail_first_n
        self.latency_s = latency_s
        self.calls = 0
        self.received: list[dict] = []
        self._app = web.Application()
        self._app.router.add_post("/predict", self._handler)
        self._runner = None
        self._port = None

    async def __aenter__(self):
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self._port = site._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *args):
        await self._runner.cleanup()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._port}/predict"

    async def _handler(self, request):
        self.calls += 1
        body = await request.json()
        self.received.append(body)
        if self.calls <= self.fail_first_n:
            return web.Response(status=500)
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        chunk = [[0.0]*7 for _ in range(self.chunk_size)]
        # mild motion: nudge ee_delta x by 0.001 each step
        for i, step in enumerate(chunk):
            step[0] = 0.001
            step[6] = 0.5
        return web.json_response({"actions": chunk})
```

- [ ] **Step 2: Add fixture**

```python
# tests/conftest.py — append
import pytest
from tests.fixtures.fake_vla_server import FakeVLAServer

@pytest.fixture
async def fake_vla_server():
    async with FakeVLAServer() as srv:
        yield srv
```

- [ ] **Step 3: Commit**

```
git add tests/fixtures/fake_vla_server.py tests/conftest.py
git commit -m "test(inference): fake VLA HTTP server fixture"
```

### Task 27: `tests/e2e/test_inference_e2e.py`

**Files:**
- Create: `tests/e2e/__init__.py`, `tests/e2e/test_inference_e2e.py`
- Reference: spec §11 (60s loop + REVIEW-tail assertion)

- [ ] **Step 1: Implement**

```python
# tests/e2e/test_inference_e2e.py
import asyncio
import time
from pathlib import Path

import numpy as np
import pytest


@pytest.mark.e2e
async def test_inference_60s_against_mock_robot(make_inference_session, fake_vla_server):
    sm = await make_inference_session(
        instruction="pick the bottle",
        contract_url=fake_vla_server.url,
    )
    # READY for ~10s to let producer fill, then RECORDING for 50s
    await sm.episode_start()
    end = time.monotonic() + 50.0
    while time.monotonic() < end:
        await asyncio.sleep(0.1)
    await sm.episode_stop()

    assert fake_vla_server.calls > 1
    assert sm.metrics.events.count("inference_error_count") == 0  # no errors
    # Verify parquet + mp4 written
    ds = sm._dataset_root
    parquet = list((ds / "data" / "chunk-000").glob("*.parquet"))
    assert len(parquet) > 0


@pytest.mark.e2e
async def test_review_tail_within_max_delta(make_inference_session, fake_vla_server):
    sm = await make_inference_session(instruction="x", contract_url=fake_vla_server.url)
    captured: list[np.ndarray] = []
    sm._command_goal_slot.subscribe(lambda c: captured.append(c.value.q.copy()))

    await sm.episode_start()
    await asyncio.sleep(0.5)
    await sm.episode_stop()

    # Capture next 100ms of dispatched commands and assert deltas <= max_delta
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.1:
        await asyncio.sleep(0.01)

    deltas = [np.abs(captured[i+1] - captured[i]).max() for i in range(len(captured)-1)]
    if deltas:
        assert max(deltas) <= 2.0 + 1e-6, "REVIEW-tail must respect max_joint_delta_per_step_deg"
```

- [ ] **Step 2: Add `e2e` marker to `pytest.ini`**

```
[pytest]
asyncio_mode = auto
markers =
    e2e: end-to-end tests (slow, require running fake server)
```

- [ ] **Step 3: Run**

```
cd backend && env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest -m e2e ../tests/e2e -v
```

- [ ] **Step 4: Commit**

```
git add tests/e2e/test_inference_e2e.py tests/e2e/__init__.py pytest.ini
git commit -m "test(inference): E2E with fake VLA + mock_robot + REVIEW-tail check"
```

---

## Phase 11 — Wrap-up

### Task 28: Update `docs/architecture.md`

Reference: existing diagram in `docs/architecture.md`.

- [ ] **Step 1: Add an `inference/` subgraph** to the mermaid diagram showing:
  - `InferenceProducer ──HTTP──> VLA Server`
  - `ChunkBuffer → ActionDecoder → InferenceSafety → command_goal_slot`
  - new WS `/ws/inference`

- [ ] **Step 2: Add a paragraph** under Notes describing the inference mode.

- [ ] **Step 3: Commit**

```
git add docs/architecture.md
git commit -m "docs(architecture): add VLA inference mode to system diagram"
```

### Task 29: Final smoke run

- [ ] **Step 1: Run all unit tests**

```
cd backend && env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/unit -v
```

Expected: all passing.

- [ ] **Step 2: Run integration tests**

```
cd backend && env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest ../tests/integration -v
```

Expected: all passing.

- [ ] **Step 3: Run E2E**

```
cd backend && env -u PYTHONPATH /home/takakimaeda/MimicRec/.venv/bin/python -m pytest -m e2e ../tests/e2e -v
```

- [ ] **Step 4: Manual frontend smoke**

```
cd frontend && npm run dev
```

Open `http://localhost:5173/inference`, click around, confirm the four phases render.

- [ ] **Step 5: Final commit (no-op)**

```
git status   # should be clean
```

---

## Notes for the implementer

- **`@superpowers:test-driven-development`** drives the loop: write failing test → run to fail → minimal implementation → run to pass → commit. Do not skip the "run to fail" step.
- **`@superpowers:verification-before-completion`** before claiming any task complete: run the test commands, see PASS, then commit.
- For each task: keep code minimal, no speculative features. Defer anything not in the spec to a follow-up.
- If a Pydantic v2 forward-ref warning appears for `NormalizationSpec.stats_ref`, call `NormalizationSpec.model_rebuild()` once at module bottom.
- If lerobot's IK API requires radians or a different method signature than assumed, adjust `IKService` — the `IKService` test (Task 6) catches divergence.
- Frontend tasks may require minor `App.tsx` / routing tweaks to match the existing navigation pattern. Verify by clicking through.
- E2E tests require `pytest-aiohttp` and `aiohttp` available in the venv. Add via `uv add --dev pytest-aiohttp aiohttp` from repo root.
- The lifecycle changes touch the largest file (`session/lifecycle.py:575+`); read carefully before editing, and prefer additive surgery over restructuring.

---

## Open implementation questions (surface before coding if blocked)

- **`api/deps.build_session_manager_for_inference`**: how is the SessionManager currently constructed for teleop? Does it expect a teleop adapter or can it boot without one? (Task 18 / Task 16 may need a small adjustment.)
- **`Frame` vs `np.ndarray` in camera slots**: does the existing camera manager publish `Stamped[Frame]` or `Stamped[np.ndarray]`? (Affects `client._build_request_body` — see Task 13.)
- **`_robot_config_dict` retention**: lifecycle currently constructs the robot adapter via Hydra-style `_target_` dict; confirm whether the raw config dict is retained or has to be re-loaded for `_robot_safety_config()`.
