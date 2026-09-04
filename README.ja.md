# MimicRec

双腕・モバイルマニピュレータ向けの構成とSE(3)表現は
[SE3Delta Motion Graph](docs/motion-graph.md)を参照してください。

[English](README.md) | [日本語](README.ja.md)

ロボットアームから模倣学習用データセットを集めるためのローカルファースト Web アプリ。テレオペ・ハンドティーチ・録画・レビュー・リプレイ・書き出しまでブラウザ完結。すべて LeRobot v3 形式で保存されます。

**🚀 ライブデモ: https://takaki-maeda-99.github.io/MimicRec/** — Record → Episodes → Replay のコアフローをブラウザだけで体験（モックビルド・ハードウェア不要）。Settings / Inference / Cloud / Export は無効化されているため、フル機能はローカルで動かしてください。

---

## できること

- **テレオペレーション**: SO-Leader / キーボード / Meta Questコントローラ / シミュレータから SO-101・reBotArm・Sim ロボットを操作して軌道を録画
- **ハンドティーチ**: 純コンプライアンス重力補償でロボットを手で動かして教示（reBotArm）。グリッパも摩擦補償付き
- **録画 → レビュー → 保存**: success / failure ラベル付きで保存、要らないテイクは破棄
- **リプレイ**: アーム + グリッパを録画通りに再生。フレーム間 setpoint 補間 + 安全ウォッチドッグ付き
- **VLA 推論**: HTTP コントラクト経由で Vision-Language-Action モデルを実機に走らせる
- **書き出し**: LeRobot v3 zip / VLA-compat zip（ダウンロード or ローカル保存）/ Hugging Face Hub push
- **設定 UI**: デバイス検出・キャリブ状態・アダプタ config 編集（カメラは V4L2 ケイパビリティから選択）

### 対応ハードウェア

| Robot | インターフェース | ハンドティーチ | 状態 |
|-------|-----------------|----------------|------|
| SO-101 | LeRobot `SOFollower` (Feetech STS3215) | — | 動作確認済み |
| SO Leader | LeRobot `SOLeader` テレオペ | — | 動作確認済み |
| reBot Arm B601-DM (+ グリッパ) | `reBotArm_control_py` via ZMQ デーモン | 重力補償 + グリッパ摩擦補償 | 動作確認済み |
| Meta Quest 3/3S | Unity + ROS 2 Pose/Joyブリッジ | — | 実装済み・実機統合確認待ち |
| Isaac Sim (任意ロボット) | ZMQ ブリッジ | 対応 | 動作確認済み (Franka) |
| Mock | 内蔵モックアダプタ | 対応 | テスト用 |

---

## かんたんな構造

```
Browser (React :5173)  ←→  FastAPI + WebSocket (:8000)  ←→  SessionManager  ←→  Hardware / Sim
                                                                ↓
                                                          LeRobot v3 dataset
```

- **Backend**: Python 3.12, FastAPI, asyncio 制御ループ, LeRobot v3 writer
- **Frontend**: React 19, TypeScript, Vite, TailwindCSS, TanStack Query

```
MimicRec/
  backend/mimicrec/        FastAPI + 制御ループ + データセット書き込み
    adapters/              ロボット & teleop アダプタ
    api/                   FastAPI ルート + WebSocket ハブ
    cameras/               CameraManager, OpenCV / Sim カメラ
    cloud/                 Hugging Face Hub push
    inference/             VLA HTTP クライアント + 制御ループ
    kinematics/            URDF ベース順運動学 (EE 列の生成)
    mappers/               teleop → ロボットコマンド変換
    recording/             ライタ, parquet, metadata
    session/               SessionManager, 制御ループ, リプレイ
  frontend/                React UI (Datasets / Record / Episodes / Replay / Inference / Settings)
  configs/                 ロボット・teleop・mapper・camera・inference・rebotarm YAML
  scripts/                 起動・キャリブ・sim ブリッジ・rebotarm デーモン
  integrations/ros2/       Meta Quest姿勢・Joy入力 + カメラROS 2ブリッジ
  third_party/             固定バージョンのサードパーティ Git submodule
    lerobot/               SO-101 対応版 LeRobot フォーク
    reBotArm_control_py/   reBotArm 制御 SDK
    ROS-TCP-Endpoint/      Unity ↔ ROS 2通信
    unity_ros_teleoperation/ Quest XRアプリ
  docs/                    アーキテクチャ / Quest手順 / VLAサーバ仕様
  tests/                   unit / integration / API / exit-criteria
```

---

## 使い方

### セットアップ

**Ubuntu 22.04** で動作確認済み。

```bash
git clone --recurse-submodules git@github.com:takaki-maeda-99/MimicRec.git
cd MimicRec
bash scripts/setup.sh
```

（`--recurse-submodules` を忘れても `setup.sh` が submodule を取ってきます。）

冪等です。apt パッケージ・`uv`・Python 3.12・backend と LeRobot の依存・Node 20 + pnpm + frontend 依存・`dialout` / `video` グループ追加まで全部やります。

オプション: `--no-system` (apt とグループ変更をスキップ、sudo プロンプトなし) / `--no-frontend` (Node・frontend をスキップ)。

### 起動

```bash
bash scripts/run.sh
# Backend:  http://localhost:8000
# Frontend: http://localhost:5173
```

別々に立ち上げたい場合は `scripts/run_backend.sh` / `scripts/run_frontend.sh`。

reBotArm daemon と Quest ROS 2 bridge を Settings 画面から管理する場合は、
ホストごとに一度だけユーザーサービスをインストールしてからバックエンドを再起動します:

```bash
bash scripts/install_user_services.sh
bash scripts/run.sh
```

リポジトリの絶対パスはインストール時に解決されます。ユニットはログイン時の自動起動を
有効にせず、root 権限も使用しません。アンインストールは
`bash scripts/install_user_services.sh --uninstall` です。ラボ内利用を前提としてUI認証はありませんが、
サービス操作APIはローカルUIプロキシ、明示したCORS Origin、固定ユニットだけに制限されます。

別端末からUIを開く場合は、バックエンド起動前にそのOriginを明示します（`*`は使用しません）:

```bash
export MIMICREC_CORS_ORIGINS=http://192.168.1.20:5173
```

### SO-101 テレオペ

最初に一度だけキャリブレーション。`id` は `configs/robot/so101.yaml` と `configs/teleop/so_leader.yaml` の `id:` と完全一致させる必要があります:

```bash
.venv/bin/python scripts/calibrate_so101.py \
    --port /dev/ttyACM0 --id my_follower --type follower
.venv/bin/python scripts/calibrate_so101.py \
    --port /dev/ttyACM1 --id my_leader   --type leader
```

中央位置に動かして Enter → 各関節を可動域いっぱい動かして Enter。既存のキャリブを上書きしたい場合は `--force`。キャリブは `~/.cache/huggingface/lerobot/calibration/` 配下に保存されます。

USB の差し直しでポートが入れ替わることがあります。物理アームと port の対応は `scripts/identify_arms.py` で確認できます（片方だけ手で動かす → 値が変化した方）。

UI 側では Robot: `so101` / Teleop: `so_leader` / Mapper: `identity` / Cameras: `front`, `wrist` (任意) を選択。

> 診断・キャリブ系スクリプトはバックエンドにアクティブなセッションがあると拒否します（シリアル競合防止）。先に `curl -X POST http://localhost:8000/api/session/end`。

### reBotArm

`reBotArm_control_py` は Python 3.10 必須なので、3.12 のバックエンド venv とは別に専用 venv が要ります。`setup.sh` は `reBotArm_control_py` submodule が存在するときに `.venv-rebotarm` を自動で作ります。推奨の起動方法は Settings → Managed services です。ターミナルから直接起動する場合:

```bash
.venv-rebotarm/bin/python -m rebotarm_daemon \
    --config configs/rebotarm_daemon.yaml
```

UI で `robot=rebotarm` を選択すると Record ページに大きな赤い E-stop が出ます。デーモンが 500Hz アーム + 100Hz グリッパの制御ループを保持し、モータは常時 MIT モードで稼働（リプレイ/テレオペ用 POSITION モードは MIT + 強い kp + 重力 FF の別名）。起動時点で実機へ接続して重力補償に入るため、UI は作業空間・支持・物理 enable switch の確認を要求します。管理サービスではenable switchの初期化失敗をfail-closedとし、ハードクラッシュ後も自動再起動しません。録画・リプレイ・推論セッション中の停止や再起動は API 側で拒否されます。手動起動済みdaemonがある場合は`external process`として検出し、二重起動を拒否します。

設定ファイルとチューニング項目は[こちら](#rebotarm-デーモン設定)。

### Meta Quest 3/3S テレオペ

Questコントローラ姿勢をUnity・ROS 2経由でMimicRecのCartesian mapperへ送り、MimicRecのカメラpreviewを圧縮ROS ImageとしてQuestへ返します。右グリップのhold-to-moveデッドマン方式で、入力停止・通信断時にも停止します。

```bash
bash scripts/setup_quest_ros2.sh
# 以後は Settings → Managed services から起動、または:
bash scripts/run_quest_ros2.sh
```

Recordでは Robot `rebotarm`、Teleop `quest_ros`、Mapper `delta_ee_to_rebotarm`、preview有効を選択します。ビルド・座標合わせ・安全確認・Quest内操作は [`docs/quest3/`](docs/quest3/README.md) を参照してください。

### Isaac Sim

```bash
# ターミナル1: シムブリッジ起動
~/isaacsim/python.sh scripts/sim_bridge_isaacsim.py --robot franka --headless

# ターミナル2: MimicRec 起動
bash scripts/run.sh
```

UI で Robot: `sim_franka` / `sim_so101`、Camera: `sim_front` を選択。Isaac Sim なしのテスト用には `scripts/sim_bridge_dummy.py`（ダミーシム on :5556）。

### キーボードショートカット (Record ページ)

| キー | 動作 |
|------|------|
| `Space` | `ready` → 開始 / `recording` → 停止 / `review` → **Success として保存** |
| `F` | `review` → **Failure として保存** |
| `D` | `review` → 破棄 |
| `Esc` | 自動サイクルをキャンセル |

自動サイクルモード（Record フォームでトグル）: Duration 秒録画 → Review window 秒の介入猶予 → 自動で次のエピソードを開始。

### Web UI ページ

| パス | 説明 |
|------|------|
| `/datasets` | データセット一覧・作成・ダウンロード |
| `/record` | セッション設定 → 録画 → レビュー → 保存 |
| `/datasets/:ds/episodes` | エピソード表・削除・アノテーション |
| `/datasets/:ds/episodes/:idx/replay` | 動画再生・実機リプレイ |
| `/inference` | VLA モデルを実機に走らせる (start/stop, 指示文, 状態表示) |
| `/settings` | デバイス検出・config 編集・キャリブ状態 |

---

## 必要な説明

### EE 座標を記録に含める

`configs/robot/so101.yaml` の `kinematics:` ブロックで `configs/urdf/so101/so101.urdf` から順運動学を計算し、parquet 各行に `observation.state.ee_pos / ee_rotvec`・`action.ee_pos / ee_rotvec`・`gripper_pos` 列が自動で追加されます。不要ならコメントアウト。`kinematics` extra が必要です（`setup.sh` がデフォルトで入れます）:

```bash
uv pip install --python .venv/bin/python -e "./backend[kinematics]"
```

### データセット形式 (LeRobot v3)

```
datasets/my_dataset/
  meta/
    info.json                              # v3 schema with features
    tasks.parquet
    episodes/chunk-000/file-000.parquet
  data/chunk-000/
    episode_000000.parquet
    episode_000001.parquet
  videos/chunk-000/observation.images.front/
    episode_000000.mp4
```

### Hugging Face Hub に push

`huggingface-cli login` でトークンをセット後、Datasets タブの「▸ Hub」を展開し「Configure Hub」から `<user-or-org>/<dataset-name>` を入力（private がデフォルト）。「Push to HF Hub」で手動 push、Auto-push を ON にすると 1 エピソード保存ごとに自動 push。

LeRobot v3 native 形式でアップロードされ、別マシンから読み込めます:

```python
from lerobot.datasets.lerobot_dataset import LeRobotDataset
ds = LeRobotDataset.from_pretrained("<user>/<dataset-name>")
```

### VLA 推論

MimicRec は HTTP で公開された任意の Vision-Language-Action モデルから実機を動かせます。`configs/inference/*.yaml` のコントラクトがリクエストの組み立て方（カメラ・proprio 状態・指示文）と、チャンク化された action レスポンスの解釈（座標系・単位・正規化統計）を記述します。

- スキーマ詳細: [`configs/inference/README.md`](configs/inference/README.md)
- リファレンス契約: [`configs/inference/gemma_libero_v1.yaml`](configs/inference/gemma_libero_v1.yaml)
- VLA サーバ実装側の要求仕様: [`docs/vla-server-contract-prompt.md`](docs/vla-server-contract-prompt.md)

MVP は `ee_delta` action（6-DoF EE 差分 + グリッパ）+ `mean_std` / `minmax_neg1_pos1` 正規化、次チャンク半消費プリフェッチ、RECORDING 中のオプション `done` 自動停止 をサポート。

### reBotArm デーモン設定

トップレベルの `configs/rebotarm_daemon.yaml` と、上流 submodule からコピーする HW 固有 config を編集します:

```bash
cp third_party/reBotArm_control_py/config/arm.yaml     configs/rebotarm/arm.yaml
cp third_party/reBotArm_control_py/config/gripper.yaml configs/rebotarm/gripper.yaml
```

`configs/rebotarm/arm.yaml` のモータ ID / channel を実機に合わせます。デーモン側の主なチューニング項目:

- `gravity_in_base` — ベース座標系で表したワールド重力 (m/s²)。直立 / 水平マウントなら省略 (デフォルト `[0, 0, -9.81]`)。傾斜マウントの場合はワールド重力をベース座標に回した値を入れる。**設定しないと重力補償がオペレータと逆向きに働きます。** `configs/rebotarm_daemon.yaml` に 45° 横・前傾斜の例あり。
- `gravity_comp.kd` — ハンドティーチ時の関節別ダンピング。慣性が大きい近位ほど高く。デフォルト `[1.5, 1.5, 1.0, 0.6, 0.4, 0.2]`。手放した瞬間に「飛んでいく」なら上げ、押し感が重ければ下げる。
- `position.kp / position.kd` — リプレイ時の MIT ゲイン。トラッキングをきつくしたければ上げ、コマンド着地を柔らかくしたければ下げる。
- `gripper.friction_tau_nm / vel_deadband_rad_s` — グリッパ摩擦補償。粘るなら上げ、勝手に動くなら下げる。

リプレイは録画から arm + gripper 両方を再生（parquet の `action.gripper_pos` 列が別経路でデーモンに送られます）。グリッパのない録画 / ハードウェアでは arm のみ再生。

### 拡張

#### 新規ロボット

1. `RobotAdapter` プロトコル準拠のアダプタを `backend/mimicrec/adapters/` に実装
2. `configs/robot/your_robot.yaml` に `_target_: your.module.YourAdapter` を書く
3. (任意) `Teleoperator` プロトコル準拠のテレオペレータも実装
4. UI のロボットドロップダウンに自動で出てきます

#### カメラ

`configs/cameras/*.yaml` — V4L2 経由で動くのは `OpenCVCamera` のみ（`MockCamera` / `SimCamera` はそれぞれ独自 kwargs）:

```yaml
_target_: mimicrec.cameras.opencv_camera.OpenCVCamera
name: wrist
device_id: 0
width: 1280
height: 720
pixel_format: MJPG    # 任意 — V4L2 fourcc (MJPG, YUYV, H264 など)
capture_fps: 30       # 任意 — V4L2 キャプチャレート (session の fps とは独立)
```

#### シミュレータブリッジ

ZMQ REQ/REP (port 5556) で JSON:

```python
{"cmd": "connect"}                  → {"ok": true, "dof": 6, "joint_names": [...]}
{"cmd": "read_state"}               → {"joint_pos": [...], "joint_vel": [...]}
{"cmd": "send_command", "q": [...]} → {"ok": true}
{"cmd": "disconnect"}               → {"ok": true}
```

リファレンス実装: [`scripts/sim_bridge_isaacsim.py`](scripts/sim_bridge_isaacsim.py)

---

## ライセンス

### MimicRec 本体

Apache License 2.0 — [`LICENSE`](LICENSE) 参照。

### Submodules / 同梱資産

| パス | 上流 | ライセンス |
|------|------|-----------|
| `third_party/lerobot/` | [huggingface/lerobot](https://github.com/huggingface/lerobot) のフォーク（`takaki-maeda-99/lerobot`） | Apache 2.0（Hugging Face）。一部に MIT 派生コード（Diffusion Policy / FOWM / simxarm / ALOHA）と Apache 2.0 派生コード（DETR）を含む |
| `third_party/reBotArm_control_py/` | `vectorBH6/reBotArm_control_py` のフォーク（`takaki-maeda-99/reBotArm_control_py`） | **LICENSE 未設定**（all-rights-reserved 扱い）。ハードウェア本体 [Seeed-Projects/reBot-DevArm](https://github.com/Seeed-Projects/reBot-DevArm) は CERN-OHL-W-2.0。Python 制御 SDK の再配布・改変は上流との個別調整が必要 |
| `third_party/ROS-TCP-Endpoint/` | `leggedrobotics/ROS-TCP-Endpoint`（`main-ros2`） | Apache 2.0 |
| `third_party/unity_ros_teleoperation/` | `leggedrobotics/unity_ros_teleoperation` | BSD 3-Clause |
| `configs/urdf/so101/` | TheRobotStudio SO-ARM100 を [onshape-to-robot](https://github.com/Rhoban/onshape-to-robot) で生成 | Apache 2.0（元設計） |

### 主要ランタイム依存

**Backend (Python)**: FastAPI / Pydantic (MIT); Uvicorn / PyAV / NumPy / SciPy / OmegaConf (BSD-3-Clause); PyArrow / OpenCV-Python / huggingface_hub (Apache 2.0); placo (MIT, `kinematics` extra のみ)

**Frontend (Node)**: React / React Router / Vite / TailwindCSS / TanStack Query / Zustand / Recharts / clsx / tailwind-merge / msw (MIT); lucide-react (ISC); class-variance-authority / TypeScript (Apache 2.0)

完全な推移依存ツリーは `backend/pyproject.toml` / `backend/uv.lock` / `frontend/package.json` / `frontend/pnpm-lock.yaml` を参照。
