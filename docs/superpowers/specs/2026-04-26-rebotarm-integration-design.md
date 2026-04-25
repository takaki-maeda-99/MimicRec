# reBotArm Integration Design (MVP)

**Date:** 2026-04-26
**Status:** Approved (pending user spec review)
**Scope:** Integrate reBotArm B601-DM hand-teach data collection into MimicRec.

## 1. Purpose

Replace the no-op `ReBotArmAdapter` stub with a working integration that
lets a user collect imitation-learning data on a reBotArm by physically
moving the arm under gravity-compensated control, and replay recorded
episodes back on the arm. Recordings include both joint and end-effector
columns, matching the SO-101 schema.

`reBotArm_control_py` requires Python 3.10 and ships its own URDF + FK +
Pinocchio dynamics, so the integration runs as a **separate safety
daemon** in its own venv, communicating with the MimicRec backend
(Python 3.12) over ZMQ.

## 2. Scope

### In scope (MVP)

- Hand-teach data collection using example 10 style "position lock with
  push-to-move" gravity compensation
- Replay of recorded episodes via POS_VEL position control
- EE pose columns in recordings (computed in the daemon, transported as
  state payload)
- Safety daemon with multi-layer guards: software E-stop, heartbeat
  watchdog, joint position / velocity / acceleration / torque limits,
  thermal cutoff
- Manual daemon startup (separate terminal, mirroring the Isaac Sim
  bridge pattern)

### Out of scope (deferred)

- Leader-arm or keyboard teleop driving reBotArm (only POSITION via
  replay path uses send_joint_command)
- Hardware E-stop button + power relay (option 9) — interface left
  unimplemented until the hardware is procured
- Auto / systemd-managed daemon startup
- Refactoring `sim_bridge` into a unified protocol (deferred until a
  third worker robot exists)

## 3. Architecture

```
┌──────────────────────────────────────────┐  ┌─────────────────────────────────────────┐
│  MimicRec backend (Python 3.12)          │  │  rebotarm_daemon  (Python 3.10, .venv-rebotarm) │
│  ┌────────────────────────────────────┐  │  │  ┌───────────────────────────────────┐  │
│  │ ReBotArmZmqAdapter                 │◄─┼──┼──► ZMQ REP :5558 (ctrl)              │  │
│  │  - connect / read_state            │  │  │  │                                   │  │
│  │  - send_joint_command              │  │  │  │  SafetyManager                    │  │
│  │  - set_mode (POSITION / GRAVITY_   │  │  │  │   ├─ joint pos clamp              │  │
│  │      COMP)                         │  │  │  │   ├─ velocity / accel ramp        │  │
│  │  - heartbeat (auto, ~5 Hz)         │  │  │  │   ├─ torque limit                 │  │
│  │  - estop / clear_estop             │  │  │  │   ├─ thermal cutoff               │  │
│  │  - get_safety_status               │  │  │  │   └─ heartbeat watchdog (500 ms)  │  │
│  └────────────────────────────────────┘  │  │  │                                   │  │
│            │                             │  │  │  ModeController                   │  │
│  ┌─────────▼──────────────────────────┐  │  │  │   ├─ POSITION (POS_VEL)           │  │
│  │ SessionManager (existing)          │  │  │  │   └─ GRAVITY_COMP (example10 風)  │  │
│  │  + recording / writer              │  │  │  │                                   │  │
│  │  + EE columns (from worker)        │  │  │  │  reBotArm RobotArm.start_control_ │  │
│  └────────────────────────────────────┘  │  │  │     loop(callback, 500 Hz)        │  │
└──────────────────────────────────────────┘  │  └───────────────────────────────────┘  │
                                              │                                         │
   ZMQ REQ/REP, msgpack (json fallback)       │  motorbridge SDK ──► CAN ──► Damiao motors
                                              └─────────────────────────────────────────┘
```

The daemon owns all high-frequency logic (500 Hz) and all safety
responsibilities. The MimicRec backend only sends targets, reads state,
and switches mode — every safety decision (E-stop, heartbeat timeout,
thermal cutoff) is made locally inside the daemon, independent of the
network. ZMQ runs on `:5558` to coexist with the existing sim bridge on
`:5556`.

If the backend dies, the daemon's heartbeat watchdog enters freeze mode
within 500 ms, holding pose via MIT lock with `tau = g(q)`. Power is
never lost without an explicit operator action; that requires the
hardware E-stop (option 9, deferred).

## 4. Components

### 4.1 MimicRec backend (Python 3.12)

| File | Responsibility |
|---|---|
| `backend/mimicrec/adapters/rebotarm_zmq.py` (new) | Implements `RobotAdapter`. ZMQ REQ client. Spawns an asyncio heartbeat task (5 Hz). `name = "rebotarm"`, `dof = 6`, `joint_names = ["j1".."j6"]` (queried from daemon on connect). |
| `configs/robot/rebotarm.yaml` (new) | `_target_: mimicrec.adapters.rebotarm_zmq.ReBotArmZmqAdapter`, `address: tcp://localhost:5558`, `heartbeat_interval_ms: 200`, existing `replay:` block, declarative `kinematics:` block (target_frame name only — URDF lives in the daemon, MimicRec does not load it). |
| `backend/mimicrec/adapters/rebotarm.py` (existing stub) | Removed. |

The adapter uses the same `_bus_lock: asyncio.Lock` pattern that
`SO101Adapter` uses (added earlier this session) so concurrent reads
from the robot reader and writes from the dispatcher don't race.

### 4.2 rebotarm_daemon (Python 3.10, separate venv)

Lives at `scripts/rebotarm_daemon/` as a Python package:

```
scripts/rebotarm_daemon/
├── __main__.py          # CLI entry: python -m rebotarm_daemon --config ...
├── server.py            # ZMQ REP main loop, request dispatch
├── safety.py            # SafetyManager: integrates all watchdogs
├── controllers.py       # ModeController: POSITION / GRAVITY_COMP control laws
├── state.py             # Shared RobotState (lock-protected, 500 Hz writer / arbitrary readers)
├── ee_pose.py           # reBotArm.kinematics wrapper for EE pos / rotvec
└── config.py            # YAML parsing, SafetyLimits dataclass
```

### 4.3 Daemon configuration

`configs/rebotarm_daemon.yaml` (new):

```yaml
arm_config: configs/rebotarm/arm.yaml   # path to reBotArm-internal YAML (motor IDs, kp, kd)
zmq_address: tcp://*:5558
control_rate_hz: 500

safety:
  joint_pos_min_rad: [...]              # 6 values; redundant with reBotArm YAML by design
  joint_pos_max_rad: [...]              # so MimicRec-side guards stay independent
  joint_vel_max_rad_s: 3.14
  joint_accel_max_rad_s2: 20.0
  torque_max_nm: [10, 10, 8, 5, 5, 3]   # per-joint
  temperature_warn_c: 70
  temperature_fault_c: 80
  temperature_recover_c: 60             # auto-clear thermal fault below this
  heartbeat_timeout_ms: 500

gravity_comp:                           # example 10 style lock-with-push
  push_velocity_threshold_m_s: 0.02
  push_omega_threshold_rad_s: 0.3
  kp: [2, 2, 2, 2, 2, 2]
  kd: [1, 1, 1, 1, 1, 1]
```

Joint names (`j1..j6`) come from the reBotArm YAML and are not renamed
by MimicRec — staying with upstream's naming avoids drift.

### 4.4 setup.sh additions

Adds a Python 3.10 venv just for the daemon:

```bash
if [[ -d "$REPO_ROOT/reBotArm_control_py" ]]; then
    uv venv "$REPO_ROOT/.venv-rebotarm" --python 3.10
    uv pip install --python "$REPO_ROOT/.venv-rebotarm/bin/python" \
        -e "$REPO_ROOT/reBotArm_control_py" \
        pyzmq msgpack numpy pyyaml pinocchio
fi
```

Daemon is started manually:

```bash
.venv-rebotarm/bin/python -m rebotarm_daemon --config configs/rebotarm_daemon.yaml
```

## 5. Data flow

### Session start

1. `POST /api/session/start` with `robot=rebotarm`
2. `ReBotArmZmqAdapter.connect()` issues ZMQ `{"cmd":"connect"}`
3. Daemon: enables motors, loads safety limits, returns `{ok, dof:6, joint_names, ee_frame}`
4. Adapter spawns `_run_heartbeat()` asyncio task (every 200 ms sends `{"cmd":"heartbeat"}`)
5. SessionManager starts (existing path). For hand-teach mode the lifecycle calls `set_mode(GRAVITY_COMP)` automatically (existing pattern, no new code).

### Per-frame loop (writer at 30 Hz)

- `read_state()` issues `{"cmd":"read_state"}` → daemon snapshots its
  lock-protected shared `RobotState` (written by the 500 Hz control
  loop, read on demand) and returns:
  ```
  {
    joint_pos: [...], joint_vel: [...], joint_effort: [...],
    ee_pos: [x,y,z], ee_rotvec: [wx,wy,wz], gripper_pos: float,
    safety_status: {state: "ok"|"warn"|"fault", details: {...}},
    t_mono_ns: ...
  }
  ```
- The writer (existing) maps the payload into parquet rows via the
  unchanged `sample_bundle_to_row` path. Because the daemon already
  computed EE pose, the backend does NOT need a local FKService for
  this robot — the writer's `fk` parameter stays `None` for reBotArm,
  and the `state_hub` includes `ee_pos / ee_rotvec / gripper_pos`
  directly from the most recent state payload.

### Replay

1. `POST /api/replay/start` (existing)
2. SessionManager calls `set_mode(POSITION)` → daemon switches its
   active ModeController to POS_VEL
3. Existing `run_replay()` computes ramped joint targets and calls
   `send_joint_command(q)` per tick
4. Adapter sends `{"cmd":"send_command", "q": [...]}`; daemon's
   SafetyManager applies joint / velocity / accel / torque clamps
   before passing to the controller (defense in depth — replay safety
   on the backend side already clamps too)

### Session end

`disconnect()` issues `{"cmd":"disconnect"}`. The daemon ramps torque
down over ~1 s before disabling motors — cutting torque instantly on a
QDD arm drops it under gravity.

## 6. Error handling and safety boundaries

### Defense in depth

| Layer | Check | On violation |
|---|---|---|
| 1. Adapter, before send | `np.isfinite`, `shape == (6,)` | Raise `HardwareError`, do not send |
| 2. ZMQ protocol | msgpack decode failure / unknown cmd | Daemon returns `{ok:false, error:"..."}` |
| 3. SafetyManager (daemon) | Joint pos clamp → velocity ramp → accel ramp → torque clamp | Clamp the value, increment violations counter, surface in `safety_status` |
| 4. Physical layer | Thermal / heartbeat timeout / E-stop API | Disable torque immediately, transition `safety_state` to fault, refuse all `send_command` until `clear_estop` |

### Heartbeat watchdog

The daemon stores `last_heartbeat_t`. The 500 Hz control loop checks
`now - last_heartbeat_t > heartbeat_timeout_ms (500)` on every tick.
On timeout: transition to `safety_state = "heartbeat_timeout"` and
freeze (hold current pose via MIT lock with `tau = g(q)`). Recoverable
via `clear_estop` once heartbeats resume.

### Thermal cutoff

motorbridge feedback exposes per-motor temperature. SafetyManager
samples it every tick:

- ≥ `temperature_warn_c` (70 °C): include warning in `safety_status`,
  UI shows yellow
- ≥ `temperature_fault_c` (80 °C): disable_torque, `safety_state =
  "thermal_fault"`, UI red, refuse new commands
- Recovery: when max temp drops below `temperature_recover_c` (60 °C)
  AND operator issues explicit `clear_estop`

### E-stop API

- `{"cmd":"estop"}` → immediate `disable_torque`, `safety_state = "estop"`
- `{"cmd":"clear_estop"}` → only succeeds if temperature OK and motor
  fault registers clear
- UI exposes a large red E-stop button in the Record page when robot
  is `rebotarm`

### Backend-side fallbacks

- Daemon not responding (process dead / frozen): adapter raises
  `HardwareError("daemon not responding")` → published on `error_bus`
  → existing session-end path triggers
- While the daemon responds, the principle is **clamp and execute** —
  the daemon never refuses a routine command, only fault states do
- Safety status changes are surfaced through the existing `/ws/session`
  error channel so the UI can react

## 7. Testing strategy

### Unit tests

- `tests/unit/test_rebotarm_safety.py`: feed synthetic joint
  trajectories into `SafetyManager`, verify clamps fire as expected
  (joint / velocity / acceleration / torque)
- `tests/unit/test_rebotarm_adapter.py`: mock ZMQ socket, verify each
  adapter method composes the correct request and parses the reply

### Integration tests (CI-runnable)

- `scripts/rebotarm_daemon_mock.py` (new): equivalent of
  `sim_bridge_dummy.py` — speaks the daemon protocol without real
  hardware, returns synthesized state, accepts all commands. Lives in
  the MimicRec venv so CI can run it without the 3.10 venv.
- `tests/integration/test_rebotarm_session.py`: spawn mock daemon,
  start a session, record a few frames, save the episode, assert that
  the parquet has EE columns, that `safety_status` is propagated, and
  that the heartbeat task is firing
- `tests/integration/test_rebotarm_estop.py`: estop → all subsequent
  `send_command` rejected → `clear_estop` → recovery

### Hardware smoke tests (manual, not CI)

- Start the real daemon connected to hardware → run a hand-teach
  session in MimicRec → physically push the arm and verify position
  lock behaves (holds when not pushed, follows when pushed) → record →
  replay an episode and verify no safety violation
- Inject fake high temperature in test mode and verify the thermal
  fault transition + recovery

### Coverage targets

- `safety.py`: 90 %+ (the core)
- adapter ZMQ layer: 80 %+
- mode controllers: 70 %+ (the SDK calls themselves can only be
  partially mocked)

## 8. Open questions / future work

- **Joint limits source of truth.** Currently the design declares
  limits in MimicRec's daemon YAML, redundant with reBotArm's own YAML.
  This is intentional for independence but means two places to update.
  Could fold into a single source if it becomes painful.
- **EE columns in `state_hub`.** SO-101 computes EE in MimicRec via
  `FKService`. reBotArm receives EE in the state payload from the
  daemon. The state_hub will need a small branch: if the active
  adapter exposes EE in its read_state payload, pass it through;
  otherwise fall back to the FKService path. The cleanest path is to
  make the adapter optionally return EE pose alongside RobotState.
- **Hardware E-stop (option 9).** Deferred. When implemented, the
  daemon will gain a GPIO monitor task and the relay will cut motor
  power directly — no software path involved.
- **Daemon as systemd service.** Out of scope for MVP; manual start
  matches the Isaac Sim bridge pattern. Revisit if an operator wants
  the daemon always-on.
