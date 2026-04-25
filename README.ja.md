# MimicRec

[English](README.md) | [日本語](README.ja.md)

ロボットアームから模倣学習用データセットを集めるためのローカルファースト Web アプリ。テレオペ・ハンドティーチ・録画・レビュー・リプレイ・ダウンロードまで、すべて LeRobot フォーマットで完結します。

## 何ができる

- **テレオペレーション**: リーダーアーム / キーボード / シミュレータからフォロワーを操作して軌道を録画
- **ハンドティーチ**: 重力補償下でロボットを手で動かして教示（reBotArm 用）
- **レビュー**: 録ったエピソードを保存／破棄／成功・失敗ラベル付け
- **リプレイ**: 安全ウォッチドッグ付きでロボット上で再生
- **サブタスクアノテーション** (現状モック、本実装は `MimicAno/` で進行中)
- **設定 UI**: デバイス検出・キャリブレーション状態・アダプタ config 編集
- **ダウンロード**: LeRobot v3 互換 zip でデータセット書き出し

## 対応ハードウェア

| Robot | インターフェース | ハンドティーチ | 状態 |
|-------|-----------------|----------------|------|
| SO-101 | LeRobot `SOFollower` (Feetech STS3215) | 非対応（重力補償なし） | 動作確認済み |
| SO Leader | LeRobot `SOLeader` テレオペ | — | 動作確認済み |
| reBot Arm B601-DM | `reBotArm_control_py` | 対応 | スタブ実装 (Python 3.10 必要) |
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
- **88 backend テスト** 全件パス

## クイックスタート

**Ubuntu 22.04 / 24.04** で動作確認済み。他の Linux / WSL でも動くと思いますが、システムパッケージのところだけ調整が必要です。

### 一発セットアップ

```bash
git clone <repo> && cd MimicRec
bash scripts/setup.sh
```

このスクリプトは冪等です。システムパッケージ・`uv`・Python 3.12・バックエンドと LeRobot の依存・Node 20 + pnpm + フロントエンド依存・`dialout` / `video` グループへのユーザー追加まで全部やります。

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
- NVIDIA GPU + driver (将来 MimicAno の実 VLM が乗ったら必要。今のスタブは CPU でも動く)
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
bash scripts/test.sh tests/ -q        # 全 88 テスト
bash scripts/test.sh tests/ -k exit_criterion  # Plan A 終了基準 (9 件)
bash scripts/test.sh tests/api/ -q     # API テストのみ (33 件)
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
    api/          # FastAPI ルート + WebSocket ハブ
    cameras/      # CameraManager, OpenCV, sim camera
    config/       # OmegaConf ローダ
    datasets/     # リーダ, アーカイブビルダ
    mappers/      # Teleop → ロボットコマンド変換
    recording/    # ライタ, pending, parquet, metadata
    session/      # SessionManager, control loop, dispatcher, replay
    util/         # LatestValue, metrics, clock, error bus
  frontend/src/
    api/          # REST クライアント, WebSocket, TanStack Query フック
    components/   # UI コンポーネント (shadcn/ui スタイル)
    pages/        # Datasets, Record, Episodes, Replay, Settings
    state/        # Zustand session ストア
  configs/        # ロボット, teleop, mapper, camera YAML
  scripts/        # 起動スクリプト, キャリブ, sim ブリッジ
  tests/          # 88 テスト (unit, integration, exit criteria, API)
  MimicAno/       # スタンドアロンサブタスクアノテータ (開発中)
    docs/design.md  # パイプライン設計書
    sam3/           # SAM 3 (テキストプロンプトセグメント) クローン
```

## MimicAno — サブタスクアノテータ

`MimicAno/` は MimicRec から呼べるスタンドアロン Python パッケージで、録画したエピソードをレビュー済みサブタスクセグメントへ変換します。

パイプライン: 信号ベース境界検出 → SAM3 物体追跡 → クリップ分割 → Gemma 4 VLM ラベリング（許可ラベルのみ）→ 時系列スムージング → 人間レビュー UI。

設計の詳細は `MimicAno/docs/design.md` を参照。実装中で、現在の `/api/datasets/...` 配下のアノテートエンドポイントは MimicAno 統合までのつなぎです。

## ライセンス

TBD
