# reBotArm Tilted-Mount Gravity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** アームのマウント姿勢に合わせて base-frame の重力ベクトルを daemon config から指定できるようにし、`reBotArm_control_py` 側の `set_gravity` / `get_gravity` バグも併せて修正する。

**Architecture:** submodule (`reBotArm_control_py`) の `dynamics/robot_model.py` で 2 引数版 `pin.Motion(linear, angular)` に直し、`get_gravity` を ndarray 直読みに直す。MimicRec 側は `DaemonConfig` トップレベルに `gravity_in_base: list[float]` を追加し、`run_server()` 冒頭で `load_dynamics_model()` 経由のキャッシュに 1 回 `set_gravity` するだけ。`compute_generalized_gravity()` は同じキャッシュを再利用するので、コントローラ側の修正は不要。

**Tech Stack:** Python 3.10, Pinocchio (pin), pytest, dataclasses + PyYAML, git submodule

**Spec:** `docs/superpowers/specs/2026-05-05-rebotarm-tilted-mount-gravity-design.md`

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `reBotArm_control_py/dynamics/robot_model.py` | Modify (submodule) | `set_gravity` / `get_gravity` のバグ修正 |
| `scripts/rebotarm_daemon/config.py` | Modify | `DaemonConfig.gravity_in_base` 追加、長さ 3 のバリデーション |
| `scripts/rebotarm_daemon/server.py` | Modify | `run_server()` 冒頭で `set_gravity` を呼ぶ + ログ出力 |
| `configs/rebotarm_daemon.yaml` | Modify | コメント形式で例を追記 (デフォルト挙動は不変) |
| `tests/test_rebotarm_daemon_config.py` | Create | `gravity_in_base` の YAML 往復 + バリデーション |

---

## Task 1: submodule の `set_gravity` / `get_gravity` バグ修正

**Files:**
- Modify: `reBotArm_control_py/dynamics/robot_model.py:120`
- Modify: `reBotArm_control_py/dynamics/robot_model.py:132-133`

**Context:** `reBotArm_control_py` は git submodule (現在 branch: `feat/gripper-external-controller`, commit: `9a7cf69`)。submodule リポジトリ内に新ブランチ `fix/gravity-api` を切ってコミットし、push/PR は本タスクのスコープ外。MimicRec 側は submodule pointer を新コミットに更新する。

submodule に formal な pytest は無い (`example/` の手動スクリプトのみ)。テストは一時的な repro スクリプトで実機なし smoke 検証し、コミット後に削除する。再現手順はコミットメッセージに残す。

- [ ] **Step 1: バグ再現スクリプトを作って失敗を確認**

`/tmp/repro_gravity.py` に以下を保存:

```python
import numpy as np
from reBotArm_control_py.dynamics import (
    load_dynamics_model, set_gravity, get_gravity, compute_generalized_gravity,
)

model = load_dynamics_model()
g_target = (0.0, -6.937, -6.937)  # right 45° tilt
print("Calling set_gravity ...")
set_gravity(model, g_target)
print("Calling get_gravity ...")
g_back = get_gravity(model)
print(f"  got: {g_back}")
print("Calling compute_generalized_gravity ...")
tau = compute_generalized_gravity(q=np.zeros(6))
print(f"  tau_g: {tau}")
print("OK")
```

実行:
```bash
/home/tirobot/MimicRec/.venv-rebotarm/bin/python /tmp/repro_gravity.py
```
Expected: `set_gravity` の `pin.Motion(gravity)` が `Boost.Python.ArgumentError` で落ちる。

- [ ] **Step 2: `set_gravity` を修正**

`reBotArm_control_py/dynamics/robot_model.py:118-120` を編集:

```python
# 変更前 (line 118-120)
    if isinstance(gravity, (tuple, list)):
        gravity = np.array(gravity, dtype=float)
    model.gravity = pin.Motion(gravity)

# 変更後
    gravity = np.asarray(gravity, dtype=float)
    if gravity.shape != (3,):
        raise ValueError(
            f"gravity must be a length-3 vector, got shape {gravity.shape}"
        )
    model.gravity = pin.Motion(gravity, np.zeros(3))
```

- [ ] **Step 3: `get_gravity` を修正**

`reBotArm_control_py/dynamics/robot_model.py:132-133` を編集:

```python
# 変更前 (line 132-133)
    g = model.gravity
    return np.array([g.linear.x, g.linear.y, g.linear.z])

# 変更後
    g = model.gravity
    return np.asarray(g.linear, dtype=float).copy()
```

- [ ] **Step 4: repro スクリプトを再実行して両方とも動くことを確認**

```bash
/home/tirobot/MimicRec/.venv-rebotarm/bin/python /tmp/repro_gravity.py
```

Expected output (抜粋):
```
Calling set_gravity ...
Calling get_gravity ...
  got: [ 0.    -6.937 -6.937]
Calling compute_generalized_gravity ...
  tau_g: [-0.295 -0.85  -5.229 -1.466 -0.54   0.   ]
OK
```

`tau_g[0]` および `tau_g[4]` が flat 時の `0` から有意に動いていれば、傾斜が反映されている証拠。

- [ ] **Step 5: 既存挙動 (flat) も回帰していないことを確認**

`/tmp/repro_gravity_flat.py` に保存:

```python
import numpy as np
from reBotArm_control_py.dynamics import (
    load_dynamics_model, set_gravity, compute_generalized_gravity,
)
model = load_dynamics_model()
set_gravity(model, (0.0, 0.0, -9.81))
tau = compute_generalized_gravity(q=np.zeros(6))
print(f"flat tau_g: {tau}")
# Expected: [0, ~-1.20, ~-7.39, ~-2.07, 0, ~0]
assert abs(tau[0]) < 1e-6 and abs(tau[4]) < 1e-6, "joint1 / joint5 should be 0 at flat mount"
print("OK")
```

実行:
```bash
/home/tirobot/MimicRec/.venv-rebotarm/bin/python /tmp/repro_gravity_flat.py
```
Expected: `OK` で終了。

- [ ] **Step 6: 一時スクリプトを削除**

```bash
rm /tmp/repro_gravity.py /tmp/repro_gravity_flat.py
```

- [ ] **Step 7: submodule 内で fix ブランチを切ってコミット**

```bash
cd /home/tirobot/MimicRec/reBotArm_control_py
git checkout -b fix/gravity-api
git add reBotArm_control_py/dynamics/robot_model.py
git commit -m "$(cat <<'EOF'
fix(dynamics): make set_gravity / get_gravity work with 3D ndarray

set_gravity called pin.Motion(gravity) with a 3-element ndarray, which
Pinocchio's Motion constructor does not accept (it requires either a
6-element vector or two 3-element vectors as linear/angular). Use the
two-argument form with zero angular velocity.

get_gravity read g.linear.x / g.linear.y / g.linear.z, but
pin.Motion.linear is a numpy ndarray and has no .x attribute. Read it
directly and return a copy.

Reproduction (now fixed):
  set_gravity(model, (0.0, -6.937, -6.937))   # right 45° tilt
  g_back = get_gravity(model)                 # array([0, -6.937, -6.937])
  tau = compute_generalized_gravity(q=np.zeros(6))
  # tau[0], tau[4] are non-zero (gravity now has off-axis components)
EOF
)"
```

- [ ] **Step 8: MimicRec 側で submodule pointer を更新してコミット**

```bash
cd /home/tirobot/MimicRec
git add reBotArm_control_py
git commit -m "$(cat <<'EOF'
chore(submodule): bump reBotArm_control_py to fix/gravity-api

Picks up the set_gravity / get_gravity API fix needed for tilted-mount
gravity compensation. See submodule commit and design doc:
docs/superpowers/specs/2026-05-05-rebotarm-tilted-mount-gravity-design.md
EOF
)"
```

---

## Task 2: `DaemonConfig.gravity_in_base` の追加 (TDD)

**Files:**
- Create: `tests/test_rebotarm_daemon_config.py`
- Modify: `scripts/rebotarm_daemon/config.py`

**Context:** `tests/conftest.py` には rebotarm daemon 用のフィクスチャは無いが、`tests/fixtures/rebotarm_daemon_test.yaml` というファイルが既に存在する (gravity_in_base なしの形)。新テストでは tmp_path で YAML を書き出して `load_daemon_config` を呼ぶ。

`scripts/` パッケージは pip インストールされておらず `import rebotarm_daemon.config` は素では失敗する (確認済)。テスト先頭で `sys.path.insert` で `scripts/` をパスに通す必要あり。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_rebotarm_daemon_config.py` を作成:

```python
"""Tests for the optional gravity_in_base field on DaemonConfig.

Covers:
- Omitting gravity_in_base falls back to the flat-mount default.
- Explicit gravity_in_base in YAML round-trips through load_daemon_config.
- Length != 3 raises ValueError at construction time.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

# scripts/ is not pip-installed; add it to the import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from rebotarm_daemon.config import DaemonConfig, load_daemon_config


def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "daemon.yaml"
    p.write_text(body)
    return p


def test_gravity_in_base_default_is_flat_mount(tmp_path: Path) -> None:
    """Omitting gravity_in_base must keep the prior flat-mount behavior."""
    cfg_path = _write_yaml(tmp_path, "arm_config: configs/rebotarm/arm.yaml\n")
    cfg = load_daemon_config(cfg_path)
    assert cfg.gravity_in_base == [0.0, 0.0, -9.81]


def test_gravity_in_base_explicit_round_trips(tmp_path: Path) -> None:
    """A right-45° tilt vector in YAML lands verbatim on the dataclass."""
    cfg_path = _write_yaml(
        tmp_path,
        "arm_config: configs/rebotarm/arm.yaml\n"
        "gravity_in_base: [0.0, -6.937, -6.937]\n",
    )
    cfg = load_daemon_config(cfg_path)
    assert cfg.gravity_in_base == [0.0, -6.937, -6.937]


def test_gravity_in_base_wrong_length_raises(tmp_path: Path) -> None:
    """Guard against typos like a 2-element vector silently being accepted."""
    cfg_path = _write_yaml(
        tmp_path,
        "arm_config: configs/rebotarm/arm.yaml\n"
        "gravity_in_base: [0.0, 0.0]\n",
    )
    with pytest.raises(ValueError, match="gravity_in_base"):
        load_daemon_config(cfg_path)


def test_gravity_in_base_default_dataclass() -> None:
    """Constructing DaemonConfig() directly also defaults to flat mount."""
    cfg = DaemonConfig()
    assert cfg.gravity_in_base == [0.0, 0.0, -9.81]
```

- [ ] **Step 2: テスト実行で失敗を確認**

```bash
/home/tirobot/MimicRec/.venv/bin/pytest tests/test_rebotarm_daemon_config.py -v
```
Expected: 4 件全部 FAIL — `gravity_in_base` 属性が無い、または `load_daemon_config` がそれを読まない。

- [ ] **Step 3: `DaemonConfig` に `gravity_in_base` を追加し、`__post_init__` で長さチェック**

`scripts/rebotarm_daemon/config.py` 編集:

冒頭の import に `__post_init__` 用の何かは不要。`@dataclass` の `__post_init__` を使う。

`DaemonConfig` の定義を以下に置き換え:

```python
@dataclass
class DaemonConfig:
    arm_config: str = "configs/rebotarm/arm.yaml"
    zmq_address: str = "tcp://*:5558"
    control_rate_hz: int = 500
    # World gravity expressed in the arm's base frame, m/s². Default
    # (0, 0, -9.81) assumes the arm is mounted upright on a horizontal
    # surface (base +z = world up, base +x = forward, base +y = left).
    # For tilted mounts, rotate world gravity (0,0,-9.81) into the base
    # frame and put the result here. Example: 45° tilt to the right
    # (about base +x) → (0.0, -6.937, -6.937).
    gravity_in_base: List[float] = field(
        default_factory=lambda: [0.0, 0.0, -9.81]
    )
    safety: SafetyLimits = field(default_factory=SafetyLimits)
    gravity_comp: GravityCompParams = field(default_factory=GravityCompParams)
    position: PositionParams = field(default_factory=PositionParams)
    gripper: Optional[GripperParams] = None

    def __post_init__(self) -> None:
        if len(self.gravity_in_base) != 3:
            raise ValueError(
                f"gravity_in_base must be a length-3 list, got "
                f"{self.gravity_in_base!r} (length {len(self.gravity_in_base)})"
            )
```

- [ ] **Step 4: `load_daemon_config` に gravity_in_base を渡す**

同ファイル `load_daemon_config` の return 部分を編集:

```python
    return DaemonConfig(
        arm_config=raw.get("arm_config", "configs/rebotarm/arm.yaml"),
        zmq_address=raw.get("zmq_address", "tcp://*:5558"),
        control_rate_hz=int(raw.get("control_rate_hz", 500)),
        gravity_in_base=list(raw.get("gravity_in_base", [0.0, 0.0, -9.81])),
        safety=SafetyLimits(**safety_raw) if safety_raw else SafetyLimits(),
        gravity_comp=GravityCompParams(**grav_raw) if grav_raw else GravityCompParams(),
        position=PositionParams(**pos_raw) if pos_raw else PositionParams(),
        gripper=GripperParams(**gripper_raw) if gripper_raw else None,
    )
```

- [ ] **Step 5: テスト実行で全 PASS を確認**

```bash
/home/tirobot/MimicRec/.venv/bin/pytest tests/test_rebotarm_daemon_config.py -v
```
Expected: `4 passed`

- [ ] **Step 6: 既存テストが回帰していないことを確認**

```bash
/home/tirobot/MimicRec/.venv/bin/pytest tests/ -x --timeout=60 2>&1 | tail -20
```
Expected: 既存テスト数 + 4 件 PASS。

- [ ] **Step 7: コミット**

```bash
cd /home/tirobot/MimicRec
git add scripts/rebotarm_daemon/config.py tests/test_rebotarm_daemon_config.py
git commit -m "$(cat <<'EOF'
feat(rebotarm_daemon): add gravity_in_base config for tilted mounts

Adds DaemonConfig.gravity_in_base — a length-3 list giving the world
gravity vector expressed in the arm's base frame. Default
(0, 0, -9.81) preserves prior flat-mount behavior; tilted mounts can
override it (e.g. 45° right tilt → [0, -6.937, -6.937]).

Validated at config construction so a wrong-length vector is caught at
startup, not at the first compute_generalized_gravity call.

Server-side wiring follows in a subsequent commit; this commit only
adds the field and tests for YAML round-tripping.
EOF
)"
```

---

## Task 3: daemon 起動時に `set_gravity` を呼ぶ

**Files:**
- Modify: `scripts/rebotarm_daemon/server.py:33` (imports)
- Modify: `scripts/rebotarm_daemon/server.py:113-123` (run_server preamble)

**Context:** `controllers.py:41` の `GravityCompController.__init__` は `compute_generalized_gravity` のキャッシュを温めるために間接的に `load_dynamics_model()` を呼ぶ可能性がある。`set_gravity` は **必ず `GravityCompController(...)` 構築より前**に呼ぶ。`server.py:263` 既存の `print(f"[rebotarm-daemon] listening on ...")` に合わせて同じプレフィックスでログ出力する。

このタスクは実機が無いと完全な動作確認は出来ないので、unit test ではなく import smoke と manual 起動チェックで担保する。

- [ ] **Step 1: `server.py` の import に `load_dynamics_model` / `set_gravity` を追加**

`scripts/rebotarm_daemon/server.py` を開いて、既存の `from reBotArm_control_py.dynamics import compute_generalized_gravity` (line 80 付近、`pre_release_settle` 関数内) と controllers import (line 33) を確認。

ファイル先頭の import 群 (line 1-50 あたりのトップレベル) に追加:

```python
from reBotArm_control_py.dynamics import load_dynamics_model, set_gravity
```

- [ ] **Step 2: `run_server` 冒頭で gravity をセット**

`server.py:113-123` の `run_server` 関数を以下のように編集 (既存ロジック直前に挿入):

```python
def run_server(cfg: DaemonConfig) -> None:
    # Apply the configured mount-aware gravity vector to the cached
    # dynamics model BEFORE any controller is constructed.
    # controllers.py and pre_release_settle call
    # compute_generalized_gravity() without an explicit model, so they
    # hit this cached instance. Must run before GravityCompController /
    # PositionController are built (their __init__ may also touch the
    # cache via compute_generalized_gravity).
    model = load_dynamics_model()
    set_gravity(model, tuple(cfg.gravity_in_base))
    print(
        f"[rebotarm-daemon] gravity_in_base = {cfg.gravity_in_base}",
        flush=True,
    )

    arm = RobotArm(cfg.arm_config)
    arm.connect()
    arm.enable()
    n = arm.num_joints

    safety = SafetyManager(cfg.safety, dof=n)
    state = SharedRobotState(dof=n)
    ee = EEPose()

    grav = GravityCompController(cfg.gravity_comp, n, safety=safety)
    posctl = PositionController(cfg.position, n, safety=safety)
    # ... 以下既存
```

- [ ] **Step 3: import smoke でモジュールが構文的に正しいことを確認**

```bash
/home/tirobot/MimicRec/.venv-rebotarm/bin/python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('/home/tirobot/MimicRec/scripts')))
from rebotarm_daemon import server
print('import OK; run_server defined:', callable(server.run_server))
"
```
Expected: `import OK; run_server defined: True`

- [ ] **Step 4: 起動 dry-run で gravity ログが出ることを確認**

実機接続が無くても `RobotArm(cfg.arm_config).connect()` で落ちる前に gravity ログは出るはず。dummy 実行:

```bash
cd /home/tirobot/MimicRec
/home/tirobot/MimicRec/.venv-rebotarm/bin/python -m rebotarm_daemon \
    --config configs/rebotarm_daemon.yaml 2>&1 | head -10
```
Expected: 出力の早い段階に `[rebotarm-daemon] gravity_in_base = [0.0, 0.0, -9.81]` が含まれる。`RobotArm` 接続失敗で落ちても OK (gravity ログがその前に出ていればよい)。

注: 既存 daemon の起動コマンドが上記と異なる場合は `scripts/rebotarm_daemon/__main__.py:7-21` を確認。

- [ ] **Step 5: コミット**

```bash
cd /home/tirobot/MimicRec
git add scripts/rebotarm_daemon/server.py
git commit -m "$(cat <<'EOF'
feat(rebotarm_daemon): apply gravity_in_base at server startup

run_server() now warms load_dynamics_model() and calls set_gravity()
with cfg.gravity_in_base before any controller is constructed. The
shared cached model is what compute_generalized_gravity() reads for
both GRAVITY_COMP and POSITION mode tau_g feedforward, so this single
call propagates the mount-aware gravity to all downstream torque
calculations without per-call threading.

Logs the active gravity vector to stdout for quick visual confirmation
at startup, matching the existing "[rebotarm-daemon] ..." print style.
EOF
)"
```

---

## Task 4: YAML サンプルにコメントで例を追記

**Files:**
- Modify: `configs/rebotarm_daemon.yaml`

**Context:** デフォルトの flat-mount 挙動を維持するため、デフォルト値は YAML には書かない (空 = `[0, 0, -9.81]`)。傾斜が必要な時だけコメントを外して書き換えるための手引きをコメントで残す。

- [ ] **Step 1: コメントを追記**

`configs/rebotarm_daemon.yaml` の `control_rate_hz: 500` の直後 (4 行目あたり) に以下を追記:

```yaml
# Optional: world gravity expressed in the arm's base frame, m/s².
# Default (omit this line) is [0.0, 0.0, -9.81] = upright/flat mount
# (base +z = world up, base +x = forward, base +y = left).
# For tilted mounts, rotate world gravity into the base frame and put
# the result here. Examples:
#   45° tilt to the right (about base +x) → [0.0, -6.937, -6.937]
#   45° tilt forward       (about base +y) → [+6.937, 0.0, -6.937]
# gravity_in_base: [0.0, 0.0, -9.81]
```

- [ ] **Step 2: 既存テストでこの YAML を読んでも fail しないことを確認**

```bash
/home/tirobot/MimicRec/.venv/bin/pytest tests/ -x --timeout=60 2>&1 | tail -10
```
Expected: 全テスト PASS。

- [ ] **Step 3: 実機で平置き起動 → ログに `[0.0, 0.0, -9.81]` が出る回帰チェック (manual)**

```bash
cd /home/tirobot/MimicRec
/home/tirobot/MimicRec/.venv-rebotarm/bin/python -m rebotarm_daemon \
    --config configs/rebotarm_daemon.yaml
```
Expected: ログに `[rebotarm-daemon] gravity_in_base = [0.0, 0.0, -9.81]` が出る。hand-teach / replay の感触が以前と変わっていないことを目視 (重力補償が同一なので変わらないはず)。

- [ ] **Step 4: コミット**

```bash
cd /home/tirobot/MimicRec
git add configs/rebotarm_daemon.yaml
git commit -m "$(cat <<'EOF'
docs(rebotarm_daemon): document gravity_in_base in example config

Adds a commented-out example block explaining the base-frame gravity
vector convention (base +z = world up, +x = forward, +y = left) with
two illustrative tilt cases. Default (omit the key) preserves prior
flat-mount behavior, so no functional change for existing setups.
EOF
)"
```

---

## 実機検証 (任意、デプロイ前)

設計 spec の E. に対応する手動検証:

1. config 未変更で起動 → ログに `[0.0, 0.0, -9.81]`、hand-teach / replay 感触に回帰なし
2. `gravity_in_base: [0.0, -6.937, -6.937]` に書き換えて再起動 → ログ反映、アームを物理的に右 45° に傾けてから hand-teach すると、垂直時より腕が「軽く支えられている」感触になることを確認
3. ログを戻し、デフォルトに復帰

---

## Self-Review

- ✅ **Spec coverage:**
  - A. submodule 修正 → Task 1 (set_gravity + get_gravity 両方カバー)
  - B. config 拡張 → Task 2 (dataclass + load_daemon_config + 長さバリデーション)
  - C. 起動時反映 → Task 3 (controllers より前に呼ぶ制約も明記)
  - D. テスト → Task 2 で MimicRec 側 4 ケース、Task 1 で submodule 側 repro 検証
  - E. 実機検証 → 末尾の「実機検証」セクション
- ✅ **Placeholder scan:** TBD/TODO 無し。具体的な行番号・コード・期待出力すべて記載。
- ✅ **Type consistency:** `gravity_in_base` は `List[float]` で一貫。`set_gravity(model, tuple(cfg.gravity_in_base))` はリスト→タプル変換のみで、submodule 側は `np.asarray(gravity, dtype=float)` で受けるので互換。
- ✅ **Default value:** `[0.0, 0.0, -9.81]` は dataclass / yaml fallback / submodule の `EARTH_GRAVITY` で完全一致。
