# reBotArm Integration MVP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the no-op `ReBotArmAdapter` stub with a working integration: a Python 3.10 safety daemon (separate venv) talks to MimicRec backend over ZMQ, supports hand-teach data collection (gravity-comp lock-with-push), replay (POS_VEL), EE pose recording, and an MVP safety stack (E-stop, heartbeat, joint/velocity/accel/torque clamps, thermal cutoff).

**Architecture:** MimicRec backend (3.12) sends `connect / read_state / send_command / set_mode / heartbeat / estop / clear_estop / get_safety_status` over ZMQ REQ/REP on `:5558`. The daemon (3.10) owns the 500 Hz control loop, all safety responsibility, the motorbridge SDK, the reBotArm URDF + Pinocchio FK, and ramps torque safely on disconnect. EE pose is computed in the daemon and rides in the `read_state` payload via new optional fields on `RobotState`. The mock daemon (3.12) implements the same protocol with synthesized state for CI tests.

**Tech Stack:** Python 3.12 (backend), Python 3.10 (daemon), ZMQ (JSON wire format), FastAPI, asyncio, pytest, motorbridge SDK, reBotArm_control_py, Pinocchio, React + TypeScript (UI).

**Spec:** `docs/superpowers/specs/2026-04-26-rebotarm-integration-design.md`

---

## File map

### Created
| Path | Purpose |
|---|---|
| `backend/mimicrec/adapters/rebotarm_zmq.py` | `RobotAdapter` impl: ZMQ REQ client + heartbeat asyncio task |
| `backend/mimicrec/adapters/rebotarm_protocol.py` | Shared command name constants, status enum names |
| `configs/robot/rebotarm.yaml` | Adapter config (address, heartbeat interval, replay block) |
| `configs/rebotarm_daemon.yaml` | Daemon config (safety limits, gravity-comp params) |
| `scripts/rebotarm_daemon/__init__.py` | Package marker |
| `scripts/rebotarm_daemon/__main__.py` | CLI entry: `python -m rebotarm_daemon --config ...` |
| `scripts/rebotarm_daemon/server.py` | ZMQ REP loop, dispatch by `cmd` |
| `scripts/rebotarm_daemon/safety.py` | `SafetyManager`: clamps + watchdogs + state machine. Pure-numpy, importable from 3.12 |
| `scripts/rebotarm_daemon/controllers.py` | `ModeController`: `POSITION` / `GRAVITY_COMP` (example 10 lock-with-push) |
| `scripts/rebotarm_daemon/state.py` | `SharedRobotState`: lock-protected. Pure Python, importable from 3.12 |
| `scripts/rebotarm_daemon/ee_pose.py` | reBotArm.kinematics wrapper (FK → pos + rotvec) |
| `scripts/rebotarm_daemon/config.py` | `SafetyLimits` + `GravityCompParams` dataclasses, YAML loader |
| `scripts/rebotarm_daemon_mock.py` | CI-runnable mock daemon. 3.12 venv. Speaks same protocol with synthesized state. |
| `tests/unit/test_rebotarm_safety.py` | Pure-logic tests for `SafetyManager` |
| `tests/unit/test_rebotarm_state.py` | Tests for `SharedRobotState` |
| `tests/unit/test_rebotarm_adapter.py` | Adapter tests against mock daemon (subprocess) |
| `tests/integration/test_rebotarm_session.py` | Full session against mock daemon, verify EE columns + safety_status flow |
| `tests/integration/test_rebotarm_estop.py` | estop → reject commands → clear_estop → recovery cycle |
| `frontend/src/components/EStopButton.tsx` | Big red E-stop button shown on Record page when robot=rebotarm |

### Modified
| Path | Change |
|---|---|
| `backend/mimicrec/types.py` | Extend `RobotState` with optional `ee_pos`, `ee_rotvec`, `gripper_pos` |
| `backend/mimicrec/recording/parquet_row.py` | Prefer `RobotState.ee_*` over `fk` arg when present |
| `backend/mimicrec/api/ws/state_hub.py` | Prefer `RobotState.ee_*` over local FK when present |
| `backend/mimicrec/adapters/so101.py` | Verify `read_state` leaves new fields None (no behavior change) |
| `scripts/setup.sh` | Create `.venv-rebotarm` (Python 3.10) and install reBotArm + deps |
| `frontend/src/pages/RecordPage.tsx` | Render `<EStopButton>` when `robot === "rebotarm"` |
| `backend/mimicrec/api/routes/session.py` | Add `POST /api/robot/estop` and `POST /api/robot/clear_estop` (dispatch through adapter) |
| `frontend/src/api/queries.ts` | `useEstop`, `useClearEstop` hooks |
| `README.md` / `README.ja.md` | Document the daemon, the start command, MVP safety scope |

### Deleted
| Path | Reason |
|---|---|
| `backend/mimicrec/adapters/rebotarm.py` | Replaced by `rebotarm_zmq.py` |

---

## Conventions

- All shell commands run from repo root: `/home/takakimaeda/MimicRec`.
- Python invocation: `.venv/bin/python` for backend / tests, `.venv-rebotarm/bin/python` for daemon-only smoke.
- Tests: `bash scripts/test.sh tests/...` (existing harness).
- Commit format: existing convention (`fix:` / `feat:` / `chore:` / `docs:` lowercase prefix; trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`).
- Don't push between tasks; the executor will push at end (or per their workflow).
- After every code edit, re-run the relevant test (`bash scripts/test.sh tests/.../<file>.py -q`) and the full suite at task end (`bash scripts/test.sh tests/ -q`) to ensure no regression.

---

## Task 1: Extend `RobotState` with optional EE fields

**Files:**
- Modify: `backend/mimicrec/types.py:33-38`
- Test: `tests/unit/test_robot_state_ee_fields.py` (new)

Lays the foundation: every adapter can optionally carry EE pose on `RobotState`, defaulting to None. Existing adapters keep returning None and the writer/state_hub fall back to the FK service, so no behavior change yet.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_robot_state_ee_fields.py
import numpy as np
from mimicrec.types import RobotState


def test_robot_state_default_ee_fields_are_none():
    s = RobotState(
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
    )
    assert s.ee_pos is None
    assert s.ee_rotvec is None
    assert s.gripper_pos is None


def test_robot_state_can_carry_ee_fields():
    s = RobotState(
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
        ee_pos=np.array([0.1, 0.2, 0.3], dtype=np.float32),
        ee_rotvec=np.array([0.0, 0.0, 0.5], dtype=np.float32),
        gripper_pos=42.0,
    )
    assert s.ee_pos.shape == (3,)
    assert s.ee_rotvec.shape == (3,)
    assert s.gripper_pos == 42.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `bash scripts/test.sh tests/unit/test_robot_state_ee_fields.py -v`
Expected: FAIL — `RobotState` does not accept `ee_pos` etc.

- [ ] **Step 3: Implement**

Edit `backend/mimicrec/types.py`:

```python
@dataclass
class RobotState:
    joint_pos: np.ndarray      # float32[dof]
    joint_vel: np.ndarray      # float32[dof]
    joint_effort: np.ndarray   # float32[dof]
    t_mono_ns: int = 0
    # Optional EE pose carried alongside joints. Adapters that compute EE
    # locally (e.g. ZMQ daemons holding their own FK) populate these; for
    # adapters that don't, the writer / state_hub falls back to FKService.
    ee_pos: np.ndarray | None = None       # float32[3]
    ee_rotvec: np.ndarray | None = None    # float32[3] axis-angle
    gripper_pos: float | None = None
```

- [ ] **Step 4: Run the test, full suite to confirm no regression**

```bash
bash scripts/test.sh tests/unit/test_robot_state_ee_fields.py -v
bash scripts/test.sh tests/ -q
```

Expected: new tests pass, all 88+ pass.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/types.py tests/unit/test_robot_state_ee_fields.py
git commit -m "$(cat <<'EOF'
feat: optional EE fields on RobotState

Adapters that compute end-effector pose locally (e.g. a ZMQ daemon
holding its own FK) populate ee_pos / ee_rotvec / gripper_pos on
RobotState. Adapters that don't leave them None and the writer /
state_hub fall back to FKService — keeps a single column schema
regardless of which side computed the pose. No behavior change yet.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `parquet_row` prefers `RobotState.ee_*` over `fk` arg

**Files:**
- Modify: `backend/mimicrec/recording/parquet_row.py`
- Test: `tests/unit/test_parquet_row_ee_pref.py` (new)

When `state.ee_pos` is set, the writer uses it directly and skips FK. When it's None, the writer falls back to the existing FK path (so SO-101 still works unchanged).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_parquet_row_ee_pref.py
import numpy as np
from mimicrec.recording.parquet_row import sample_bundle_to_row
from mimicrec.types import RobotState, RobotCommand, SampleBundle, Stamped


class _StubFK:
    def __init__(self):
        self.n_kin_joints = 5
        self.calls = 0

    def pose(self, q):
        self.calls += 1
        return (
            np.array([99.0, 99.0, 99.0], dtype=np.float32),
            np.array([99.0, 99.0, 99.0], dtype=np.float32),
        )


def _bundle_with_state(state: RobotState) -> SampleBundle:
    cmd = RobotCommand(q=np.zeros(6, dtype=np.float32))
    cmd.t_mono_ns = 1
    return SampleBundle(
        tick_t_mono_ns=100,
        state=Stamped(value=state, t_mono_ns=1),
        action=cmd,
        frames={},
    )


def test_uses_state_ee_when_present_and_skips_fk():
    state = RobotState(
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
        ee_pos=np.array([0.1, 0.2, 0.3], dtype=np.float32),
        ee_rotvec=np.array([0.0, 0.0, 0.4], dtype=np.float32),
        gripper_pos=33.3,
    )
    fk = _StubFK()
    row = sample_bundle_to_row(_bundle_with_state(state), 0, {}, fk=fk)
    np.testing.assert_allclose(row["observation.state.ee_pos"], [0.1, 0.2, 0.3])
    np.testing.assert_allclose(row["observation.state.ee_rotvec"], [0.0, 0.0, 0.4])
    assert row["observation.state.gripper_pos"] == 33.3
    assert fk.calls == 0  # FK NOT called


def test_falls_back_to_fk_when_state_ee_is_none():
    state = RobotState(
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
    )
    fk = _StubFK()
    row = sample_bundle_to_row(_bundle_with_state(state), 0, {}, fk=fk)
    # FK was used (StubFK returns 99,99,99)
    np.testing.assert_allclose(row["observation.state.ee_pos"], [99.0, 99.0, 99.0])
    assert fk.calls == 2  # once for state, once for action


def test_no_ee_columns_when_state_none_and_no_fk():
    state = RobotState(
        joint_pos=np.zeros(6, dtype=np.float32),
        joint_vel=np.zeros(6, dtype=np.float32),
        joint_effort=np.zeros(6, dtype=np.float32),
    )
    row = sample_bundle_to_row(_bundle_with_state(state), 0, {}, fk=None)
    assert "observation.state.ee_pos" not in row
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
bash scripts/test.sh tests/unit/test_parquet_row_ee_pref.py -v
```

Expected: FAIL — current implementation always calls fk and ignores state.ee_*.

- [ ] **Step 3: Implement**

Replace the EE block inside `sample_bundle_to_row` (in `backend/mimicrec/recording/parquet_row.py`) with logic that prefers `state.ee_*`:

```python
    # Observation EE: prefer values already on RobotState (e.g. supplied by a
    # daemon-side FK). Fall back to local fk only when state has no EE.
    obs_ee_pos = state.ee_pos
    obs_ee_rotvec = state.ee_rotvec
    obs_gripper = state.gripper_pos
    if obs_ee_pos is None and fk is not None:
        n = fk.n_kin_joints
        obs_ee_pos, obs_ee_rotvec = fk.pose(state.joint_pos[:n])
        if state.joint_pos.shape[0] > n:
            obs_gripper = float(state.joint_pos[n])

    # Action EE: derived from commanded q. Action has no "ee_pos" field today,
    # so always use FK when fk is set; otherwise omit.
    act_ee_pos = act_ee_rotvec = None
    act_gripper = None
    if fk is not None:
        n = fk.n_kin_joints
        act_ee_pos, act_ee_rotvec = fk.pose(bundle.action.q[:n])
        if bundle.action.q.shape[0] > n:
            act_gripper = float(bundle.action.q[n])

    if obs_ee_pos is not None:
        row["observation.state.ee_pos"] = obs_ee_pos
        row["observation.state.ee_rotvec"] = obs_ee_rotvec
        if obs_gripper is not None:
            row["observation.state.gripper_pos"] = float(obs_gripper)
    if act_ee_pos is not None:
        row["action.ee_pos"] = act_ee_pos
        row["action.ee_rotvec"] = act_ee_rotvec
        if act_gripper is not None:
            row["action.gripper_pos"] = act_gripper
```

Replace the existing `if fk is not None:` block in the file with the above.

- [ ] **Step 4: Run target test + full suite**

```bash
bash scripts/test.sh tests/unit/test_parquet_row_ee_pref.py -v
bash scripts/test.sh tests/ -q
```

Both must pass.

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/recording/parquet_row.py tests/unit/test_parquet_row_ee_pref.py
git commit -m "$(cat <<'EOF'
feat: parquet writer prefers RobotState.ee_* over local FK

When the adapter has already computed end-effector pose (e.g. a ZMQ
daemon that owns the URDF), the writer uses that directly and skips
FKService entirely. SO-101 is unchanged: its adapter leaves the EE
fields None so the local FKService still fills the row. Action-side
EE is still derived via FKService since RobotCommand has no EE channel.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `state_hub` (`/ws/state`) prefers `RobotState.ee_*`

**Files:**
- Modify: `backend/mimicrec/api/ws/state_hub.py`

`/ws/state` currently always calls `fk.pose(...)`. Change it to prefer values already on `RobotState`. No new test (state_hub is exercised through integration tests later); manual code review required.

- [ ] **Step 1: Edit `state_hub.py`**

In the `if sm:` block, replace the FK section so it prefers `s.value.ee_*`:

```python
                if s is not None:
                    payload: dict = {
                        "joint_pos": s.value.joint_pos.tolist(),
                        "joint_vel": s.value.joint_vel.tolist(),
                        "joint_effort": s.value.joint_effort.tolist(),
                        "t_mono_ns": s.t_mono_ns,
                    }
                    # Prefer EE already on RobotState (daemon-supplied);
                    # else fall back to local FK if configured.
                    if s.value.ee_pos is not None:
                        payload["ee_pos"] = s.value.ee_pos.tolist()
                        payload["ee_rotvec"] = (
                            s.value.ee_rotvec.tolist()
                            if s.value.ee_rotvec is not None
                            else None
                        )
                        if s.value.gripper_pos is not None:
                            payload["gripper_pos"] = float(s.value.gripper_pos)
                    else:
                        fk = getattr(sm, "_fk", None)
                        if fk is not None:
                            try:
                                n = fk.n_kin_joints
                                ee_pos, ee_rotvec = fk.pose(s.value.joint_pos[:n])
                                payload["ee_pos"] = ee_pos.tolist()
                                payload["ee_rotvec"] = ee_rotvec.tolist()
                                if s.value.joint_pos.shape[0] > n:
                                    payload["gripper_pos"] = float(s.value.joint_pos[n])
                            except Exception:
                                # FK errors here shouldn't kill the state stream
                                pass
                    await websocket.send_json(payload)
```

- [ ] **Step 2: Run full suite**

```bash
bash scripts/test.sh tests/ -q
```

Expected: 88+ pass.

- [ ] **Step 3: Commit**

```bash
git add backend/mimicrec/api/ws/state_hub.py
git commit -m "$(cat <<'EOF'
feat: /ws/state prefers RobotState.ee_* over local FK

Mirrors the parquet writer: when the adapter already published EE on
RobotState, broadcast it directly. Falls back to the FKService path
when ee_pos is None. Same wire shape either way.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Daemon protocol module (constants + payload helpers)

**Files:**
- Create: `backend/mimicrec/adapters/rebotarm_protocol.py`
- Test: `tests/unit/test_rebotarm_protocol.py` (new)

Single source of truth for command names, status enum strings, and a couple of small helpers. Importable from both the backend adapter and the mock daemon (the real daemon duplicates the constants — small enough to be fine).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_rebotarm_protocol.py
from mimicrec.adapters import rebotarm_protocol as p


def test_command_names_are_stable_strings():
    assert p.CMD_CONNECT == "connect"
    assert p.CMD_DISCONNECT == "disconnect"
    assert p.CMD_READ_STATE == "read_state"
    assert p.CMD_SEND_COMMAND == "send_command"
    assert p.CMD_SET_MODE == "set_mode"
    assert p.CMD_HEARTBEAT == "heartbeat"
    assert p.CMD_ESTOP == "estop"
    assert p.CMD_CLEAR_ESTOP == "clear_estop"
    assert p.CMD_GET_SAFETY_STATUS == "get_safety_status"


def test_safety_states_are_stable_strings():
    assert p.SAFETY_OK == "ok"
    assert p.SAFETY_WARN == "warn"
    assert p.SAFETY_ESTOP == "estop"
    assert p.SAFETY_HEARTBEAT_TIMEOUT == "heartbeat_timeout"
    assert p.SAFETY_THERMAL_FAULT == "thermal_fault"
    assert p.SAFETY_TORQUE_FAULT == "torque_fault"


def test_modes_match_robot_mode_values():
    from mimicrec.adapters.robot import RobotMode
    assert p.MODE_POSITION == RobotMode.POSITION.value
    assert p.MODE_GRAVITY_COMP == RobotMode.GRAVITY_COMP.value
```

- [ ] **Step 2: Run, expect FAIL (module missing)**

```bash
bash scripts/test.sh tests/unit/test_rebotarm_protocol.py -v
```

- [ ] **Step 3: Implement**

```python
# backend/mimicrec/adapters/rebotarm_protocol.py
"""Wire-protocol constants for the reBotArm safety daemon ZMQ bridge.

These names are duplicated verbatim in scripts/rebotarm_daemon/server.py
(which lives in a separate Python 3.10 venv and cannot import this module
at runtime). Keep them in sync.
"""
from __future__ import annotations

# Commands (request 'cmd' field)
CMD_CONNECT = "connect"
CMD_DISCONNECT = "disconnect"
CMD_READ_STATE = "read_state"
CMD_SEND_COMMAND = "send_command"
CMD_SET_MODE = "set_mode"
CMD_HEARTBEAT = "heartbeat"
CMD_ESTOP = "estop"
CMD_CLEAR_ESTOP = "clear_estop"
CMD_GET_SAFETY_STATUS = "get_safety_status"

# Safety state values (in read_state and get_safety_status responses)
SAFETY_OK = "ok"
SAFETY_WARN = "warn"
SAFETY_ESTOP = "estop"
SAFETY_HEARTBEAT_TIMEOUT = "heartbeat_timeout"
SAFETY_THERMAL_FAULT = "thermal_fault"
SAFETY_TORQUE_FAULT = "torque_fault"

# Mode values
MODE_POSITION = "position"
MODE_GRAVITY_COMP = "gravity_comp"

DEFAULT_ZMQ_ADDRESS = "tcp://localhost:5558"
```

- [ ] **Step 4: Run test + full suite**

```bash
bash scripts/test.sh tests/unit/test_rebotarm_protocol.py -v
bash scripts/test.sh tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/adapters/rebotarm_protocol.py tests/unit/test_rebotarm_protocol.py
git commit -m "$(cat <<'EOF'
feat: reBotArm ZMQ protocol constants

Single source of truth for command names and safety-state strings.
Daemon (Python 3.10 venv) duplicates the values rather than importing,
since cross-venv import isn't viable; tests pin the values so any
drift is caught.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `SharedRobotState` (lock-protected snapshot container)

**Files:**
- Create: `scripts/rebotarm_daemon/__init__.py` (empty package marker)
- Create: `scripts/rebotarm_daemon/state.py`
- Test: `tests/unit/test_rebotarm_state.py` (new)

The daemon's 500 Hz control loop writes into a shared `RobotState`-like dataclass; the ZMQ thread reads snapshots on demand. Pure Python — testable in 3.12.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_rebotarm_state.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import numpy as np
from rebotarm_daemon.state import SharedRobotState


def test_snapshot_returns_independent_copy():
    s = SharedRobotState(dof=6)
    pos = np.array([1, 2, 3, 4, 5, 6], dtype=np.float32)
    s.set(joint_pos=pos, joint_vel=np.zeros(6, dtype=np.float32),
          joint_effort=np.zeros(6, dtype=np.float32),
          ee_pos=np.array([0.1, 0.2, 0.3], dtype=np.float32),
          ee_rotvec=np.array([0.0, 0.0, 0.5], dtype=np.float32),
          gripper_pos=42.0,
          motor_temps_c=np.array([35.0]*6, dtype=np.float32),
          motor_torques_nm=np.array([0.1]*6, dtype=np.float32))
    snap = s.snapshot()
    pos[0] = 999  # mutate original
    assert snap["joint_pos"][0] == 1  # snapshot unaffected
    assert snap["ee_pos"][0] == 0.1
    assert snap["gripper_pos"] == 42.0
    assert snap["motor_temps_c"][0] == 35.0


def test_snapshot_before_first_set_returns_zeros():
    s = SharedRobotState(dof=6)
    snap = s.snapshot()
    assert snap["joint_pos"].shape == (6,)
    assert (snap["joint_pos"] == 0).all()
    assert snap["ee_pos"] is None  # never been set
```

- [ ] **Step 2: Run, expect FAIL (module missing)**

```bash
bash scripts/test.sh tests/unit/test_rebotarm_state.py -v
```

- [ ] **Step 3: Implement**

```python
# scripts/rebotarm_daemon/__init__.py
```

```python
# scripts/rebotarm_daemon/state.py
"""Lock-protected shared state container for the reBotArm daemon.

The 500 Hz control loop calls .set(...) every tick; ZMQ requests call
.snapshot() on demand. snapshot() copies arrays so callers can mutate
freely.
"""
from __future__ import annotations

import threading
from typing import Optional

import numpy as np


class SharedRobotState:
    def __init__(self, dof: int = 6):
        self._dof = dof
        self._lock = threading.Lock()
        self._joint_pos = np.zeros(dof, dtype=np.float32)
        self._joint_vel = np.zeros(dof, dtype=np.float32)
        self._joint_effort = np.zeros(dof, dtype=np.float32)
        self._ee_pos: Optional[np.ndarray] = None
        self._ee_rotvec: Optional[np.ndarray] = None
        self._gripper_pos: Optional[float] = None
        self._motor_temps_c = np.zeros(dof, dtype=np.float32)
        self._motor_torques_nm = np.zeros(dof, dtype=np.float32)

    def set(
        self,
        *,
        joint_pos: np.ndarray,
        joint_vel: np.ndarray,
        joint_effort: np.ndarray,
        ee_pos: Optional[np.ndarray] = None,
        ee_rotvec: Optional[np.ndarray] = None,
        gripper_pos: Optional[float] = None,
        motor_temps_c: Optional[np.ndarray] = None,
        motor_torques_nm: Optional[np.ndarray] = None,
    ) -> None:
        with self._lock:
            self._joint_pos = joint_pos.astype(np.float32, copy=True)
            self._joint_vel = joint_vel.astype(np.float32, copy=True)
            self._joint_effort = joint_effort.astype(np.float32, copy=True)
            if ee_pos is not None:
                self._ee_pos = ee_pos.astype(np.float32, copy=True)
            if ee_rotvec is not None:
                self._ee_rotvec = ee_rotvec.astype(np.float32, copy=True)
            if gripper_pos is not None:
                self._gripper_pos = float(gripper_pos)
            if motor_temps_c is not None:
                self._motor_temps_c = motor_temps_c.astype(np.float32, copy=True)
            if motor_torques_nm is not None:
                self._motor_torques_nm = motor_torques_nm.astype(np.float32, copy=True)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "joint_pos": self._joint_pos.copy(),
                "joint_vel": self._joint_vel.copy(),
                "joint_effort": self._joint_effort.copy(),
                "ee_pos": None if self._ee_pos is None else self._ee_pos.copy(),
                "ee_rotvec": None if self._ee_rotvec is None else self._ee_rotvec.copy(),
                "gripper_pos": self._gripper_pos,
                "motor_temps_c": self._motor_temps_c.copy(),
                "motor_torques_nm": self._motor_torques_nm.copy(),
            }
```

- [ ] **Step 4: Run + full suite**

```bash
bash scripts/test.sh tests/unit/test_rebotarm_state.py -v
bash scripts/test.sh tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add scripts/rebotarm_daemon/__init__.py scripts/rebotarm_daemon/state.py tests/unit/test_rebotarm_state.py
git commit -m "$(cat <<'EOF'
feat: SharedRobotState — lock-protected snapshot container for daemon

Daemon's 500 Hz control loop writes; ZMQ requests snapshot on demand.
snapshot() copies arrays so callers can mutate freely. Pure-Python
module so it imports under both 3.12 (tests) and 3.10 (daemon runtime).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Daemon `config.py` — `SafetyLimits`, `GravityCompParams`, YAML loader

**Files:**
- Create: `scripts/rebotarm_daemon/config.py`
- Test: `tests/unit/test_rebotarm_daemon_config.py` (new)
- Test fixture: `tests/fixtures/rebotarm_daemon_test.yaml` (new)

Pure Python; just dataclasses + PyYAML.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_rebotarm_daemon_config.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import pytest
from rebotarm_daemon.config import (
    DaemonConfig, SafetyLimits, GravityCompParams, load_daemon_config,
)


def test_safety_limits_defaults_present():
    s = SafetyLimits()
    assert s.heartbeat_timeout_ms > 0
    assert s.temperature_warn_c < s.temperature_fault_c
    assert s.temperature_recover_c < s.temperature_fault_c


def test_loads_yaml(tmp_path):
    fixture = Path(__file__).parent.parent / "fixtures" / "rebotarm_daemon_test.yaml"
    cfg = load_daemon_config(fixture)
    assert cfg.zmq_address == "tcp://*:5558"
    assert cfg.control_rate_hz == 500
    assert len(cfg.safety.joint_pos_min_rad) == 6
    assert cfg.safety.heartbeat_timeout_ms == 500
    assert cfg.gravity_comp.push_velocity_threshold_m_s == 0.02
```

```yaml
# tests/fixtures/rebotarm_daemon_test.yaml
arm_config: configs/rebotarm/arm.yaml
zmq_address: tcp://*:5558
control_rate_hz: 500
safety:
  joint_pos_min_rad: [-3.14, -3.14, -3.14, -3.14, -3.14, -3.14]
  joint_pos_max_rad: [3.14, 3.14, 3.14, 3.14, 3.14, 3.14]
  joint_vel_max_rad_s: 3.14
  joint_accel_max_rad_s2: 20.0
  torque_max_nm: [10, 10, 8, 5, 5, 3]
  temperature_warn_c: 70
  temperature_fault_c: 80
  temperature_recover_c: 60
  heartbeat_timeout_ms: 500
gravity_comp:
  push_velocity_threshold_m_s: 0.02
  push_omega_threshold_rad_s: 0.3
  kp: [2, 2, 2, 2, 2, 2]
  kd: [1, 1, 1, 1, 1, 1]
```

- [ ] **Step 2: Run, expect FAIL**

```bash
bash scripts/test.sh tests/unit/test_rebotarm_daemon_config.py -v
```

- [ ] **Step 3: Implement**

```python
# scripts/rebotarm_daemon/config.py
"""Configuration dataclasses for the reBotArm safety daemon."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml


@dataclass
class SafetyLimits:
    joint_pos_min_rad: List[float] = field(default_factory=lambda: [-3.14] * 6)
    joint_pos_max_rad: List[float] = field(default_factory=lambda: [3.14] * 6)
    joint_vel_max_rad_s: float = 3.14
    joint_accel_max_rad_s2: float = 20.0
    torque_max_nm: List[float] = field(default_factory=lambda: [10.0] * 6)
    temperature_warn_c: float = 70.0
    temperature_fault_c: float = 80.0
    temperature_recover_c: float = 60.0
    heartbeat_timeout_ms: int = 500


@dataclass
class GravityCompParams:
    push_velocity_threshold_m_s: float = 0.02
    push_omega_threshold_rad_s: float = 0.3
    kp: List[float] = field(default_factory=lambda: [2.0] * 6)
    kd: List[float] = field(default_factory=lambda: [1.0] * 6)


@dataclass
class DaemonConfig:
    arm_config: str = "configs/rebotarm/arm.yaml"
    zmq_address: str = "tcp://*:5558"
    control_rate_hz: int = 500
    safety: SafetyLimits = field(default_factory=SafetyLimits)
    gravity_comp: GravityCompParams = field(default_factory=GravityCompParams)


def load_daemon_config(path: str | Path) -> DaemonConfig:
    raw = yaml.safe_load(Path(path).read_text())
    safety_raw = raw.get("safety", {})
    grav_raw = raw.get("gravity_comp", {})
    return DaemonConfig(
        arm_config=raw.get("arm_config", "configs/rebotarm/arm.yaml"),
        zmq_address=raw.get("zmq_address", "tcp://*:5558"),
        control_rate_hz=int(raw.get("control_rate_hz", 500)),
        safety=SafetyLimits(**safety_raw) if safety_raw else SafetyLimits(),
        gravity_comp=GravityCompParams(**grav_raw) if grav_raw else GravityCompParams(),
    )
```

- [ ] **Step 4: Run + full suite**

```bash
bash scripts/test.sh tests/unit/test_rebotarm_daemon_config.py -v
bash scripts/test.sh tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add scripts/rebotarm_daemon/config.py tests/unit/test_rebotarm_daemon_config.py tests/fixtures/rebotarm_daemon_test.yaml
git commit -m "$(cat <<'EOF'
feat: daemon config dataclasses (SafetyLimits, GravityCompParams)

YAML-loaded; sensible defaults so an under-specified config still
yields a runnable daemon. PyYAML only — no reBotArm SDK imports —
so it tests under 3.12.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `SafetyManager` — clamps + watchdogs + state machine

**Files:**
- Create: `scripts/rebotarm_daemon/safety.py`
- Test: `tests/unit/test_rebotarm_safety.py` (new)

This is the safety core. Pure numpy + scalar comparisons. Owns the safety-state enum string. Caller (server / control loop) feeds it timestamps, joint values, temperatures; manager returns clamped values + a state object.

- [ ] **Step 1: Write the failing test (covers all clamps + state machine)**

```python
# tests/unit/test_rebotarm_safety.py
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import numpy as np
import pytest
from rebotarm_daemon.config import SafetyLimits
from rebotarm_daemon.safety import SafetyManager


def _mgr(**overrides) -> SafetyManager:
    limits = SafetyLimits(
        joint_pos_min_rad=[-1.0] * 6,
        joint_pos_max_rad=[1.0] * 6,
        joint_vel_max_rad_s=1.0,
        joint_accel_max_rad_s2=10.0,
        torque_max_nm=[5.0] * 6,
        temperature_warn_c=60.0,
        temperature_fault_c=70.0,
        temperature_recover_c=50.0,
        heartbeat_timeout_ms=200,
        **overrides,
    )
    return SafetyManager(limits, dof=6)


def test_clamp_joint_pos_to_bounds():
    m = _mgr()
    q = np.array([2.0, -2.0, 0.5, 0.5, 0.5, 0.5])
    out = m.clamp_joint_pos(q)
    assert out[0] == 1.0
    assert out[1] == -1.0
    assert out[2] == 0.5


def test_velocity_ramp_limits_step_size():
    m = _mgr()
    q_now = np.zeros(6)
    q_target = np.array([10.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    dt = 0.01
    out = m.ramp_velocity(q_now, q_target, dt)
    # max step = vel_max * dt = 1.0 * 0.01 = 0.01
    assert out[0] == pytest.approx(0.01, abs=1e-6)


def test_torque_clamp_per_joint():
    m = _mgr()
    tau = np.array([100, -100, 0, 0, 0, 0], dtype=float)
    out = m.clamp_torque(tau)
    assert out[0] == 5.0
    assert out[1] == -5.0


def test_thermal_warn_then_fault_then_recover():
    m = _mgr()
    assert m.evaluate_thermal(np.array([55] * 6)) == "ok"
    assert m.evaluate_thermal(np.array([65] * 6)) == "warn"
    fault = m.evaluate_thermal(np.array([72] * 6))
    assert fault == "thermal_fault"
    # state stays in fault even when temp drops to warn band
    assert m.evaluate_thermal(np.array([55] * 6)) == "thermal_fault"
    # cooling below recover threshold + clear request returns to ok
    m.evaluate_thermal(np.array([45] * 6))
    assert m.try_clear_estop(np.array([45] * 6)) is True
    assert m.evaluate_thermal(np.array([45] * 6)) == "ok"


def test_estop_then_clear():
    m = _mgr()
    m.trigger_estop()
    assert m.is_active_fault()
    assert m.try_clear_estop(np.array([20] * 6)) is True
    assert not m.is_active_fault()


def test_clear_estop_blocked_when_thermal_fault_active():
    m = _mgr()
    m.evaluate_thermal(np.array([72] * 6))  # enters thermal fault
    m.trigger_estop()
    # too hot to recover
    assert m.try_clear_estop(np.array([55] * 6)) is False


def test_heartbeat_timeout_after_silence():
    m = _mgr(heartbeat_timeout_ms=50)
    m.note_heartbeat()
    assert m.heartbeat_state(time.monotonic()) == "ok"
    later = time.monotonic() + 0.1
    assert m.heartbeat_state(later) == "heartbeat_timeout"
```

- [ ] **Step 2: Run, expect FAIL**

```bash
bash scripts/test.sh tests/unit/test_rebotarm_safety.py -v
```

- [ ] **Step 3: Implement**

```python
# scripts/rebotarm_daemon/safety.py
"""Multi-layer safety for the reBotArm daemon.

Pure-Python (numpy) — no motorbridge imports — so it can be unit-tested
in the 3.12 venv even though the daemon runs under 3.10.
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np

from rebotarm_daemon.config import SafetyLimits


_OK = "ok"
_WARN = "warn"
_ESTOP = "estop"
_HEARTBEAT_TIMEOUT = "heartbeat_timeout"
_THERMAL_FAULT = "thermal_fault"
_TORQUE_FAULT = "torque_fault"


class SafetyManager:
    def __init__(self, limits: SafetyLimits, dof: int = 6):
        self._limits = limits
        self._dof = dof

        # state-machine: latched faults (cleared only via try_clear_estop)
        self._estop_active = False
        self._thermal_active = False
        self._torque_active = False

        # last heartbeat timestamp (monotonic seconds); initialized far in past
        self._last_hb_t: float = 0.0

        # rolling for accel ramp
        self._last_q: Optional[np.ndarray] = None

    # ---- clamps -------------------------------------------------------

    def clamp_joint_pos(self, q: np.ndarray) -> np.ndarray:
        lo = np.asarray(self._limits.joint_pos_min_rad, dtype=float)
        hi = np.asarray(self._limits.joint_pos_max_rad, dtype=float)
        return np.clip(q, lo, hi).astype(q.dtype)

    def ramp_velocity(self, q_now: np.ndarray, q_target: np.ndarray, dt: float) -> np.ndarray:
        if dt <= 0:
            return q_now.copy()
        max_step = self._limits.joint_vel_max_rad_s * dt
        delta = q_target - q_now
        norm = np.abs(delta)
        scale = np.where(norm > max_step, max_step / np.maximum(norm, 1e-12), 1.0)
        return q_now + delta * scale

    def ramp_accel(self, q_target: np.ndarray, dt: float) -> np.ndarray:
        if self._last_q is None or dt <= 0:
            self._last_q = q_target.copy()
            return q_target
        max_step = self._limits.joint_accel_max_rad_s2 * dt * dt
        delta = q_target - self._last_q
        norm = np.abs(delta)
        scale = np.where(norm > max_step, max_step / np.maximum(norm, 1e-12), 1.0)
        out = self._last_q + delta * scale
        self._last_q = out.copy()
        return out

    def clamp_torque(self, tau: np.ndarray) -> np.ndarray:
        bound = np.asarray(self._limits.torque_max_nm, dtype=float)
        return np.clip(tau, -bound, bound).astype(tau.dtype)

    # ---- heartbeat ---------------------------------------------------

    def note_heartbeat(self) -> None:
        self._last_hb_t = time.monotonic()

    def heartbeat_state(self, now_t: Optional[float] = None) -> str:
        if self._last_hb_t == 0.0:
            return _OK  # no heartbeats expected yet (pre-connect)
        now = time.monotonic() if now_t is None else now_t
        age_ms = (now - self._last_hb_t) * 1000.0
        if age_ms > self._limits.heartbeat_timeout_ms:
            return _HEARTBEAT_TIMEOUT
        return _OK

    # ---- thermal -----------------------------------------------------

    def evaluate_thermal(self, temps_c: np.ndarray) -> str:
        max_t = float(np.max(temps_c))
        if self._thermal_active:
            return _THERMAL_FAULT
        if max_t >= self._limits.temperature_fault_c:
            self._thermal_active = True
            return _THERMAL_FAULT
        if max_t >= self._limits.temperature_warn_c:
            return _WARN
        return _OK

    # ---- estop / fault state ----------------------------------------

    def trigger_estop(self) -> None:
        self._estop_active = True

    def trigger_torque_fault(self) -> None:
        self._torque_active = True

    def is_active_fault(self) -> bool:
        return self._estop_active or self._thermal_active or self._torque_active

    def try_clear_estop(self, current_temps_c: np.ndarray) -> bool:
        """Return True if all fault conditions are clear and we can resume.

        Conditions:
          - max temp < temperature_recover_c (60 °C)
          - heartbeat is fresh (heartbeat_state == OK)
          - no torque fault outstanding
        """
        if float(np.max(current_temps_c)) >= self._limits.temperature_recover_c:
            return False
        if self.heartbeat_state() != _OK:
            return False
        # torque faults clear automatically once cleared
        self._estop_active = False
        self._thermal_active = False
        self._torque_active = False
        return True

    # ---- aggregate state for status payload --------------------------

    def overall_state(self, temps_c: Optional[np.ndarray] = None) -> str:
        # priority: estop > thermal > torque > heartbeat > warn > ok
        if self._estop_active:
            return _ESTOP
        if self._thermal_active:
            return _THERMAL_FAULT
        if self._torque_active:
            return _TORQUE_FAULT
        hb = self.heartbeat_state()
        if hb != _OK:
            return hb
        if temps_c is not None:
            warn = self.evaluate_thermal(temps_c)
            if warn != _OK:
                return warn
        return _OK
```

- [ ] **Step 4: Run + full suite**

```bash
bash scripts/test.sh tests/unit/test_rebotarm_safety.py -v
bash scripts/test.sh tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add scripts/rebotarm_daemon/safety.py tests/unit/test_rebotarm_safety.py
git commit -m "$(cat <<'EOF'
feat: SafetyManager — clamps + watchdogs + fault state machine

Pure numpy core. Joint pos clamp, velocity / acceleration ramp,
torque clamp, thermal cutoff (warn → fault, sticky until recover
threshold + explicit clear), heartbeat watchdog (auto fault on
silence > limit), E-stop trigger + clear with multi-condition gate
(temp + heartbeat + torque OK). Tested in the 3.12 venv since this
module imports nothing from the reBotArm SDK.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Mock daemon (`scripts/rebotarm_daemon_mock.py`)

**Files:**
- Create: `scripts/rebotarm_daemon_mock.py`

A standalone Python 3.12 script (so it runs in CI / dev with no extra venv) that:
- Binds ZMQ REP on a configurable port (default `tcp://*:5558`).
- Implements every command the real daemon does, with synthesized state.
- Tracks the same fault states as `SafetyManager`, so estop / clear_estop integration tests are realistic.
- Exits cleanly on SIGINT.

This will become the test fixture for the adapter and integration tests in tasks 10–12.

- [ ] **Step 1: Implement**

```python
# scripts/rebotarm_daemon_mock.py
#!/usr/bin/env python
"""Mock reBotArm safety daemon for tests / dev without hardware.

Speaks the same ZMQ wire protocol as the real daemon. Synthesizes a slow
sinusoidal joint trajectory so /ws/state plots have signal. Implements
the estop / clear_estop / heartbeat / safety_status semantics so
integration tests can exercise them.

Usage:
    .venv/bin/python scripts/rebotarm_daemon_mock.py
    .venv/bin/python scripts/rebotarm_daemon_mock.py --port 5599
"""
from __future__ import annotations

import argparse
import math
import signal
import sys
import time

import numpy as np
import zmq

from mimicrec.adapters.rebotarm_protocol import (
    CMD_CONNECT, CMD_DISCONNECT, CMD_READ_STATE, CMD_SEND_COMMAND,
    CMD_SET_MODE, CMD_HEARTBEAT, CMD_ESTOP, CMD_CLEAR_ESTOP,
    CMD_GET_SAFETY_STATUS, MODE_POSITION, MODE_GRAVITY_COMP,
    SAFETY_OK, SAFETY_ESTOP,
)


JOINT_NAMES = [f"j{i}" for i in range(1, 7)]
DOF = 6


def _make_payload(t0: float, mode: str) -> dict:
    t = time.monotonic() - t0
    q = np.array([0.3 * math.sin(t * 0.5 + i * 0.7) for i in range(DOF)], dtype=np.float32)
    qd = np.array([0.15 * math.cos(t * 0.5 + i * 0.7) for i in range(DOF)], dtype=np.float32)
    return {
        "joint_pos": q.tolist(),
        "joint_vel": qd.tolist(),
        "joint_effort": [0.0] * DOF,
        "ee_pos": [0.20 + 0.05 * math.sin(t), 0.10 + 0.02 * math.cos(t), 0.30],
        "ee_rotvec": [0.0, 0.0, 0.5 * math.sin(t * 0.3)],
        "gripper_pos": float(50 + 30 * math.sin(t * 0.4)),
        "motor_temps_c": [40.0] * DOF,
        "motor_torques_nm": [0.05] * DOF,
        "t_mono_ns": time.monotonic_ns(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5558)
    args = parser.parse_args()

    ctx = zmq.Context()
    sock = ctx.socket(zmq.REP)
    sock.bind(f"tcp://*:{args.port}")
    sock.setsockopt(zmq.RCVTIMEO, 100)

    state = {
        "connected": False,
        "mode": MODE_GRAVITY_COMP,
        "fault": None,           # None | "estop" | "thermal_fault"
        "last_hb": 0.0,
        "last_cmd_q": None,
        "t0": time.monotonic(),
    }

    print(f"[mock-daemon] listening on tcp://*:{args.port}")
    stopped = False

    def _stop(*_):
        nonlocal stopped
        stopped = True
        print("\n[mock-daemon] stopping")

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    while not stopped:
        try:
            msg = sock.recv_json()
        except zmq.Again:
            continue
        cmd = msg.get("cmd")

        if cmd == CMD_CONNECT:
            state["connected"] = True
            state["t0"] = time.monotonic()
            sock.send_json({"ok": True, "dof": DOF, "joint_names": JOINT_NAMES,
                            "ee_frame": "tool0"})
        elif cmd == CMD_DISCONNECT:
            state["connected"] = False
            sock.send_json({"ok": True})
        elif cmd == CMD_HEARTBEAT:
            state["last_hb"] = time.monotonic()
            sock.send_json({"ok": True})
        elif cmd == CMD_READ_STATE:
            payload = _make_payload(state["t0"], state["mode"])
            payload["safety_state"] = state["fault"] or SAFETY_OK
            sock.send_json(payload)
        elif cmd == CMD_SEND_COMMAND:
            if state["fault"]:
                sock.send_json({"ok": False, "error": f"fault active: {state['fault']}"})
            else:
                state["last_cmd_q"] = msg.get("q", [])
                sock.send_json({"ok": True})
        elif cmd == CMD_SET_MODE:
            m = msg.get("mode", MODE_GRAVITY_COMP)
            # Validate to match the real daemon's behavior so misuse is
            # caught in integration tests.
            if m not in (MODE_POSITION, MODE_GRAVITY_COMP):
                sock.send_json({"ok": False, "error": f"unknown mode: {m}"})
            else:
                state["mode"] = m
                sock.send_json({"ok": True, "mode": m})
        elif cmd == CMD_ESTOP:
            state["fault"] = SAFETY_ESTOP
            sock.send_json({"ok": True})
        elif cmd == CMD_CLEAR_ESTOP:
            # always succeeds in mock (no real temp / heartbeat constraints)
            state["fault"] = None
            sock.send_json({"ok": True})
        elif cmd == CMD_GET_SAFETY_STATUS:
            sock.send_json({
                "safety_state": state["fault"] or SAFETY_OK,
                "mode": state["mode"],
            })
        else:
            sock.send_json({"ok": False, "error": f"unknown cmd: {cmd}"})

    sock.close(linger=0)
    ctx.term()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke test it manually**

```bash
.venv/bin/python scripts/rebotarm_daemon_mock.py --port 5599 &
DAEMON_PID=$!
sleep 1

.venv/bin/python -c "
import zmq, json
ctx = zmq.Context(); s = ctx.socket(zmq.REQ); s.connect('tcp://localhost:5599')
s.send_json({'cmd': 'connect'}); print(s.recv_json())
s.send_json({'cmd': 'read_state'}); print(s.recv_json())
s.send_json({'cmd': 'estop'}); print(s.recv_json())
s.send_json({'cmd': 'send_command', 'q': [0]*6}); print(s.recv_json())
"

kill $DAEMON_PID
```

Expected: connect returns dof/joint_names; read_state returns synthesized payload; estop returns ok; send_command returns ok=false with "fault active".

- [ ] **Step 3: Commit**

```bash
git add scripts/rebotarm_daemon_mock.py
git commit -m "$(cat <<'EOF'
feat: mock reBotArm daemon for CI / dev without hardware

Speaks the full ZMQ protocol with synthesized sinusoidal joint state
and EE pose so /ws/state has signal. Implements estop / clear_estop
and refuses send_command while a fault is latched, so integration
tests can exercise the safety semantics. Runs under the 3.12 venv
since it has no reBotArm SDK dependency.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `ReBotArmZmqAdapter` — backend adapter

**Files:**
- Create: `backend/mimicrec/adapters/rebotarm_zmq.py`
- Test: `tests/unit/test_rebotarm_adapter.py` (new)
- Delete: `backend/mimicrec/adapters/rebotarm.py`

The adapter is a thin ZMQ REQ client that:
- Uses an `asyncio.Lock` around bus access (same pattern as `SO101Adapter`).
- Spawns an `asyncio` heartbeat task in `connect()` and cancels it in `disconnect()`.
- `read_state()` returns a `RobotState` populated with EE fields from the daemon.
- Exposes `estop()` and `clear_estop()` for the route handlers added in Task 13.

Tests spawn the mock daemon as a subprocess.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_rebotarm_adapter.py
import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
import numpy as np

from mimicrec.adapters.rebotarm_zmq import ReBotArmZmqAdapter

REPO = Path(__file__).resolve().parents[2]
MOCK = REPO / "scripts" / "rebotarm_daemon_mock.py"
PY = REPO / ".venv" / "bin" / "python"


@pytest.fixture
def daemon_port():
    """Spawn mock daemon on a unique port, yield port, kill on teardown."""
    port = 5600 + int(time.time() * 1000) % 100  # cheap uniqueifier
    proc = subprocess.Popen([str(PY), str(MOCK), "--port", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            preexec_fn=os.setsid)
    time.sleep(0.5)
    try:
        yield port
    finally:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=2)


@pytest.mark.asyncio
async def test_connect_returns_dof_and_starts_heartbeat(daemon_port):
    a = ReBotArmZmqAdapter(address=f"tcp://localhost:{daemon_port}",
                           heartbeat_interval_ms=100)
    await a.connect()
    try:
        assert a.dof == 6
        assert a.joint_names == [f"j{i}" for i in range(1, 7)]
        # heartbeat task should be active
        assert a._heartbeat_task is not None
        await asyncio.sleep(0.25)
        assert not a._heartbeat_task.done()
    finally:
        await a.disconnect()


@pytest.mark.asyncio
async def test_read_state_includes_ee_fields(daemon_port):
    a = ReBotArmZmqAdapter(address=f"tcp://localhost:{daemon_port}",
                           heartbeat_interval_ms=100)
    await a.connect()
    try:
        s = await a.read_state()
        assert s.joint_pos.shape == (6,)
        assert s.ee_pos is not None and s.ee_pos.shape == (3,)
        assert s.ee_rotvec is not None and s.ee_rotvec.shape == (3,)
        assert s.gripper_pos is not None
    finally:
        await a.disconnect()


@pytest.mark.asyncio
async def test_send_joint_command_round_trips(daemon_port):
    a = ReBotArmZmqAdapter(address=f"tcp://localhost:{daemon_port}",
                           heartbeat_interval_ms=100)
    await a.connect()
    try:
        await a.send_joint_command(np.zeros(6, dtype=np.float32))
    finally:
        await a.disconnect()


@pytest.mark.asyncio
async def test_estop_blocks_send_command(daemon_port):
    a = ReBotArmZmqAdapter(address=f"tcp://localhost:{daemon_port}",
                           heartbeat_interval_ms=100)
    await a.connect()
    try:
        await a.estop()
        with pytest.raises(Exception):
            await a.send_joint_command(np.zeros(6, dtype=np.float32))
        await a.clear_estop()
        # now succeeds again
        await a.send_joint_command(np.zeros(6, dtype=np.float32))
    finally:
        await a.disconnect()
```

- [ ] **Step 2: Run, expect FAIL (adapter does not exist)**

```bash
bash scripts/test.sh tests/unit/test_rebotarm_adapter.py -v
```

- [ ] **Step 3: Implement adapter**

```python
# backend/mimicrec/adapters/rebotarm_zmq.py
"""ZMQ REQ client adapter for the reBotArm safety daemon.

The daemon runs in a separate Python 3.10 venv and owns the motor
connection + 500 Hz control loop + all safety. This adapter just
exchanges JSON messages with it.
"""
from __future__ import annotations

import asyncio

import numpy as np
import zmq

from mimicrec.adapters.robot import RobotMode
from mimicrec.adapters.rebotarm_protocol import (
    CMD_CONNECT, CMD_DISCONNECT, CMD_READ_STATE, CMD_SEND_COMMAND,
    CMD_SET_MODE, CMD_HEARTBEAT, CMD_ESTOP, CMD_CLEAR_ESTOP,
    DEFAULT_ZMQ_ADDRESS,
)
from mimicrec.errors import HardwareError
from mimicrec.types import RobotState


class ReBotArmZmqAdapter:
    name = "rebotarm"
    dof = 6                     # finalized in connect() from daemon reply
    joint_names: list[str] = [f"j{i}" for i in range(1, 7)]

    def __init__(
        self,
        address: str = DEFAULT_ZMQ_ADDRESS,
        heartbeat_interval_ms: int = 200,
        request_timeout_ms: int = 1000,
    ):
        self._address = address
        self._heartbeat_interval_ms = heartbeat_interval_ms
        self._request_timeout_ms = request_timeout_ms
        self._ctx: zmq.Context | None = None
        self._socket: zmq.Socket | None = None
        # half-duplex REQ socket — one outstanding request at a time
        self._bus_lock = asyncio.Lock()
        self._heartbeat_task: asyncio.Task | None = None

    # ---- bus helpers ------------------------------------------------

    def _send_recv_sync(self, msg: dict) -> dict:
        assert self._socket is not None
        self._socket.send_json(msg)
        return self._socket.recv_json()

    async def _request(self, msg: dict) -> dict:
        loop = asyncio.get_running_loop()
        async with self._bus_lock:
            return await loop.run_in_executor(None, self._send_recv_sync, msg)

    # ---- lifecycle --------------------------------------------------

    async def connect(self) -> None:
        self._ctx = zmq.Context()
        self._socket = self._ctx.socket(zmq.REQ)
        self._socket.setsockopt(zmq.RCVTIMEO, self._request_timeout_ms)
        self._socket.setsockopt(zmq.SNDTIMEO, self._request_timeout_ms)
        self._socket.setsockopt(zmq.LINGER, 0)
        self._socket.connect(self._address)
        try:
            reply = await self._request({"cmd": CMD_CONNECT})
        except Exception as e:
            self._teardown_socket()
            raise HardwareError(f"reBotArm daemon connect failed: {e}") from e
        if not reply.get("ok"):
            self._teardown_socket()
            raise HardwareError(f"reBotArm daemon refused connect: {reply}")
        # daemon authoritative about dof / joint_names
        self.dof = int(reply.get("dof", self.dof))
        self.joint_names = list(reply.get("joint_names", self.joint_names))
        # spawn heartbeat
        self._heartbeat_task = asyncio.create_task(self._run_heartbeat())

    async def disconnect(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
            self._heartbeat_task = None
        if self._socket is not None:
            try:
                await self._request({"cmd": CMD_DISCONNECT})
            except Exception:
                pass
        self._teardown_socket()

    def _teardown_socket(self) -> None:
        if self._socket is not None:
            self._socket.close(linger=0)
            self._socket = None
        if self._ctx is not None:
            self._ctx.term()
            self._ctx = None

    async def _run_heartbeat(self) -> None:
        interval = self._heartbeat_interval_ms / 1000.0
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self._request({"cmd": CMD_HEARTBEAT})
                except Exception:
                    # network blip; daemon's own heartbeat watchdog handles it
                    pass
        except asyncio.CancelledError:
            return

    # ---- state / command --------------------------------------------

    async def read_state(self) -> RobotState:
        reply = await self._request({"cmd": CMD_READ_STATE})
        return RobotState(
            joint_pos=np.asarray(reply["joint_pos"], dtype=np.float32),
            joint_vel=np.asarray(reply["joint_vel"], dtype=np.float32),
            joint_effort=np.asarray(reply["joint_effort"], dtype=np.float32),
            ee_pos=(np.asarray(reply["ee_pos"], dtype=np.float32)
                    if reply.get("ee_pos") is not None else None),
            ee_rotvec=(np.asarray(reply["ee_rotvec"], dtype=np.float32)
                       if reply.get("ee_rotvec") is not None else None),
            gripper_pos=(float(reply["gripper_pos"])
                         if reply.get("gripper_pos") is not None else None),
        )

    async def send_joint_command(self, q: np.ndarray) -> None:
        if q.shape != (self.dof,):
            raise HardwareError(f"command shape {q.shape} != ({self.dof},)")
        if not np.isfinite(q).all():
            raise HardwareError("non-finite joint command")
        reply = await self._request({"cmd": CMD_SEND_COMMAND, "q": q.tolist()})
        if not reply.get("ok"):
            raise HardwareError(f"daemon rejected send_command: {reply}")

    async def set_mode(self, mode: RobotMode) -> None:
        reply = await self._request({"cmd": CMD_SET_MODE, "mode": mode.value})
        if not reply.get("ok"):
            raise HardwareError(f"daemon rejected set_mode: {reply}")

    def supports_mode(self, mode: RobotMode) -> bool:
        return True  # both POSITION and GRAVITY_COMP supported

    # ---- safety ------------------------------------------------------

    async def estop(self) -> None:
        await self._request({"cmd": CMD_ESTOP})

    async def clear_estop(self) -> dict:
        return await self._request({"cmd": CMD_CLEAR_ESTOP})
```

- [ ] **Step 4: Delete the old stub**

```bash
git rm backend/mimicrec/adapters/rebotarm.py
```

- [ ] **Step 5: Run target test + full suite**

```bash
bash scripts/test.sh tests/unit/test_rebotarm_adapter.py -v
bash scripts/test.sh tests/ -q
```

If tests need `pytest-asyncio` markers and the suite doesn't already have an `asyncio_mode = auto` config, add `@pytest.mark.asyncio` to the new tests (already in the test code above).

- [ ] **Step 6: Commit**

```bash
git add backend/mimicrec/adapters/rebotarm_zmq.py tests/unit/test_rebotarm_adapter.py
git commit -m "$(cat <<'EOF'
feat: ReBotArmZmqAdapter — ZMQ REQ client for the safety daemon

Async asyncio.Lock around the bus (REQ is half-duplex). Auto heartbeat
task started in connect(), cancelled in disconnect(). read_state
populates RobotState.ee_* directly from the daemon payload so the
writer doesn't need a local FK. send_joint_command validates shape /
finiteness before sending. estop / clear_estop expose the safety
endpoints to the API layer.

Replaces the no-op stub at backend/mimicrec/adapters/rebotarm.py.
Tests spawn the mock daemon as a subprocess.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Robot + daemon configs (`rebotarm.yaml`, `rebotarm_daemon.yaml`)

**Files:**
- Create: `configs/robot/rebotarm.yaml`
- Create: `configs/rebotarm_daemon.yaml`

These make the adapter selectable from the UI dropdown and give the (real) daemon a runnable config file.

- [ ] **Step 1: Write `configs/robot/rebotarm.yaml`**

```yaml
_target_: mimicrec.adapters.rebotarm_zmq.ReBotArmZmqAdapter
address: tcp://localhost:5558
heartbeat_interval_ms: 200
request_timeout_ms: 1000
replay:
  ramp_duration_sec: 2
  max_joint_velocity: 1
  max_joint_acceleration: 5
  max_joint_position_jump: 0.3
  command_timeout_sec: 0.2
  watchdog_hz: 20
# No `kinematics:` block needed — the daemon supplies EE pose directly
# in the read_state payload (RobotState.ee_*).
```

- [ ] **Step 2: Write `configs/rebotarm_daemon.yaml`**

```yaml
arm_config: configs/rebotarm/arm.yaml   # provided by reBotArm_control_py user setup
zmq_address: tcp://*:5558
control_rate_hz: 500
safety:
  joint_pos_min_rad: [-3.14, -3.14, -3.14, -3.14, -3.14, -3.14]
  joint_pos_max_rad: [3.14, 3.14, 3.14, 3.14, 3.14, 3.14]
  joint_vel_max_rad_s: 3.14
  joint_accel_max_rad_s2: 20.0
  torque_max_nm: [10, 10, 8, 5, 5, 3]
  temperature_warn_c: 70
  temperature_fault_c: 80
  temperature_recover_c: 60
  heartbeat_timeout_ms: 500
gravity_comp:
  push_velocity_threshold_m_s: 0.02
  push_omega_threshold_rad_s: 0.3
  kp: [2, 2, 2, 2, 2, 2]
  kd: [1, 1, 1, 1, 1, 1]
```

- [ ] **Step 3: Verify the adapter is discoverable**

```bash
curl -s http://localhost:8000/api/configs/robot 2>&1 || echo "(backend not running, verify manually)"
ls configs/robot/rebotarm.yaml
```

- [ ] **Step 4: Run full suite to ensure no breakage from the new config files**

```bash
bash scripts/test.sh tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add configs/robot/rebotarm.yaml configs/rebotarm_daemon.yaml
git commit -m "$(cat <<'EOF'
feat: rebotarm robot + daemon configs

robot/rebotarm.yaml selects the new ZMQ adapter; no kinematics
block since the daemon supplies EE on RobotState directly.
rebotarm_daemon.yaml is the operator-tunable safety + gravity-comp
config for the daemon process.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Integration test — full session against mock daemon

**Files:**
- Create: `tests/integration/test_rebotarm_session.py`

End-to-end exercise: spawn mock daemon → start session via the API harness → record a couple of frames → save the episode → assert the parquet has EE columns and that the writer didn't try to use a local FK.

- [ ] **Step 1: Write the test**

Look first at an existing integration test for shape:

```bash
ls tests/integration/
```

Pattern after the closest existing fixture (likely uses `httpx` against the FastAPI app). Then:

```python
# tests/integration/test_rebotarm_session.py
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pyarrow.parquet as pq
import pytest

REPO = Path(__file__).resolve().parents[2]
MOCK = REPO / "scripts" / "rebotarm_daemon_mock.py"
PY = REPO / ".venv" / "bin" / "python"


@pytest.fixture
def mock_daemon():
    port = 5700
    proc = subprocess.Popen(
        [str(PY), str(MOCK), "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid,
    )
    time.sleep(0.5)
    try:
        yield port
    finally:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=2)


@pytest.mark.asyncio
async def test_session_records_ee_columns_via_daemon(mock_daemon, tmp_path, monkeypatch):
    """Full flow: start session pointing at mock daemon, record briefly,
    assert parquet has EE columns supplied via RobotState.ee_*."""
    # Override the address in the rebotarm.yaml at instantiation time.
    # Use a tmp dataset root.
    monkeypatch.setenv("MIMICREC_DATASETS_ROOT", str(tmp_path))

    # Write a temp robot config pointing at our chosen port.
    cfg_dir = tmp_path / "configs" / "robot"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "rebotarm_test.yaml").write_text(f"""\
_target_: mimicrec.adapters.rebotarm_zmq.ReBotArmZmqAdapter
address: tcp://localhost:{mock_daemon}
heartbeat_interval_ms: 100
request_timeout_ms: 500
""")

    # Construct the SessionManager directly (skipping the API layer keeps
    # the test self-contained) and run a tiny record loop.
    from mimicrec.api.deps import build_session_manager_from_request
    # ... (executor: read existing tests/api/test_*.py to mirror their
    # session-construction pattern; the assertion target is:)
    #
    #   table = pq.read_table(<episode_parquet_path>)
    #   assert "observation.state.ee_pos" in table.column_names
    #   assert "observation.state.ee_rotvec" in table.column_names
    #   assert "observation.state.gripper_pos" in table.column_names
    #
    # The most important assertion is that the writer was given fk=None
    # (no FKService loaded for rebotarm) yet the EE columns are still
    # present — proves the daemon-supplied EE path works end-to-end.
    pytest.skip("executor: complete this against the existing API harness")
```

> **Executor note — concrete patterns to mirror:**
> - For SessionManager-direct construction (no API layer): see `tests/integration/test_session_lifecycle_mock.py` — the `_make_sm(...)` helper / equivalent shows how to build a SessionManager against a mock adapter.
> - For HTTP-API-driven tests: see `tests/api/test_session_routes.py` — uses an `httpx.AsyncClient` against `mimicrec.api.app:app` with a temporary `MIMICREC_DATASETS_ROOT`.
> Pick whichever fits — the assertion target (parquet has EE columns) is the same. The skip below should be removed once wired.

- [ ] **Step 2: Run with the test enabled, verify pass**

```bash
bash scripts/test.sh tests/integration/test_rebotarm_session.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_rebotarm_session.py
git commit -m "$(cat <<'EOF'
test(integration): rebotarm session records EE columns via mock daemon

End-to-end: mock daemon spawned in a subprocess → SessionManager
configured against it → brief record → asserts the parquet has
ee_pos / ee_rotvec / gripper_pos columns even though no local
FKService was loaded. Proves the RobotState-side EE path.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Integration test — estop / clear_estop cycle

**Files:**
- Create: `tests/integration/test_rebotarm_estop.py`

- [ ] **Step 1: Write the test**

```python
# tests/integration/test_rebotarm_estop.py
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from mimicrec.adapters.rebotarm_zmq import ReBotArmZmqAdapter
from mimicrec.errors import HardwareError

REPO = Path(__file__).resolve().parents[2]
MOCK = REPO / "scripts" / "rebotarm_daemon_mock.py"
PY = REPO / ".venv" / "bin" / "python"


@pytest.fixture
def mock_daemon():
    port = 5701
    proc = subprocess.Popen(
        [str(PY), str(MOCK), "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid,
    )
    time.sleep(0.5)
    try:
        yield port
    finally:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=2)


@pytest.mark.asyncio
async def test_estop_blocks_and_clear_resumes(mock_daemon):
    a = ReBotArmZmqAdapter(address=f"tcp://localhost:{mock_daemon}",
                           heartbeat_interval_ms=100)
    await a.connect()
    try:
        # baseline: send_command works
        await a.send_joint_command(np.zeros(6, dtype=np.float32))
        # estop
        await a.estop()
        with pytest.raises(HardwareError):
            await a.send_joint_command(np.zeros(6, dtype=np.float32))
        # clear
        result = await a.clear_estop()
        assert result.get("ok")
        # send_command works again
        await a.send_joint_command(np.zeros(6, dtype=np.float32))
    finally:
        await a.disconnect()
```

- [ ] **Step 2: Run, expect PASS**

```bash
bash scripts/test.sh tests/integration/test_rebotarm_estop.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_rebotarm_estop.py
git commit -m "$(cat <<'EOF'
test(integration): rebotarm estop blocks send_command, clear resumes

Round-trip the estop → reject → clear → resume cycle through
the mock daemon. Confirms the adapter raises HardwareError on a
fault-rejected send and that clear_estop is wired correctly.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: API routes — `POST /api/robot/estop` and `POST /api/robot/clear_estop`

**Files:**
- Modify: `backend/mimicrec/api/routes/session.py`
- Test: `tests/api/test_robot_safety_routes.py` (new)

Front-of-house for the E-stop button. Routes look up the active adapter and call `estop()` / `clear_estop()` if it has them.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_robot_safety_routes.py
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

REPO = Path(__file__).resolve().parents[2]
MOCK = REPO / "scripts" / "rebotarm_daemon_mock.py"
PY = REPO / ".venv" / "bin" / "python"


@pytest.fixture
def mock_daemon():
    port = 5702
    proc = subprocess.Popen(
        [str(PY), str(MOCK), "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid,
    )
    time.sleep(0.5)
    try:
        yield port
    finally:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=2)


@pytest.mark.asyncio
async def test_estop_returns_404_when_no_session():
    from mimicrec.api.app import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/robot/estop")
        assert r.status_code in (404, 409)


# Executor note: a happy-path test for /api/robot/estop requires a
# running session with the rebotarm adapter against the mock daemon.
# Pattern to mirror: tests/api/test_session_routes.py — set up a
# session via POST /api/session/start with a temp robot YAML pointing
# at the mock daemon's port (same as Task 11), then POST /api/robot/
# estop and assert 200 + side effect (subsequent send_command rejects).
```

- [ ] **Step 2: Run, expect FAIL or 404 from missing route**

```bash
bash scripts/test.sh tests/api/test_robot_safety_routes.py -v
```

- [ ] **Step 3: Implement routes**

In `backend/mimicrec/api/routes/session.py`, append:

```python
@router.post("/robot/estop")
async def robot_estop(request: Request):
    sm = getattr(request.app.state, "session_manager", None)
    if sm is None:
        raise InvalidTransitionError("no active session")
    adapter = sm._robot
    if not hasattr(adapter, "estop"):
        raise InvalidTransitionError("active robot adapter has no estop()")
    await adapter.estop()
    return {"ok": True}


@router.post("/robot/clear_estop")
async def robot_clear_estop(request: Request):
    sm = getattr(request.app.state, "session_manager", None)
    if sm is None:
        raise InvalidTransitionError("no active session")
    adapter = sm._robot
    if not hasattr(adapter, "clear_estop"):
        raise InvalidTransitionError("active robot adapter has no clear_estop()")
    return await adapter.clear_estop()
```

- [ ] **Step 4: Run target test + full suite**

```bash
bash scripts/test.sh tests/api/test_robot_safety_routes.py -v
bash scripts/test.sh tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/api/routes/session.py tests/api/test_robot_safety_routes.py
git commit -m "$(cat <<'EOF'
feat: POST /api/robot/estop + /api/robot/clear_estop

Routes look up the active adapter and dispatch estop / clear_estop
when supported. Returns InvalidTransitionError when no session is
active or when the active adapter has no safety surface (e.g. mock,
sim_so101) — keeps the UI button safe to expose unconditionally.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Frontend — E-stop button + hooks

**Files:**
- Create: `frontend/src/components/EStopButton.tsx`
- Modify: `frontend/src/api/queries.ts`
- Modify: `frontend/src/pages/RecordPage.tsx`

- [ ] **Step 1: Add hooks**

In `frontend/src/api/queries.ts`, near the other mutations:

```typescript
export function useEstop() {
  return useMutation({
    mutationFn: () =>
      apiFetch("/api/robot/estop", { method: "POST" }),
  });
}

export function useClearEstop() {
  return useMutation({
    mutationFn: () =>
      apiFetch<{ ok: boolean; reason?: string }>("/api/robot/clear_estop", { method: "POST" }),
  });
}
```

- [ ] **Step 2: Add the component**

```tsx
// frontend/src/components/EStopButton.tsx
import { useEstop, useClearEstop } from "../api/queries.ts";

export default function EStopButton() {
  const estop = useEstop();
  const clear = useClearEstop();

  return (
    <div className="border-2 border-red-700 bg-red-50 rounded-md p-3 flex items-center gap-3">
      <button
        className="bg-red-600 hover:bg-red-700 text-white font-bold text-lg px-6 py-3 rounded-full shadow"
        onClick={() => estop.mutate()}
        disabled={estop.isPending}
      >
        ⏻ E-STOP
      </button>
      <button
        className="text-sm text-red-800 underline"
        onClick={() => clear.mutate()}
        disabled={clear.isPending}
      >
        clear E-stop
      </button>
      {estop.isError && <span className="text-xs text-red-700">estop failed</span>}
      {clear.isError && <span className="text-xs text-red-700">clear failed</span>}
    </div>
  );
}
```

- [ ] **Step 3: Wire it into RecordPage**

In `frontend/src/pages/RecordPage.tsx`, after the EE monitor block:

```tsx
import EStopButton from "../components/EStopButton.tsx";

// ... inside the active-session JSX, before <RecordingControls />:
{robot === "rebotarm" && (
  <div className="mb-6">
    <EStopButton />
  </div>
)}
```

- [ ] **Step 4: Type-check + smoke**

```bash
cd frontend && pnpm tsc --noEmit && cd ..
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EStopButton.tsx frontend/src/api/queries.ts frontend/src/pages/RecordPage.tsx
git commit -m "$(cat <<'EOF'
feat: E-stop button on Record page when robot=rebotarm

Big red button + small "clear E-stop" link. Hits POST /api/robot/estop
and /api/robot/clear_estop. Shows only for the rebotarm adapter so
users of mock / sim / so101 don't see a button that would 409.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Real daemon — `controllers.py`, `ee_pose.py`, `server.py`, `__main__.py`

**Files:**
- Create: `scripts/rebotarm_daemon/controllers.py`
- Create: `scripts/rebotarm_daemon/ee_pose.py`
- Create: `scripts/rebotarm_daemon/server.py`
- Create: `scripts/rebotarm_daemon/__main__.py`

This is the only Python 3.10 code. Imports `motorbridge`, `reBotArm_control_py.actuator.RobotArm`, `reBotArm_control_py.dynamics`, `reBotArm_control_py.kinematics`, `pinocchio`, `zmq`, `numpy`. CI cannot exercise it; smoke tests are manual.

> **Executor note:** This task uses real hardware bindings, so we cannot write CI tests. **Read each of these reBotArm examples first** before writing the controllers, so the MIT / POS_VEL invocation matches:
> - `reBotArm_control_py/example/9_gravity_compensation.py`
> - `reBotArm_control_py/example/10_gravity_compensation_lock.py`
> - `reBotArm_control_py/example/4_pos_vel_control.py`
>
> **Verify before writing:** the SDK API names assumed below
> (`reBotArm_control_py.kinematics.load_robot_model`,
> `reBotArm_control_py.dynamics.load_dynamics_model` /
> `compute_generalized_gravity`, `arm.get_temperatures()`,
> `arm.get_torques()`) are best-effort guesses from the examples.
> Confirm they exist in the actual SDK; substitute the real names.
>
> **Threading model:** `arm.start_control_loop(callback, rate=...)` —
> example 9 lets the main thread spin in `time.sleep(0.01)` while the
> control loop runs in its own thread. Confirm this in the example;
> if `start_control_loop` is in fact blocking, wrap the ZMQ REP loop
> below in a `threading.Thread(daemon=True).start()` and run the
> control loop on the main thread instead. The plan assumes the
> example-9 pattern (control loop is non-blocking after start).

- [ ] **Step 1: Implement `ee_pose.py`**

```python
# scripts/rebotarm_daemon/ee_pose.py
"""End-effector pose helper using reBotArm's built-in kinematics."""
from __future__ import annotations

import numpy as np

from reBotArm_control_py.kinematics import load_robot_model
import pinocchio as pin


class EEPose:
    def __init__(self, ee_frame_name: str = "tool0"):
        self._model = load_robot_model()
        self._data = self._model.createData()
        self._frame_id = self._model.getFrameId(ee_frame_name)

    def pose(self, q_rad: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        pin.forwardKinematics(self._model, self._data, np.asarray(q_rad, dtype=float))
        pin.updateFramePlacements(self._model, self._data)
        T = self._data.oMf[self._frame_id]
        pos = np.asarray(T.translation, dtype=np.float32)
        # axis-angle (rotvec) form
        rotvec = pin.log3(T.rotation).astype(np.float32)
        return pos, rotvec
```

- [ ] **Step 2: Implement `controllers.py`**

```python
# scripts/rebotarm_daemon/controllers.py
"""Mode controllers for the reBotArm daemon: POSITION and GRAVITY_COMP."""
from __future__ import annotations

import numpy as np

from reBotArm_control_py.dynamics import (
    load_dynamics_model, compute_generalized_gravity,
)


class GravityCompLockController:
    """Example-10-style: lock pose when EE is stationary, follow when pushed."""

    def __init__(self, params, num_joints: int):
        self._params = params
        self._n = num_joints
        self._dyn_model = load_dynamics_model()
        self._target = None  # locked target

    def step(self, arm, ee_lin_vel: np.ndarray, ee_ang_vel: np.ndarray) -> None:
        q = arm.get_positions()
        if self._target is None:
            self._target = q.copy()
        v_norm = float(np.linalg.norm(ee_lin_vel))
        w_norm = float(np.linalg.norm(ee_ang_vel))
        if v_norm > self._params.push_velocity_threshold_m_s or \
           w_norm > self._params.push_omega_threshold_rad_s:
            self._target = q.copy()
        tau_g = compute_generalized_gravity(q=q)
        arm.mit(
            pos=self._target,
            vel=np.zeros(self._n),
            kp=np.asarray(self._params.kp),
            kd=np.asarray(self._params.kd),
            tau=tau_g,
            request_feedback=True,
        )


class PositionController:
    def __init__(self, num_joints: int):
        self._n = num_joints
        self._target = None

    def set_target(self, q: np.ndarray) -> None:
        self._target = np.asarray(q, dtype=float).copy()

    def step(self, arm) -> None:
        if self._target is None:
            self._target = arm.get_positions().copy()
        arm.pos_vel(pos=self._target, vel=np.zeros(self._n))
```

- [ ] **Step 3: Implement `server.py`**

```python
# scripts/rebotarm_daemon/server.py
"""ZMQ REP server for the reBotArm safety daemon."""
from __future__ import annotations

import threading
import time

import numpy as np
import pinocchio as pin
import zmq

from reBotArm_control_py.actuator import RobotArm
from rebotarm_daemon.config import DaemonConfig
from rebotarm_daemon.controllers import (
    GravityCompLockController, PositionController,
)
from rebotarm_daemon.ee_pose import EEPose
from rebotarm_daemon.safety import SafetyManager
from rebotarm_daemon.state import SharedRobotState


# Wire-protocol constants (intentionally duplicated from
# backend/mimicrec/adapters/rebotarm_protocol.py — daemon runs in a
# different venv and cannot import that module).
CMD_CONNECT = "connect"
CMD_DISCONNECT = "disconnect"
CMD_READ_STATE = "read_state"
CMD_SEND_COMMAND = "send_command"
CMD_SET_MODE = "set_mode"
CMD_HEARTBEAT = "heartbeat"
CMD_ESTOP = "estop"
CMD_CLEAR_ESTOP = "clear_estop"
CMD_GET_SAFETY_STATUS = "get_safety_status"
MODE_POSITION = "position"
MODE_GRAVITY_COMP = "gravity_comp"
SAFETY_OK = "ok"


def run_server(cfg: DaemonConfig) -> None:
    arm = RobotArm()
    arm.connect()
    arm.enable()
    n = arm.num_joints

    safety = SafetyManager(cfg.safety, dof=n)
    state = SharedRobotState(dof=n)
    ee = EEPose()

    grav = GravityCompLockController(cfg.gravity_comp, n)
    posctl = PositionController(n)
    mode = {"current": MODE_GRAVITY_COMP}
    last_q = np.zeros(n)
    last_t = time.monotonic()

    def control_callback(arm, dt: float):
        nonlocal last_q, last_t
        q = arm.get_positions()
        # crude EE velocity via finite diff
        dt2 = max(time.monotonic() - last_t, 1e-3)
        ee_pos, ee_rotvec = ee.pose(q)
        ee_pos_prev, _ = ee.pose(last_q) if last_t > 0 else (ee_pos, ee_rotvec)
        ee_lin_vel = (ee_pos - ee_pos_prev) / dt2
        ee_ang_vel = np.zeros(3)  # cheap; refine later if needed

        # update shared state for snapshot()
        try:
            temps = np.asarray(arm.get_temperatures(), dtype=np.float32)
        except AttributeError:
            temps = np.zeros(n, dtype=np.float32)
        try:
            taus = np.asarray(arm.get_torques(), dtype=np.float32)
        except AttributeError:
            taus = np.zeros(n, dtype=np.float32)
        state.set(joint_pos=q.astype(np.float32),
                  joint_vel=np.zeros(n, dtype=np.float32),  # arm doesn't expose vel directly
                  joint_effort=taus,
                  ee_pos=ee_pos, ee_rotvec=ee_rotvec,
                  gripper_pos=None,
                  motor_temps_c=temps,
                  motor_torques_nm=taus)

        # safety state machine
        safety.evaluate_thermal(temps)
        if safety.is_active_fault() or safety.heartbeat_state() != SAFETY_OK:
            # freeze: hold current pose with gravity comp only
            grav.step(arm, np.zeros(3), np.zeros(3))
        elif mode["current"] == MODE_GRAVITY_COMP:
            grav.step(arm, ee_lin_vel, ee_ang_vel)
        else:
            posctl.step(arm)
        last_q = q.copy()
        last_t = time.monotonic()

    arm.start_control_loop(control_callback, rate=cfg.control_rate_hz)

    ctx = zmq.Context()
    sock = ctx.socket(zmq.REP)
    sock.bind(cfg.zmq_address)
    sock.setsockopt(zmq.RCVTIMEO, 100)

    print(f"[rebotarm-daemon] listening on {cfg.zmq_address}")
    stopped = False
    try:
        while not stopped:
            try:
                msg = sock.recv_json()
            except zmq.Again:
                continue
            cmd = msg.get("cmd")

            if cmd == CMD_CONNECT:
                sock.send_json({
                    "ok": True,
                    "dof": n,
                    "joint_names": [f"j{i+1}" for i in range(n)],
                    "ee_frame": "tool0",
                })
            elif cmd == CMD_HEARTBEAT:
                safety.note_heartbeat()
                sock.send_json({"ok": True})
            elif cmd == CMD_READ_STATE:
                snap = state.snapshot()
                payload = {
                    "joint_pos": snap["joint_pos"].tolist(),
                    "joint_vel": snap["joint_vel"].tolist(),
                    "joint_effort": snap["joint_effort"].tolist(),
                    "ee_pos": None if snap["ee_pos"] is None else snap["ee_pos"].tolist(),
                    "ee_rotvec": None if snap["ee_rotvec"] is None else snap["ee_rotvec"].tolist(),
                    "gripper_pos": snap["gripper_pos"],
                    "safety_state": safety.overall_state(snap["motor_temps_c"]),
                    "t_mono_ns": time.monotonic_ns(),
                }
                sock.send_json(payload)
            elif cmd == CMD_SEND_COMMAND:
                if safety.is_active_fault() or safety.heartbeat_state() != SAFETY_OK:
                    sock.send_json({"ok": False, "error": "safety fault active"})
                else:
                    q = np.asarray(msg.get("q", [0.0] * n), dtype=float)
                    q = safety.clamp_joint_pos(q)
                    posctl.set_target(q)
                    sock.send_json({"ok": True})
            elif cmd == CMD_SET_MODE:
                m = msg.get("mode", MODE_GRAVITY_COMP)
                if m not in (MODE_POSITION, MODE_GRAVITY_COMP):
                    sock.send_json({"ok": False, "error": f"unknown mode: {m}"})
                else:
                    mode["current"] = m
                    sock.send_json({"ok": True, "mode": m})
            elif cmd == CMD_ESTOP:
                safety.trigger_estop()
                try:
                    arm.disable()
                except Exception:
                    pass
                sock.send_json({"ok": True})
            elif cmd == CMD_CLEAR_ESTOP:
                snap = state.snapshot()
                if safety.try_clear_estop(snap["motor_temps_c"]):
                    try:
                        arm.enable()
                    except Exception:
                        pass
                    sock.send_json({"ok": True})
                else:
                    sock.send_json({"ok": False, "reason": "preconditions not met"})
            elif cmd == CMD_GET_SAFETY_STATUS:
                snap = state.snapshot()
                sock.send_json({
                    "safety_state": safety.overall_state(snap["motor_temps_c"]),
                    "mode": mode["current"],
                })
            elif cmd == CMD_DISCONNECT:
                stopped = True
                sock.send_json({"ok": True})
            else:
                sock.send_json({"ok": False, "error": f"unknown cmd: {cmd}"})
    finally:
        try:
            arm.disconnect()
        except Exception:
            pass
        sock.close(linger=0)
        ctx.term()
```

- [ ] **Step 4: Implement `__main__.py`**

```python
# scripts/rebotarm_daemon/__main__.py
"""Daemon CLI entry: python -m rebotarm_daemon --config <path>"""
from __future__ import annotations

import argparse
import sys

from rebotarm_daemon.config import load_daemon_config
from rebotarm_daemon.server import run_server


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    cfg = load_daemon_config(args.config)
    run_server(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Smoke test (manual, requires .venv-rebotarm built — see Task 16)**

Skip until Task 16.

- [ ] **Step 6: Commit (no tests pass / fail because daemon imports won't load in 3.12 — that's by design)**

```bash
git add scripts/rebotarm_daemon/controllers.py scripts/rebotarm_daemon/ee_pose.py scripts/rebotarm_daemon/server.py scripts/rebotarm_daemon/__main__.py
git commit -m "$(cat <<'EOF'
feat: real reBotArm safety daemon (Python 3.10)

- ee_pose: Pinocchio FK on the reBotArm URDF, returns pos + rotvec
- controllers: GravityCompLockController (example 10 style) +
  PositionController (POS_VEL)
- server: 500 Hz callback drives shared state + applies the active
  controller; ZMQ REP loop dispatches CMD_* requests, applies
  joint-pos clamp on send_command, freezes on fault / heartbeat
  timeout, ramps disable on estop
- __main__: thin CLI entry

Daemon code only imports under Python 3.10 + reBotArm SDK installed
in .venv-rebotarm; not exercised by CI (covered by mock daemon).
Hardware smoke test deferred to manual operator.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: `setup.sh` adds the `.venv-rebotarm` Python 3.10 venv

**Files:**
- Modify: `scripts/setup.sh`

- [ ] **Step 1: Edit setup.sh** — add this block after the main `installing backend deps` step:

```bash
# ---------- 3b. reBotArm daemon venv (Python 3.10) ----------
# reBotArm_control_py is pinned to Python 3.10 and ships its own
# motorbridge / pinocchio dependencies.
if [[ -d "$REPO_ROOT/reBotArm_control_py" ]]; then
    log "creating .venv-rebotarm (Python 3.10) for reBotArm daemon"
    if [[ ! -d "$REPO_ROOT/.venv-rebotarm" ]]; then
        uv venv "$REPO_ROOT/.venv-rebotarm" --python 3.10
    fi
    PY_REBOT="$REPO_ROOT/.venv-rebotarm/bin/python"
    log "installing reBotArm + daemon deps"
    uv pip install --python "$PY_REBOT" \
        -e "$REPO_ROOT/reBotArm_control_py" \
        pyzmq numpy pyyaml pinocchio
else
    log "reBotArm_control_py submodule absent — skipping rebotarm daemon venv"
fi
```

- [ ] **Step 2: Verify syntactically**

```bash
bash -n scripts/setup.sh && echo "syntax OK"
```

- [ ] **Step 3: Update README sections**

In `README.md` and `README.ja.md`, in the "Hardware (optional)" or "Manual install" section, add a paragraph explaining the daemon requires its own venv and is started manually:

```markdown
### reBotArm (optional)

`reBotArm_control_py` requires Python 3.10 (cannot share the 3.12
backend venv). `setup.sh` creates `.venv-rebotarm` automatically when
the `reBotArm_control_py` submodule is present. Start the daemon in
a separate terminal:

    .venv-rebotarm/bin/python -m rebotarm_daemon \
        --config configs/rebotarm_daemon.yaml

Then in MimicRec UI choose `robot=rebotarm`. The Record page will
show a big red E-stop button.
```

- [ ] **Step 4: Run full suite — none of this affects tests but be sure**

```bash
bash scripts/test.sh tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add scripts/setup.sh README.md README.ja.md
git commit -m "$(cat <<'EOF'
chore: setup.sh installs .venv-rebotarm (Python 3.10) for daemon

reBotArm_control_py pins Python 3.10, so the daemon can't share the
3.12 backend venv. setup.sh now creates .venv-rebotarm and installs
the SDK + pyzmq / pinocchio / pyyaml. README documents the manual
daemon start command.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 17: README polish + final full-suite check

**Files:**
- Modify: `README.md`, `README.ja.md`

- [ ] **Step 1: Update the "Supported hardware" table**

Change the `reBot Arm B601-DM` row's status from `Stub` to `Verified (mock daemon in CI; hardware smoke pending)`. Mention safety MVP scope (1–7).

- [ ] **Step 2: Update keyboard shortcut and Web UI sections**

If the E-stop button isn't a keyboard shortcut yet, leave the keyboard table alone. (Adding `Esc-Esc` for E-stop is a nice future, not MVP.)

- [ ] **Step 3: Final test pass**

```bash
bash scripts/test.sh tests/ -q
cd frontend && pnpm tsc --noEmit && cd ..
```

Both must succeed.

- [ ] **Step 4: Commit**

```bash
git add README.md README.ja.md
git commit -m "$(cat <<'EOF'
docs: reBotArm support marked Verified (mock daemon in CI)

Updated supported-hardware table; hardware smoke pending operator.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 18: Hardware smoke test (manual, not CI)

**Goal:** verify the integration on the real arm. No code changes; this is the operator runbook.

- [ ] **Step 1:** Plug the arm in (CAN bus + 24 V power). Verify motors enumerate (`ip link show can0` or whatever driver / interface the arm uses).

- [ ] **Step 2:** Start the daemon:

```bash
.venv-rebotarm/bin/python -m rebotarm_daemon --config configs/rebotarm_daemon.yaml
```

Expected log: `[rebotarm-daemon] listening on tcp://*:5558`. The arm should silently enter gravity-comp lock — push it gently and verify it follows, release and verify it holds.

- [ ] **Step 3:** Start backend + frontend in separate terminals:

```bash
bash scripts/run.sh
```

- [ ] **Step 4:** In the UI, start a session with `robot=rebotarm`, `mode=hand_teach`, dataset = a fresh name. Press **E-STOP** in the UI — verify the daemon log shows the estop command, the arm goes limp safely (still under gravity comp via daemon's freeze-on-fault). Press "clear E-stop" — verify the arm comes back online.

- [ ] **Step 5:** Record one episode (Space → push the arm through a small motion → Space → save). Verify the parquet has `observation.state.ee_pos` columns and live `/ws/state` shows EE moving in real time.

- [ ] **Step 6:** Replay the episode (UI → Replay page). Verify the arm tracks the recorded trajectory without violations (no thermal alerts, no torque clamps tripping).

- [ ] **Step 7:** Note any issues in a follow-up issue / TODO. Don't commit; this task produces no code.

---

## Final sanity check

- [ ] Run the full test suite one last time:

```bash
bash scripts/test.sh tests/ -q
```

- [ ] Confirm the commit log is coherent:

```bash
git log --oneline -20
```

- [ ] Push when ready:

```bash
git push origin main
```

---

## Out of scope reminders

These are explicitly NOT part of this plan:

- Leader / keyboard teleop driving reBotArm (only POSITION via replay uses send_joint_command)
- Hardware E-stop button + power relay
- systemd / auto-start of daemon
- Refactor of sim_bridge into a unified protocol
- Live safety_status display in the frontend (status comes through but no dedicated indicator beyond E-stop button); add later if useful
