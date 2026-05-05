# reBotArm 傾斜マウント対応: 重力補償の base-frame gravity 化

**作成日:** 2026-05-05
**対象:** `reBotArm_control_py` (submodule), `scripts/rebotarm_daemon/`

## 背景

reBotArm daemon の重力補償 (`GravityCompController` および `PositionController` の `tau_g` フィードフォワード) は、Pinocchio の `model.gravity` を介してトルクを計算している。デフォルトは `EARTH_GRAVITY = (0, 0, -9.81)` で、これは **base_link の z 軸が物理的に真上を向いている (= アームを平置き) 前提**。

base_link の前方は `+x`、左方は `+y`、上方は `+z` であることを `compute_fk(q=0)` で確認済 (EE 位置 ≈ `(+0.26, 0, +0.19)`、回転ほぼ単位行列)。

アームを傾けて運用したい場合、base frame で表現された重力ベクトルを `model.gravity` にセットしてやれば、Pinocchio 側は自動的に正しい重力補償トルクを出す。

### 現状の 2 つの問題

1. **library 側のバグ**: `reBotArm_control_py/dynamics/robot_model.py` の `set_gravity()` / `get_gravity()` が壊れていて呼ぶとエラーになる。
   - `set_gravity`: `pin.Motion(gravity)` (3D ndarray 1 引数) は Pinocchio の `Motion` コンストラクタ仕様に合わない。`linear, angular` の 2 引数 or 6D ベクトルが必要。
   - `get_gravity`: `g.linear.x` で読もうとしているが `pin.Motion.linear` は ndarray なので `.x` 属性は無い。
2. **MimicRec daemon 側の未対応**: `scripts/rebotarm_daemon/` は `set_gravity` を一度も呼んでおらず、config にもマウント姿勢パラメータが無い。library が直っても、daemon 経由で傾きを設定する経路がそもそも存在しない。

両方を直す。

## ゴール

- アームの物理マウント姿勢に合わせて base frame の重力ベクトルを config から指定できるようにする
- 起動時に 1 回設定したら、`GravityCompController` および `PositionController` が出すトルクは自動的にそのマウント姿勢を反映する
- 既存挙動 (平置き) は config を変えなければ完全に保たれる

## スコープ外

- マウント姿勢を runtime に変える API (ZMQ コマンドなど) — config 起動時固定でよい
- 重力 magnitude のバリデーション (≈9.81 か等) — 月/火星にも対応する library の設計意図に従い、入れない
- IK / FK 側への影響 — 重力を使わないので無関係
- `reBotArm_control_py` の他の dynamics API のバグ調査・修正
- submodule の push / GitHub PR 作成 (後回し)

---

## 設計

### A. submodule (`reBotArm_control_py`) のバグ修正

**対象ファイル:** `reBotArm_control_py/dynamics/robot_model.py`

**修正 1 — `set_gravity` (line 120):**

```python
# 変更前
model.gravity = pin.Motion(gravity)
# 変更後
model.gravity = pin.Motion(np.asarray(gravity, dtype=float), np.zeros(3))
```

`pin.Motion` の `(linear, angular)` 2 引数コンストラクタを使う。

**修正 2 — `get_gravity` (line 133):**

```python
# 変更前
return np.array([g.linear.x, g.linear.y, g.linear.z])
# 変更後
return np.asarray(g.linear, dtype=float).copy()
```

`.linear` は ndarray なのでそのまま読む。`.copy()` で外部からの変更を防ぐ。

**ブランチ運用:** submodule 内に `fix/gravity-api` を切ってコミット。push / GitHub PR は本作業のスコープ外。MimicRec 側は submodule pointer を新コミットに更新する。

**テスト:** submodule 側はそもそも `tests/` ディレクトリを持たず `example/` の手動スクリプトしか存在しない。スタイルを崩さないため、formal pytest は導入しない。コミットメッセージに再現手順だけ書き残す:

```
set_gravity(model, (0.0, -6.937, -6.937)) followed by
compute_generalized_gravity(q=np.zeros(6)) returns without error and
gives a torque vector that differs from the flat-mount baseline.
```

### B. MimicRec の config 拡張

**対象ファイル:** `scripts/rebotarm_daemon/config.py`

`DaemonConfig` トップレベルに 1 フィールド追加 (`gravity_comp` の中ではない — POSITION モードでも `compute_generalized_gravity` が使われるため、特定セクションに紐付けると意味的に誤解を招く):

```python
@dataclass
class DaemonConfig:
    arm_config: str = "configs/rebotarm/arm.yaml"
    zmq_address: str = "tcp://*:5558"
    control_rate_hz: int = 500
    # World gravity expressed in the arm's base frame, m/s². Default
    # (0, 0, -9.81) assumes the arm is mounted upright on a horizontal
    # surface (base +z = world up). For tilted mounts, rotate world
    # gravity (0,0,-9.81) into the base frame and put the result here.
    # Example: 45° tilt to the right (about base +x) → (0, -6.937, -6.937).
    gravity_in_base: List[float] = field(
        default_factory=lambda: [0.0, 0.0, -9.81]
    )
    safety: SafetyLimits = field(default_factory=SafetyLimits)
    gravity_comp: GravityCompParams = field(default_factory=GravityCompParams)
    position: PositionParams = field(default_factory=PositionParams)
    gripper: Optional[GripperParams] = None
```

`load_daemon_config` も対応:

```python
return DaemonConfig(
    arm_config=raw.get("arm_config", "configs/rebotarm/arm.yaml"),
    zmq_address=raw.get("zmq_address", "tcp://*:5558"),
    control_rate_hz=int(raw.get("control_rate_hz", 500)),
    gravity_in_base=list(raw.get("gravity_in_base", [0.0, 0.0, -9.81])),
    safety=...,
    gravity_comp=...,
    position=...,
    gripper=...,
)
```

**バリデーション:** `DaemonConfig.__post_init__` で `len(gravity_in_base) == 3` のみチェック。長さ違反は `ValueError` を投げる。magnitude チェックは入れない (YAGNI、月/火星対応の library 意図に合わせる)。

**YAML サンプル `configs/rebotarm_daemon.yaml`:** 既存ファイルにコメントで例を追記する。デフォルト挙動を変えないので、ユーザがファイルを更新しなくても既存挙動が続く:

```yaml
# Optional: world gravity expressed in the arm's base frame, m/s².
# Default (omit this line) is [0.0, 0.0, -9.81] = upright/flat mount
# (base +z = world up, base +x = forward, base +y = left).
# For tilted mounts, rotate world gravity into the base frame.
# Example: 45° tilt to the right (about base +x) → [0.0, -6.937, -6.937]
# gravity_in_base: [0.0, 0.0, -9.81]
```

### C. daemon 起動時の `model.gravity` 反映

**対象ファイル:** `scripts/rebotarm_daemon/server.py`

`load_dynamics_model()` はモジュールグローバル `_CACHED_MODEL` に結果を保持し、`compute_generalized_gravity()` (引数 `model` 省略時) はそのキャッシュを使う。つまり **起動時に 1 回キャッシュを温めて `set_gravity` を呼べば、以降の controllers.py 内全ての呼び出しが自動的に新しい gravity を見る**。

`run_server()` の冒頭、コントローラを組み立てる前に挿入:

```python
from reBotArm_control_py.dynamics import load_dynamics_model, set_gravity

def run_server(cfg: DaemonConfig) -> None:
    # Apply the configured mount-aware gravity vector to the cached
    # dynamics model BEFORE any controller is constructed. controllers.py
    # call compute_generalized_gravity() without an explicit model, so
    # they hit this cached instance. Must run before
    # GravityCompController/PositionController are built.
    model = load_dynamics_model()
    set_gravity(model, tuple(cfg.gravity_in_base))
    print(f"[rebotarm-daemon] gravity_in_base = {cfg.gravity_in_base}", flush=True)

    safety = SafetySupervisor(cfg.safety, n)
    grav = GravityCompController(cfg.gravity_comp, n, safety=safety)
    ...
```

**配置の制約:** `GravityCompController.__init__` (`controllers.py:41`) は内部で `compute_generalized_gravity` 用のキャッシュを温めるため `load_dynamics_model` を間接呼出する可能性あり。`set_gravity` は **必ずコントローラ構築より前**に置く。コードコメントで明示。

**ログ:** 起動時に標準出力に出力し、「傾斜設定が効いているか」を即目視確認できるようにする。既存の `server.py:263` (`print(f"[rebotarm-daemon] listening on {cfg.zmq_address}")`) と同じ `print(f"[rebotarm-daemon] ...")` スタイルに揃える。

### D. テスト

**submodule 側:** 上記の通り formal テスト追加なし。

**MimicRec 側 (`tests/`):**

新規もしくは既存 `tests/test_smoke.py` に追加:

1. **デフォルトテスト**: `gravity_in_base` を省いた YAML をロード → `cfg.gravity_in_base == [0.0, 0.0, -9.81]`
2. **明示テスト**: `gravity_in_base: [0.0, -6.937, -6.937]` を書いた YAML をロード → そのまま反映される
3. **長さバリデーション**: `gravity_in_base: [0.0, 0.0]` のように長さ違いの YAML が `ValueError` を投げる

`set_gravity` が実際に Pinocchio に正しく効くかは submodule のコミットメッセージ再現手順で担保する。MimicRec 側は **config 往復のみ**確認。

`tests/fixtures/rebotarm_daemon_test.yaml` 既存パターンに合わせて、必要なら新フィクスチャを追加。

### E. 実機検証手順

1. `configs/rebotarm_daemon.yaml` を変更しないまま daemon を起動
2. ログに `[daemon] gravity_in_base = [0.0, 0.0, -9.81]` が出ることを確認
3. 既存の hand-teach / replay 挙動が変化していないこと (回帰なし) を体感確認
4. (傾けたい時のみ) `gravity_in_base` を書き換えて再起動 → 重力補償が新しい姿勢に追従することを確認

---

## 影響範囲

- **新規 import**: `server.py` で `load_dynamics_model, set_gravity` を追加
- **既存ロジック変更なし**: `GravityCompController` / `PositionController` のコード自体は触らない (キャッシュ経由で自動反映されるため)
- **後方互換**: `gravity_in_base` を省略すると従来挙動と完全一致

## 次ステップ

design 承認後、`writing-plans` スキルで実装プランを作成する。
