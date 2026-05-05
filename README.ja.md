# MimicRec

[English](README.md) | [日本語](README.ja.md)

ロボットアームから模倣学習用データセットを集めるためのローカルファースト Web アプリ。テレオペ・ハンドティーチ・録画・レビュー・リプレイ・ダウンロードまで、すべて LeRobot フォーマットで完結します。

## 何ができる

- **テレオペレーション**: リーダーアーム / キーボード / シミュレータからフォロワーを操作して軌道を録画
- **ハンドティーチ**: 純コンプライアンス重力補償でロボットを手で動かして教示（reBotArm）。グリッパも摩擦補償付きで軽く動かせます
- **レビュー**: 録ったエピソードを保存／破棄／成功・失敗ラベル付け
- **リプレイ**: アーム＋グリッパ両方が録画通りに動作、安全ウォッチドッグ付き
- **VLA 推論実行**: HTTP 契約経由で Vision-Language-Action モデルを実機に走らせる (`configs/inference/`)
- **サブタスクアノテーション**: アプリ内の stub アノテータ（実 VLM はまだ）
- **設定 UI**: デバイス検出・キャリブレーション状態・アダプタ config 編集
- **ダウンロード**: LeRobot v3 互換 zip でデータセット書き出し

## 対応ハードウェア

| Robot | インターフェース | ハンドティーチ | 状態 |
|-------|-----------------|----------------|------|
| SO-101 | LeRobot `SOFollower` (Feetech STS3215) | 非対応（重力補償なし） | 動作確認済み |
| SO Leader | LeRobot `SOLeader` テレオペ | — | 動作確認済み |
| reBot Arm B601-DM (+ グリッパ) | `reBotArm_control_py` via ZMQ デーモン | 純コンプライアンス重力補償 + グリッパ摩擦補償 | 動作確認済み |
| Mock | 内蔵モックアダプタ | 対応 | テスト用 |
| Isaac Sim (任意ロボット) | ZMQ ブリッジ | 対応 | 動作確認済み (Franka) |

## アーキテクチャ

```
Browser (React)  ←→  FastAPI + WebSocket  ←→  SessionManager  ←→  Hardware / Sim
     :5173                 :8000                    ↓
                                              Recording → LeRobot v3 dataset
```

- **Backend**: Python 3.12, FastAPI, asyncio 制御ループ, LeRobot v3 形式
- **Frontend**: React 19, TypeScript, Vite, TailwindCSS, TanStack Query
- **約 250 backend テスト** (unit / integration / exit-criteria / API)

## クイックスタート

**Ubuntu 22.04 / 24.04** で動作確認済み。他の Linux / WSL でも動くと思いますが、システムパッケージのところだけ調整が必要です。

### 一発セットアップ

```bash
git clone --recurse-submodules <repo> && cd MimicRec
bash scripts/setup.sh
```

（`--recurse-submodules` 忘れても `setup.sh` が後から submodule を取ってきます。）

このスクリプトは冪等です。`lerobot` と `reBotArm_control_py` の submodule 取得、システムパッケージ・`uv`・Python 3.12・バックエンドと LeRobot の依存・Node 20 + pnpm + フロントエンド依存・`dialout` / `video` グループへのユーザー追加まで全部やります。

> グループに変更があった場合は、**ログアウト→ログイン**して反映してください（または同じシェルだけで一時的に効かせる場合は `newgrp video`）。

オプション: `--no-system` (apt とグループ変更をスキップ、sudo プロンプトなし)、`--no-frontend` (Node / pnpm / フロントを飛ばす)。

### 前提（setup.sh が代わりに入れるもの）

apt: `ffmpeg`, `v4l-utils`, `libudev-dev`, `pkg-config`, `build-essential`, `git`, `git-lfs`, `curl`

ツールチェーン:
- `uv` (公式インストーラ)
- Python 3.12 (uv が自動で取得。Ubuntu 22.04 デフォルトは 3.10)
- Node.js 20+ (NodeSource 経由) と `pnpm` (`npm -g` で導入)

ハードウェア（任意）:
- SO-101 follower / leader on `/dev/ttyACM*` (`dialout` グループ要)
- USB カメラ on `/dev/video*` (`video` グループ要)
- NVIDIA GPU + driver (VLA 推論サーバを自前ホストする場合のみ必要。アプリ内のスタブアノテータは CPU で動きます)
- Isaac Sim 5.0 (Omniverse Launcher から別途インストール)

### 手動インストール（setup.sh を使わない場合）

```bash
# uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Backend
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e "./backend[dev]"

# LeRobot (SO-101 用)
uv pip install --python .venv/bin/python -e "./lerobot"
uv pip install --python .venv/bin/python "lerobot[feetech]"

# Frontend (Node 20+ と pnpm が必要)
cd frontend && pnpm install && cd ..

# ハードウェアグループ (再ログイン必須)
sudo usermod -aG dialout,video "$USER"
```

### 起動

```bash
bash scripts/run.sh
# Backend:  http://localhost:8000
# Frontend: http://localhost:5173
```

別々に立ち上げたい場合:

```bash
bash scripts/run_backend.sh   # FastAPI :8000
bash scripts/run_frontend.sh  # Vite :5173
```

### テスト実行

```bash
bash scripts/test.sh tests/ -q                 # 全テスト
bash scripts/test.sh tests/ -k exit_criterion  # Plan A 終了基準 (9 件)
bash scripts/test.sh tests/api/ -q             # API テストのみ
```

## 使い方

### 1. モックモード（ハードウェア無し）

`http://localhost:5173` を開いて **Record** ページへ:
- Robot: `mock`
- Teleop: `mock_leader`
- Mapper: `identity`
- Dataset: `my_dataset`
- Task: `pick`

**Start Session** → **Start Recording** (`Space`) → **Stop** → **Save** (`Space`)。

### 2. SO-101 テレオペ

最初にキャリブレーション（一度だけ）。`id` は `configs/robot/so101.yaml` と `configs/teleop/so_leader.yaml` の `id:` と完全一致させる必要があります:

```bash
.venv/bin/python scripts/calibrate_so101.py \
    --port /dev/ttyACM0 --id my_awesome_follower_arm --type follower
.venv/bin/python scripts/calibrate_so101.py \
    --port /dev/ttyACM1 --id my_awesome_leader_arm --type leader
```

スクリプトはアームに接続して LeRobot の対話キャリブレーションを実行します（中央位置に動かして Enter → 各関節を可動域いっぱい動かして Enter）。

**既にキャリブ済みのアームを再キャリブする場合**: デフォルトでは LeRobot は既存のキャリブレーションを使い回します。`--force` を渡すとキャッシュファイルを削除してから新規キャリブが走ります:

```bash
.venv/bin/python scripts/calibrate_so101.py \
    --port /dev/ttyACM0 --id my_awesome_follower_arm --type follower --force
```

> キャリブレーションは `~/.cache/huggingface/lerobot/calibration/` 配下の `robots/so_follower/<id>.json` と `teleoperators/so_leader/<id>.json` に保存されます。

**ポートは差し直すたびに入れ替わることがあります。** config と異なるポートでキャリブしてしまうと挙動が怪しくなります。物理アームとポートの対応を確認するには:

```bash
.venv/bin/python scripts/identify_arms.py
# 片方のアームだけ手で動かす → 値が変化するポートがそのアーム
```

UI 側では:
- Robot: `so101`
- Teleop: `so_leader`
- Mapper: `identity`
- Cameras: `front`, `wrist` (任意)

**EE 座標を記録に含める。** `configs/robot/so101.yaml` には `kinematics:` ブロックが書かれていて、`configs/urdf/so101/so101.urdf` で順運動学を計算します。これにより各 parquet 行に `observation.state.ee_pos / ee_rotvec`・`action.ee_pos / ee_rotvec`・`gripper_pos` 列が自動で追加されます。不要なら `kinematics:` ブロックをコメントアウトしてください。`kinematics` extra が必要です: `uv pip install --python .venv/bin/python -e "./backend[kinematics]"` (`setup.sh` がデフォルトで入れます)。

> 診断・キャリブレーション系スクリプトは、バックエンドにアクティブなセッションがあると自動で実行を拒否します（シリアルポート競合防止）。実行前にセッションを終了してください: `curl -X POST http://localhost:8000/api/session/end`

### 3. Isaac Sim (シミュレーション)

```bash
# ターミナル1: シムブリッジ起動
~/isaacsim/python.sh scripts/sim_bridge_isaacsim.py --robot franka --headless

# ターミナル2: MimicRec 起動
bash scripts/run.sh
```

UI 側で:
- Robot: `sim_franka` または `sim_so101`
- Camera: `sim_front`

Isaac Sim なしでテストしたい場合:

```bash
.venv/bin/python scripts/sim_bridge_dummy.py  # ダミーシム on :5556
```

### 4. reBotArm (任意)

`reBotArm_control_py` は Python 3.10 必須で、3.12 のバックエンド venv とは
共有できません。`setup.sh` は `reBotArm_control_py` submodule が存在するときに
`.venv-rebotarm` を自動で作成します。デーモンは別ターミナルで起動してください:

    .venv-rebotarm/bin/python -m rebotarm_daemon \
        --config configs/rebotarm_daemon.yaml

その後 MimicRec UI で `robot=rebotarm` を選択すると、Record ページに
大きな赤い E-stop ボタンが表示されます。

デーモンが 500Hz アーム制御ループ + 100Hz グリッパループを保持し、
ハンドティーチは [`reBotArm_control_py/data_collect/11_gravity_compensation_record.py`](reBotArm_control_py/data_collect/11_gravity_compensation_record.py)
を踏襲、モータは常に MIT モードで動作します(リプレイ/テレオペ用の POSITION
モードは MIT + 強い kp + 重力 FF というだけ)。モード切替で arm が
落下する事故は起きません。デーモンはバックエンドの session start/end を
跨いで生存するので、基本的には一度起動して放置で OK。

#### 設定

トップレベルの `configs/rebotarm_daemon.yaml` と、上流 submodule から
コピーするハードウェア固有 config を編集します:

```bash
cp reBotArm_control_py/config/arm.yaml     configs/rebotarm/arm.yaml
cp reBotArm_control_py/config/gripper.yaml configs/rebotarm/gripper.yaml
```

`configs/rebotarm/arm.yaml` のモータ ID / channel を実機に合わせます。
MimicRec の daemon config 側でチューニングする主なパラメータ:

- `gravity_in_base` — ベース座標系で表したワールド重力 (m/s²)。直立/水平
  マウントなら省略 (デフォルト `[0, 0, -9.81]`)。傾斜マウントの場合は
  ワールド重力をベース座標に回した値をここに入れる。設定しないと重力補償
  がオペレータと逆方向に働きます。`configs/rebotarm_daemon.yaml` に
  45° 横傾斜・前傾斜の例があります。
- `gravity_comp.kd` — ハンドティーチ時の関節別ダンピング。慣性が大きい
  近位 4340P (関節1〜3) ほど高く。デフォルト `[1.5, 1.5, 1.0, 0.6, 0.4, 0.2]`。
  手放した瞬間に「飛んでいく」なら上げ、押し感が重ければ下げます。
- `position.kp / position.kd` — リプレイ時の MIT ゲイン。デフォルトは
  `arm.yaml` の MIT デフォルト (近位 120/8、遠位 18/2) 相当。トラッキング
  をきつくしたければ上げ、コマンド着地を柔らかくしたければ下げます。
- `gripper.friction_tau_nm / vel_deadband_rad_s` — グリッパを押した瞬間
  に方向沿いに足す摩擦補償。粘るなら上げ、勝手に動くなら下げます。

リプレイは録画から arm + gripper 両方を再生します。parquet の
`action.gripper_pos` 列が読み込まれて別経路でデーモンに送信される
仕組み。グリッパのない録画/ハードウェアでは arm のみ再生されます。

#### 録画が止まる / リプレイが abort する場合

リプレイ abort はほぼ safety watchdog の trip です。バックエンドログの
`[replay] SAFETY TRIP` を見ると、どのゲート（`joint_position_jump` /
`joint_velocity` / `joint_acceleration`）がどの値で発火したか出ます。
`configs/robot/rebotarm.yaml` の `replay:` ブロックの該当しきい値を
録画の自然な値に合わせて引き上げてください。デーモン側 clamp
(`configs/rebotarm_daemon.yaml` の `safety:` ブロック) が実モータに
届く前のスムージングを担当します。

録画の cadence(フレーム間隔のばらつき)は parquet から確認できます:

```python
import pyarrow.parquet as pq, numpy as np
ts = np.array([float(r.as_py()) for r in pq.read_table(
    "datasets/<ds>/data/chunk-000/episode_000000.parquet"
).column("timestamp")])
dt = np.diff(ts)
print(f"median {np.median(dt)*1000:.1f}ms  std {np.std(dt)*1000:.2f}ms  "
      f"min {dt.min()*1000:.1f}ms  max {dt.max()*1000:.1f}ms")
```

健全な 30 fps 録画なら median ~33 ms、std < 1 ms。std が median と
同等のレベルで暴れてる場合、H.264 エンコーダが追いついていません
(writer はすでに asyncio ループ外でエンコード+`preset=ultrafast`
を使ってますが、低スペック CPU だと更に軽いコーデックが必要かも)。

## キーボードショートカット (Record ページ)

| キー | 動作 |
|------|------|
| `Space` | `ready` → 開始, `recording` → 停止, `review` → **Success として保存** |
| `F` | `review` → **Failure として保存** |
| `D` | `review` → 破棄 |
| `Esc` | 自動サイクルをキャンセル |
| `1` / `2` / `3` | ラベルを手動でセット: success / failure / skip |

自動サイクルモード（Record フォームでトグル）: *Duration* 秒録画 → *Review window* 秒の介入猶予（`F` で失敗保存・`D` で破棄）→ 自動的に次のエピソードを開始します。

## Web UI ページ

| ページ | パス | 説明 |
|--------|------|------|
| **Datasets** | `/datasets` | データセット一覧・作成・ダウンロード |
| **Record** | `/record` | セッション設定 → 録画 → レビュー → 保存 |
| **Episodes** | `/datasets/:ds/episodes` | エピソード表・削除・アノテーション |
| **Replay** | `/datasets/:ds/episodes/:idx/replay` | 動画再生・実機リプレイ |
| **Inference** | `/inference` | VLA モデルを実機に走らせる (start/stop, 指示文, 状態表示) |
| **Settings** | `/settings` | デバイス検出・アダプタ設定・キャリブ状態 |

## REST API

### セッション / 録画 / リプレイ

| Method | Endpoint | 説明 |
|--------|----------|------|
| `GET` | `/api/health` | ヘルスチェック |
| `POST` | `/api/session/start` | セッション開始 |
| `POST` | `/api/session/end` | セッション終了 |
| `GET` | `/api/session/state` | 現在のセッション状態 |
| `GET` | `/api/session/config` | 起動中セッションの解決済み config |
| `POST` | `/api/episode/start` | 録画開始 |
| `POST` | `/api/episode/stop` | 録画停止 |
| `POST` | `/api/episode/save` | エピソード保存 |
| `POST` | `/api/episode/discard` | エピソード破棄 |
| `POST` | `/api/replay/start` | 実機リプレイ開始 |
| `POST` | `/api/replay/stop` | リプレイ停止 |
| `GET` | `/api/configs/:group` | config オプション一覧 |

### データセット / エピソード / アノテーション

| Method | Endpoint | 説明 |
|--------|----------|------|
| `GET` | `/api/datasets` | データセット一覧 |
| `POST` | `/api/datasets` | データセット作成 |
| `DELETE` | `/api/datasets/:ds` | データセット削除 |
| `GET` | `/api/datasets/:ds/episodes` | エピソード一覧 |
| `GET` | `/api/datasets/:ds/episodes/:idx` | エピソード詳細 |
| `DELETE` | `/api/datasets/:ds/episodes/:idx` | 削除 (tombstone) |
| `GET` | `/api/datasets/:ds/episodes/:idx/video/:cam` | エピソード動画ストリーム |
| `GET` | `/api/datasets/:ds/episodes/:idx/frames` | アノテーション用サンプリングフレーム |
| `GET` | `/api/datasets/:ds/tasks` | タスク名一覧 |
| `POST` | `/api/datasets/:ds/tasks` | タスク追加 |
| `GET` | `/api/datasets/:ds/archive` | zip ダウンロード |
| `POST` | `/api/datasets/:ds/episodes/:idx/annotate` | 1 エピソードアノテート |
| `POST` | `/api/datasets/:ds/annotate-all` | データセット全件アノテート |
| `GET` | `/api/datasets/:ds/annotate-progress` | アノテート進捗ポーリング |

### 推論 (VLA)

| Method | Endpoint | 説明 |
|--------|----------|------|
| `GET` | `/api/configs/inference` | 利用可能な推論コントラクト一覧 |
| `GET` | `/api/configs/inference/:name` | パース＋検証済みコントラクト読み取り (env は伏字化) |
| `POST` | `/api/session/inference/start` | アクティブロボットに対して推論セッション開始 |
| `POST` | `/api/session/inference/stop` | 推論セッション停止 |
| `PUT` | `/api/session/inference/instruction` | 自然言語指示文をセット (READY のみ) |
| `GET` | `/api/session/inference/state` | 現在の推論状態 |

コントラクト本体は `configs/inference/*.yaml`。スキーマ詳細(エンドポイント・リクエスト/レスポンス形・action 形式・正規化統計)は `configs/inference/README.md` を参照。

### 設定

| Method | Endpoint | 説明 |
|--------|----------|------|
| `GET` | `/api/settings/devices/serial` | 検出されたシリアルポート |
| `GET` | `/api/settings/devices/cameras` | 検出されたカメラ |
| `GET` | `/api/settings/configs/:group` | グループ内 config 一覧 |
| `GET` | `/api/settings/configs/:group/:name` | config 読み取り |
| `POST` | `/api/settings/configs/:group/:name` | config 書き込み |
| `DELETE` | `/api/settings/configs/:group/:name` | config 削除 |
| `GET` | `/api/settings/calibration` | キャリブファイル一覧 |
| `GET` | `/api/settings/calibration/:category/:type/:id` | キャリブ読み取り |

## WebSocket チャネル

| Path | レート | 内容 |
|------|--------|------|
| `/ws/session` | イベント駆動 | 状態遷移・エピソード進捗・エラー |
| `/ws/state` | ~15 Hz | ロボットの関節位置・速度 |
| `/ws/cameras/:cam` | ~15 Hz | JPEG バイナリフレーム |
| `/ws/teleop` | イベント駆動 | ブラウザキーボード teleop 入力 |
| `/ws/inference` | イベント駆動 | 推論セッション状態・チャンクイベント・エラー |

## データセット形式

LeRobot v3 互換:

```
datasets/my_dataset/
  meta/
    info.json              # v3 schema with features
    tasks.parquet
    episodes/chunk-000/file-000.parquet
  data/
    chunk-000/
      episode_000000.parquet
      episode_000001.parquet
  videos/
    chunk-000/
      observation.images.front/
        episode_000000.mp4
```

## 新規ロボットの追加

1. `RobotAdapter` プロトコルを実装したアダプタを作成 (`backend/mimicrec/adapters/robot.py`)
2. `configs/robot/your_robot.yaml` に `_target_: your.module.YourAdapter` を書く
3. (任意) `Teleoperator` プロトコル準拠のテレオペレータも実装
4. UI のロボットドロップダウンに自動で出てきます

### シミュレータブリッジ

ZMQ ブリッジプロトコルでどんなシムでも繋げられます:

```python
# シム側が ZMQ REQ/REP (port 5556) で JSON を送受信:
{"cmd": "connect"}           → {"ok": true, "dof": 6, "joint_names": [...]}
{"cmd": "read_state"}        → {"joint_pos": [...], "joint_vel": [...]}
{"cmd": "send_command", "q": [...]} → {"ok": true}
{"cmd": "disconnect"}        → {"ok": true}
```

リファレンス実装は `scripts/sim_bridge_isaacsim.py` を参照。

## プロジェクト構造

```
MimicRec/
  backend/mimicrec/
    adapters/     # ロボット & teleop アダプタ (SO-101, mock, sim bridge, web teleop)
    annotator/    # アプリ内サブタスクアノテータ (現状 stub)
    api/          # FastAPI ルート + WebSocket ハブ
    cameras/      # CameraManager, OpenCV, sim camera
    config/       # OmegaConf ローダ
    datasets/     # リーダ, アーカイブビルダ
    inference/    # VLA HTTP クライアント, contract ローダ, 制御ループ
    kinematics/   # URDF ベース順運動学 (EE 列の生成)
    mappers/      # Teleop → ロボットコマンド変換
    recording/    # ライタ, pending, parquet, metadata
    session/      # SessionManager, control loop, dispatcher, replay
    util/         # LatestValue, metrics, clock, error bus
  frontend/src/
    api/          # REST クライアント, WebSocket, TanStack Query フック
    components/   # UI コンポーネント (shadcn/ui スタイル)
    pages/        # Datasets, Record, Episodes, Replay, Inference, Settings
    state/        # Zustand session / inference ストア
  configs/        # ロボット, teleop, mapper, camera, inference, rebotarm YAML
  docs/           # アーキテクチャノート, VLA サーバ契約スペック
  scripts/        # 起動スクリプト, キャリブ, sim ブリッジ, rebotarm デーモン
  tests/          # unit, integration, exit criteria, API
```

## VLA 推論

MimicRec は HTTP で公開された任意の Vision-Language-Action モデルから実機を
動かせます。`configs/inference/` 配下の YAML がリクエストの組み立て方
（カメラ・proprio 状態・指示文）と、チャンク化された action レスポンスの
解釈（座標系・単位・正規化統計）を記述します。

- スキーマ詳細: `configs/inference/README.md`
- リファレンス契約: `configs/inference/gemma_libero_v1.yaml`
- VLA サーバ実装側の要求仕様: `docs/vla-server-contract-prompt.md`

MVP は `ee_delta` action（6-DoF EE 差分 + グリッパ）+ `mean_std` /
`minmax_neg1_pos1` 正規化、次チャンク半消費プリフェッチ、RECORDING 中の
オプション `done` 自動停止 をサポート。

## ライセンス

TBD
