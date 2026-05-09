# Idle Pose Return

データ収集セッションで「既知の初期姿勢（idle pose）」へアームを滑らかに戻すための仕組み。
セッション開始時とエピソード終了時に自動発火し、毎回同じ起点から記録できるようにする。

## 関連ファイル

| ファイル | 役割 |
|---|---|
| `idle.py` | `IdlePose` データクラス、`load_idle_pose()`、`move_to_idle()` |
| `lifecycle.py` | `SessionManager` への統合（spawn / await / cancel） |
| `../../../configs/rebotarm/idle_pose.yaml` | 記録された idle 姿勢（rad / deg / gripper） |
| `../../../scripts/go_to_idle.py` | CLI からの一発実行 |

## `move_to_idle()` の挙動

```python
async def move_to_idle(
    adapter, *,
    idle_pose=None,         # None なら DEFAULT_IDLE_POSE_PATH をロード
    duration_sec=3.0,       # ランプ時間
    fps=30,                 # setpoint 送信レート
    hold_sec=1.0,           # ランプ後 POSITION で保持する時間
    after_mode=POSITION,    # 完了後に切り替えるモード
    clock=None,
)
```

1. `read_state()` で現在姿勢を取得
2. `set_mode(POSITION)`（daemon は POSITION 遷移時に live measured pose で posctl をシードするので jerk なし）
3. **ランプ**: `q_start → q_goal` を `n = duration_sec * fps` ステップで線形補間
4. **保持**: `q_goal` を `n_hold = hold_sec * fps` ステップ送信し続ける（残留モメンタムを剛性で吸収）
5. `after_mode != POSITION` なら最後にモード切替

`hold_sec` がないと、ランプ末端の慣性で arm が idle 通過後にずれる事象が出たため追加（実機で joint5 が +7° 程度ずれて確認）。

## SessionManager への統合

| タイミング | 呼び方 | after_mode |
|---|---|---|
| `start()` (IDLE → READY) | **同期 await**（readers/dispatcher を spawn する前に到達を保証） | session の target_mode |
| `episode_stop()` (RECORDING → REVIEW) | **バックグラウンド task として spawn**（REVIEW UI を即返すため） | session の target_mode |
| `episode_save()` / `episode_discard()` (REVIEW → READY) | 背景 task を **await**（READY 時点で idle 到達を保証） | — |
| `end()` (任意 → IDLE) | 背景 task を cancel | — |

`session.mode` 別の挙動:

- `HAND_TEACH` → idle へ復帰し `GRAVITY_COMP` で終わる（次のエピソードを手で動かして教示）
- `TELEOP` → **idle 復帰しない**（リーダーアームが read-only で同期できず、EE-delta マッパが REVIEW 中に保持する anchor が古いまま再開すると follower が snap するため、復帰自体を廃止）
- `INFERENCE` → スキップ（別ライフサイクル）

これにより autoCycle（連続自動収集）でも:

```
record → auto-stop ─┐
                    │
              REVIEW (背景で arm が idle へ移動中、ユーザーは判定中)
                    │
auto-save / auto-discard ─ await idle move ─ READY ─ next episode_start
                                                       ↑ 必ず idle 起点
```

## idle 姿勢のキャプチャ／更新

HAND_TEACH セッション中なら RecordPage の "Set current pose as home" ボタンから capture できる。`POST /api/session/idle-pose/capture` が `read_state` → `save_idle_pose` を実行して `configs/rebotarm/idle_pose.yaml` を atomic に上書きする。

CLI / ZMQ ワンショットの方法は以下に残しておく（HAND_TEACH を使えない場面用）:

daemon を起動した状態で:

```bash
.venv/bin/python - <<'PY'
import math, time, zmq, yaml
from pathlib import Path
ctx = zmq.Context.instance()
s = ctx.socket(zmq.REQ); s.connect("tcp://localhost:5558")
s.setsockopt(zmq.RCVTIMEO, 2000); s.setsockopt(zmq.SNDTIMEO, 2000)
s.send_json({"cmd": "connect"}); info = s.recv_json()
s.send_json({"cmd": "read_state"}); st = s.recv_json()
q = [float(x) for x in st["joint_pos"]]
doc = {
    "joint_names": list(info.get("joint_names", [])),
    "joint_pos_rad": q,
    "joint_pos_deg": [math.degrees(x) for x in q],
    "gripper_pos": float(st["gripper_pos"]) if st.get("gripper_pos") is not None else None,
    "captured_at_unix": time.time(),
    "source": "rebotarm_daemon CMD_READ_STATE @ tcp://localhost:5558",
}
Path("configs/rebotarm/idle_pose.yaml").write_text(
    yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
PY
```

(将来的にスクリプト化したい場合は `scripts/capture_idle_pose.py` 切り出し候補)

## CLI からの実行

```bash
.venv/bin/python scripts/go_to_idle.py
.venv/bin/python scripts/go_to_idle.py --duration 5 --after gravity_comp
.venv/bin/python scripts/go_to_idle.py --duration 4 --fps 30 --idle-path configs/rebotarm/idle_pose.yaml
```

CLI は `hold_sec` を露出していない（必要になったら追加）。

## 既知の前提

- daemon が POSITION モード遷移時に live measured pose で posctl をシードすること（`scripts/rebotarm_daemon/server.py` 参照）。これが無いと初手で snap する。
- `idle_pose.yaml` が無いと `FileNotFoundError` を warning ログのみで握り潰す（greenfield 環境向け）。
- 重力補償が完璧でないマウント角度では、`after_mode=GRAVITY_COMP` 後に微小な垂れが残ることがある。マウントを傾けた場合は `configs/rebotarm_daemon.yaml` の `gravity_in_base` を実測値に合わせる。
