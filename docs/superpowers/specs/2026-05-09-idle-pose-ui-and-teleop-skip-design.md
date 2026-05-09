# Idle Pose UI Capture + TELEOP Skip — Design

Date: 2026-05-09
Status: Draft (awaiting review)

## 背景

- アーム idle pose は現状 `configs/rebotarm/idle_pose.yaml` に手書きの ZMQ ワンショット (README 記載) で書き出している。UI から更新する手段がない。
- TELEOP モードでは録画停止 / セッション開始のたびに `move_to_idle()` がフォロワーを idle pose へ動かすが、リーダー (SO leader) は `read_action()` のみの read-only adapter で同期して動かせない。マッパは delta-mode で内部 anchor (`_target_pos` 等) を保持しており、idle 復帰後に RECORDING へ戻ると mapper の anchor が古いまま新しいフォロワー姿勢との差分を IK に流し込むため、再開直後に follower が「グワッ」と元位置方向へ走る。
- ユーザーの判断: TELEOP では idle 復帰自体が要件に合わないので **削除する**。HAND_TEACH の idle 復帰は教示の起点を揃える目的があるため現状維持。
- 同時に、HAND_TEACH 中に「今手で動かしている姿勢を idle として保存」したいニーズがあり、UI から触れるようにしたい (README が示唆していた `capture_idle_pose.py` 切り出しの代替)。

## スコープ

含む:
1. `_move_to_idle_for_session()` の skip 対象に `SessionMode.TELEOP` を追加 (3 箇所すべての trigger に効く)
2. 「現姿勢を idle として保存」する API + UI の追加 (HAND_TEACH セッション中限定)

含まない:
- リーダーアームを書き込み可能にする / モーター駆動して idle へ追従させる
- マッパの anchor リセット (TELEOP の idle 復帰自体を削除するので不要)
- joint 値を手で編集する UI、idle pose の手動トリガー UI (`go_to_idle.py` の UI 版)
- `start()` 時の idle 復帰挙動の変更 (HAND_TEACH では従来通り発火、TELEOP では発火しない)

## バックエンド変更

### 1. lifecycle: TELEOP の idle 復帰を skip

`backend/mimicrec/session/lifecycle.py` の `_move_to_idle_for_session()`:

現状:
```python
if self.session.mode == SessionMode.INFERENCE:
    return
after = (
    RobotMode.GRAVITY_COMP
    if self.session.mode == SessionMode.HAND_TEACH
    else RobotMode.POSITION
)
```

変更後:
```python
if self.session.mode in (SessionMode.INFERENCE, SessionMode.TELEOP):
    return
# 残るは HAND_TEACH のみ → after_mode は常に GRAVITY_COMP
after = RobotMode.GRAVITY_COMP
```

これで `start()` / `episode_stop()` / `episode_save()|discard()` の 3 経路すべてで TELEOP は idle へ動かなくなる。`_idle_move_task` の spawn / cancel 周りはそのままでよい (TELEOP では task=None のまま `_await_pending_idle_move()` の早期 return パスを通る)。

### 2. idle 姿勢キャプチャの実装

`backend/mimicrec/session/idle.py` に追加:

```python
def save_idle_pose(pose: IdlePose, path: Path | str = DEFAULT_IDLE_POSE_PATH,
                   *, source: str = "ui_capture") -> dict:
    """IdlePose を yaml にシリアライズして書き出す。書き出した dict を返す。"""
```

書き出す yaml の schema は既存と同一:
- `joint_names: list[str]`
- `joint_pos_rad: list[float]`
- `joint_pos_deg: list[float]`
- `gripper_pos: float | null`
- `captured_at_unix: float`
- `source: str` (UI 経由なら `"ui_capture via session adapter"`)

キャプチャ自体は API ルート側で adapter から `read_state()` してから `IdlePose` を組み立てる (`joint_names` は session manager が保持している `joint_names` を渡す。後述)。

### 3. API ルート

`backend/mimicrec/api/routes/session.py` に追加:

```
POST /api/session/idle-pose/capture
```

挙動:
1. `get_session_manager(request.app)` でアクティブ session を取得 (なければ 409)
2. `session.mode != HAND_TEACH` なら 409 (`detail`: "idle capture requires HAND_TEACH session")
3. `state = await sm._robot.read_state()` (`sm._robot` 直アクセスは `routes/session.py:152, 176` と同じ既存パターン)
4. `joint_names = sm._robot.joint_names` (lifecycle.py:761 / ws/teleop_hub.py:47 と同じ)
5. `IdlePose` を構築 → `save_idle_pose()` → 書き出した dict を JSON で返す

レスポンス例:
```json
{
  "joint_names": ["joint1", ...],
  "joint_pos_rad": [...], "joint_pos_deg": [...],
  "gripper_pos": ..., "captured_at_unix": 1778..., "source": "ui_capture..."
}
```

エラー:
- 409 active session なし
- 409 mode != HAND_TEACH
- 503 adapter read_state 失敗 (HardwareError)
- 500 yaml 書き込み失敗

## フロントエンド変更

### 1. 新コンポーネント `IdlePoseCaptureButton.tsx`

場所: `frontend/src/components/IdlePoseCaptureButton.tsx`

挙動:
- props なし。内部で `useSessionStore` から `mode` を読み、HAND_TEACH のときだけ render (それ以外 `null`)
- ボタン: "Set current pose as home"
- クリック → 確認モーダル開く
  - モーダル本文は確認文のみ ("Save the current arm pose as the new idle position? This overwrites configs/rebotarm/idle_pose.yaml.")。frontend には現姿勢を取得する専用フック / hook が今ないため、live preview は MVP では入れない (将来必要なら、API レスポンスを使った "after" toast に joint 値を含めて見せる方向で別途検討)
  - "Confirm" で `apiFetch("/api/session/idle-pose/capture", { method: "POST" })`
  - 成功 → モーダル閉じて toast "Idle pose updated"
  - 失敗 → toast にエラー文表示、モーダルは開いたまま

### 2. RecordPage への組み込み

`frontend/src/pages/RecordPage.tsx`:
- session 起動中の主画面 (現在 `RecordingControls` などが並んでいる領域) に `<IdlePoseCaptureButton />` を 1 個置く
- 表示位置の細部はレビュー時に詰める。`RecordingControls` の右側 / `EEMonitor` の隣 / セカンダリ操作群あたりが候補

### 3. 既存 SettingsPage には触らない

`SettingsPage.tsx` の汎用 config 編集 (`CONFIG_GROUPS`) には `rebotarm` を加えず、idle pose は専用 UI 経由でのみ更新する。理由: 一般ユーザーが textarea で raw YAML を編集する事故を避けたい。`rebotarm/arm.yaml` 等を将来扱いたくなったら別議論。

## エラー処理 / エッジケース

- HAND_TEACH 以外で誤って API が叩かれた場合 → backend 409、frontend 側はそもそもボタンを出さない
- adapter read 失敗 → backend 503、UI は toast で「アームから状態取得に失敗しました」
- yaml 書き出し中の途中失敗 → 既存ファイルを破壊しないよう `tempfile + rename` (atomic write) を `save_idle_pose()` 内で行う
- 同時連打: モーダルの Confirm 中はボタン disable でガード

## テスト計画

backend (`tests/unit/`):
- `test_lifecycle_idle_skip.py` (or 既存ライフサイクルテストへ追加): TELEOP session で `_move_to_idle_for_session()` を呼んでも `move_to_idle` が発火しないことを確認。HAND_TEACH では発火することも回帰として残す
- `test_idle_save.py` 新規: `save_idle_pose()` が正しい schema の yaml を書き出すこと、atomic write で部分書きが残らないこと
- `tests/integration/` 相当があれば API ルートのハッピーパス + 409/503 エラー

frontend:
- 現状 `frontend/package.json` に vitest / jest 等のテストランナーが入っていないため、frontend 自動テストはスコープ外。動作確認は dev server を起動して HAND_TEACH セッションでボタンが表示されること、モーダル確認 → 保存 → toast 表示までを手動で確認する

## マイグレーション / 影響範囲

- 既存 yaml は schema 互換なので壊さない
- TELEOP セッションでは idle 復帰しなくなる挙動変更がユーザー目線で起きる。README (`backend/mimicrec/session/README.md`) の対応表を更新する必要あり (TELEOP 行を「skip (削除済み)」に)
- `scripts/go_to_idle.py` は手動トリガーなので残置 (削除も改修もしない)
