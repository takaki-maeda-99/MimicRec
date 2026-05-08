# GoPro Hero 11 recording integration — design

## Problem

MimicRec は今 `OpenCVCamera`（V4L2 UVC）でしかカメラ収録を扱えない。広角・高画質・手振れ補正・各種センサ（IMU/温度/GPS）を一緒に録りたいケースで、GoPro Hero 11 を「もう1つのカメラ」として LeRobot v3.0 形式に並べて記録できるようにしたい。

GoPro は通常の UVC カメラと違い、

- フレームを host が逐次 read する API ではなく **SDカードに自身で録画する**
- ライブ映像は別系統で **UDP MPEG-TS の低解像度プレビュー**として流れる
- IMU 等は録画 MP4 の **GPMF (GoPro Metadata Format) トラックに同梱**される
- USB 接続は **MTP/独自プロトコルではなく USB-CDC-NCM（仮想イーサ）+ HTTP + mDNS**（`open_gopro.WiredGoPro` の中身）
- 録画ファイルは ~4GB（FAT32 制限）で **自動的に chapter 分割**される

ため、既存の `Camera.read() -> Frame` モデルにそのまま乗らない。専用の抽象を入れて既存パイプラインと共存させる。

加えて、現行 MimicRec は `OpenCVCamera` で `width / height / pixel_format / capture_fps` を YAML で指定し、**Settings UI の構造化フォーム**から選択できる UX が **既に実装済**（spec: `2026-05-09-camera-capability-selection-design.md`）。GoPro 側もユーザー視点では **同じ UX**（解像度を選んで保存）にしたい。GoPro が native でサポートしない解像度には**ダウンスケール**で対応する。

## Goals

1. 1 台以上の GoPro Hero 11 を `configs/gopros/*.yaml` で宣言でき、session 起動で自動接続される。
2. YAML スキーマは **OpenCVCamera と同じ** `width / height / fps`（+ `aspect_mode`）。`recording_preset` のような GoPro 内部概念を表に出さない。
3. ユーザー指定の `(width, height, fps)` を満たす **最小の native preset**を内部で自動選択して録画する。
4. native preset と target resolution が異なる場合は **DLWorker が ffmpeg で downscale**（GPMF を保持）して dataset に置く。
5. エピソード start/stop に追従して GoPro 側も録画 start/stop し、SDカードに 1 episode = 1 MP4 を作る（chapter 制限内）。
6. その MP4 を **非同期** にホストへ pull し、LeRobot 形式の `videos/observation.images.<gopro_name>/chunk-XXX/episode_XXXXXX.mp4` に配置する。
7. 操作者が収録中に GoPro の構図を確認できるよう、UDP プレビューを既存のカメラプレビュー UI に出す（preview-only — episode parquet には絶対に書かない）。
8. 収録途中でアプリがクラッシュ／停止しても、SD 上に残っている MP4 を後から拾い直して該当 episode に紐付けられる（永続キュー）。
9. IMU 等のセンサデータは **MP4 の GPMF トラックに埋め込まれたまま保持**し、`info.json` にその存在をマーカーとして記録する（downscale 後も GPMF は保持）。

## Definition of done

実装完了の判定は以下の全項目を満たすこと：

- [ ] `configs/gopros/<name>.yaml` を作って session を起動すると、GoPro が USB 接続され、UI のプレビューに UDP 映像が流れる。
- [ ] YAML で `width=1280, height=720, fps=30` 指定 → 内部で `1080p_30_wide` 録画 → DL → ffmpeg で 1280×720 にスケール → `videos/observation.images.<gopro_name>/chunk-000/episode_000000.mp4` が **指定通り 1280×720** で置かれる。
- [ ] その MP4 を `ffprobe -show_streams` すると **GPMF (handler_name `GoPro MET`) トラックが downscale 後も含まれる**。
- [ ] `info.json` の features エントリに `observation.images.<gopro_name>` があり `info.has_gpmf=true`、`shape=[height, width, 3]` が **YAML 指定値**になっている。
- [ ] YAML で `width=1920, height=1080, fps=30` 指定 → native と完全一致 → ffmpeg はストリームコピー（再エンコード回避）。
- [ ] YAML で `fps=25` 指定（Hero 11 が非対応） → instantiation 時点で `ConfigError` が上がる。
- [ ] session 中に SIGKILL → 再起動で `.pending/gopro_dl/<uuid>.json` が resume され、未取得の MP4 が dataset に揃う。
- [ ] 2 台同時運用で DL が直列化される（DLWorker のログで確認）。
- [ ] GoPro なしでも `MockGoProDevice` ベースの unit test が通る（CI 含む）。
- [ ] `Frame.preview_only=True` のフレームが `PendingEpisode` の **video writer 経路に渡らない**（row 自体は parquet に append される）。
- [ ] **長尺録画（chapter 切れ）検出**: episode 中に GoPro が chapter を切ったケース（multi-MP4 になる）で `HardwareError "chapter split detected"` が publish され、最初の chapter のみが dataset に置かれる。
- [ ] **NCM (USB-Ethernet) インタフェース未認識**ケースで `HardwareError` が publish される（環境エラーが出た時点で session 起動が止まる）。

## Non-goals (Out of scope)

- **リアルタイムに GoPro の高解像度フレームを取得**して制御ループに使うこと（構造的に不可能）。
- **フレーム単位（≤数十 ms）の時刻同期**。本設計の精度は **±1 秒程度**。
- **長尺エピソード（chapter 切れ後の 2 番目以降の chapter 結合）**。chapter が切れたら最初の chapter のみ dataset に保存し、残りは SD 上に orphan として残す（α 方針）。後続の concat / multi-file episode 対応は別 feature。
- **GoPro 設定 UI の構造化フォーム**は本 feature では入れない。`configs/gopros/*.yaml` は手書き編集（既存 Settings の JSON textarea fallback で対応可能）。**構造化 GoPro 編集 UI は後続 spec で**。
- **GPMF を別ファイルへ抽出**して parquet 化すること（MP4 内に温存する方針）。
- **Wi-Fi / BLE 経由の制御**。USB 有線のみ。
- **GoPro セッション中のホットプラグでの再接続**。session 開始時に揃っていることを前提とする。
- **複数 GoPro を 1 つの USB ハブで限界まで並列駆動**。実機検証は最大 2 台までを想定。
- **同一データセットへの並行セッション**。既存の制約踏襲、`.pending/gopro_dl/` 競合は対象外。
- 既知バグ：`dataset_layout.py:75` の OpenCV カメラ向け「`camera_resolutions` 未指定時の 480×640 デフォルト」は本 feature では直さない（本 feature は `gopro_specs` 別経路で書く）。

## Decisions summary

| 項目 | 決定 | 補足 |
|---|---|---|
| 役割 | 高品質収録 + 後処理 | リアルタイム取り込みはしない |
| 機種 | Hero 11 | `WiredGoPro` で USB 制御 |
| 録画単位 | per-episode shutter | 1 episode = 1 MP4（chapter 切れ未満のとき） |
| **Chapter 制限** | **α 方針: 制限明記、超過は警告** | preset 別の目安を doc に |
| DL タイミング | 非同期 | episode_stop はノンブロッキングで返る |
| DL 経路 | USB 有線 | Wi-Fi/BLE は使わない |
| **USB 制御プロトコル** | **CDC-NCM + HTTP + mDNS** | `open_gopro.WiredGoPro` の内部実装。MTP ではない |
| **解像度選択 UX** | **`width / height / fps` を YAML で（OpenCVCamera と同 shape）** | 内部で native preset 自動選択 |
| **指定解像度が native と異なる場合** | **DLWorker が ffmpeg で downscale**（GPMF copy 保持） | always ffmpeg を通すことで `info.json codec=libx264` に正規化 |
| **不可能な指定の扱い** | YAML load 時に `ConfigError` | fps=25, 解像度上限超など |
| **アスペクト比違い** | デフォルト 中央 crop（`aspect_mode: crop\|stretch`） | crop が学習用途で自然 |
| 時刻同期 | `set_date_time()` のみ | 精度 **±1 秒程度** |
| **`gopro_t0` の扱い** | **`episode_start_mono_ns` で代替**（host 時計） | start-time の media_list polling は構造的に動かないため廃止 |
| プレビュー | UDP MPEG-TS デコード | preview-only フラグ付き、episode parquet には絶対に入れない |
| **PyAV decode の loop ブロッキング** | **`asyncio.to_thread` で別スレッド** | demux/decode は同期 I/O ゆえ event loop 上では走らせない |
| 多台数 | N 台対応 | DL は全デバイス横断で **直列化**（実機検証は最大 2 台） |
| IMU/GPMF | MP4 内に温存（downscale 後も） | `info.json` に `has_gpmf: true` |
| クライアント所有権 | 1 デバイス = 1 SDK client | `GoProDevice` が所有、preview/recorder はその view |
| キュー永続化 | `.pending/gopro_dl/<uuid>.json` | enqueue 時 fsync + dir fsync を **executor 経由** |
| ジョブのデータセットパス | sidecar には `(cam_name, episode_index, chunk_index)` のみ保存 | DLWorker 実行時に `paths.episode_video()` で recompute |
| **gather エラー伝搬** | `return_exceptions=True` の結果を **必ず inspect** | 失敗を握り潰さず ErrorBus に publish + device.disable |
| エラー伝搬 | DL worker → ErrorBus | 既存 `HardwareError` 経路に乗せる |
| Mock | `MockGoProDevice` / `MockGoProPreviewSource` | CI で GoPro 物理接続なしでも全 flow が回る |
| Config 配置 | `configs/gopros/*.yaml` | `cameras/` とは別ディレクトリ |
| 起動順 | Registry → CameraManager | preview_source は registry が用意、CameraManager に merge して渡す |
| Disabled device | 一度ログ、以降 silent skip | `CameraManager._run_camera` の fail-open に倣う |
| **`open_gopro` API 名** | **Phase 0 verification で実機 enum**して実装に反映 | 本 spec の例は SDK 0.16 系を想定 |
| **Codec metadata 戦略** | **常に ffmpeg を通す（downscale 時 libx264 / 完全一致時 stream copy）** | `info.json codec` は再エンコード時 libx264 / コピー時 ffprobe で実 codec 取得（実装は DLWorker 側、init_dataset では暫定で libx264）|

## Architecture overview

```
┌────────────────────────────────────────────────────────────────┐
│ Session orchestrator (api/deps.py 付近, 既存)                  │
│                                                                 │
│  episode_start(idx, t_host) ──┐                                 │
│  episode_stop()           ────┤                                 │
└───────────────────────────────┼─────────────────────────────────┘
                                │
                ┌───────────────▼───────────────────────────────┐
                │ GoProDeviceRegistry (新規)                     │
                │  - 持ち物: list[GoProDevice], DLQueue,        │
                │           DLWorker, DatasetPaths              │
                │  - lifecycle: start() / stop()                │
                │  - episode_start(idx, t) / episode_stop(idx)  │
                │  - preview_sources() -> dict[name, Camera]    │
                └───────────────┬───────────────────────────────┘
                                │
            ┌───────────────────┼───────────────────────┐
            ▼                   ▼                       ▼
   ┌────────────────┐  ┌────────────────┐    ┌────────────────────┐
   │ GoProDevice    │  │ GoProDevice    │    │ MockGoProDevice    │
   │ (real)         │  │ (real)         │    │ (CI / unit tests)  │
   │ - SDK client   │  │ - SDK client   │    │                    │
   │   (NCM+HTTP)   │  │ ...            │    │                    │
   │ - 自動 preset  │  │                │    │                    │
   │   選択         │  │                │    │                    │
   └─────┬──────┬───┘  └────────────────┘    └────────────────────┘
         │      │
         │      └─────────► GoProRecorder (control plane view)
         │                    └─► DLQueue.enqueue(GoProDLJob)
         │
         └─────────► GoProPreviewSource (UDP+pyav view, Camera I/F)
                       │  (decode loop は asyncio.to_thread)
                       ▼
              CameraManager.cameras dict (新エントリ)
                       │
                       ▼
              JPEG preview fan-out (既存)
              ※ Frame.preview_only=True のため、
                PendingEpisode は無視する

  DLWorker (registry 内)
    │ FIFO で全デバイス横断 直列処理
    │
    ├─ download_file（USB-CDC-NCM 経由 HTTP）
    ├─ chapter detection（媒体上の追加 file が同 group か確認、追加 chapter は orphan）
    ├─ ffmpeg pass（downscale or stream copy、GPMF 保持）
    └─ shutil.move → dataset videos/observation.images.<gopro_name>/...
```

ポイント：

- **1 物理デバイス = 1 `GoProDevice` インスタンス = 1 SDK client**。
- **`GoProPreviewSource` は `Camera` インターフェースを実装する read-only view**。decode loop は **`asyncio.to_thread` で実行**。
- **DLWorker は全 `GoProDevice` 横断で 1 個**（直列化）。ffmpeg pass もこのワーカ内で連続で走る。
- **`GoProDeviceRegistry` は CameraManager と peer**。registry を **先に start** して preview_sources を集めてから CameraManager を構築する。
- **USB 制御の実体は CDC-NCM（仮想イーサ）+ HTTP**。Linux 側の network manager / firewall / udev / autosuspend が絡む。

## Resolution selection and downscale

ユーザーは YAML で `(width, height, fps)` を指定する。GoPro 内部の preset 名は隠蔽する。

### 内部解決ロジック（`GoProDevice.__init__` 内）

1. **preset 検索**: 内部 native preset 表から、以下を全部満たす **最小の preset** を選ぶ：
   - native_w ≥ target_w
   - native_h ≥ target_h
   - native_fps == target_fps
2. **完全一致** (native_w == target_w, native_h == target_h): downscale 不要。ffmpeg は `-c:v copy` で stream copy。
3. **native > target**: ffmpeg で `-c:v libx264` 再エンコード + `-vf scale` で downscale。GPMF は `-c:d copy` で持ち越し。
4. **適合 preset 無し** (target が native max を超える、fps が non-native など): YAML load 時に **`ConfigError`** を上げる。session 起動が止まる。

### Native preset 表（実装時に Phase 0 verification で確定する）

Phase 0 で実機 + `get_camera_capabilities()` から enum し、コード内に固定。以下は **代表的な出発セット**（Hero 11 US firmware）：

| preset name (SDK 内部) | width | height | fps | native_codec | chapter ~ |
|---|---|---|---|---|---|
| `1080p_30_wide` | 1920 | 1080 | 30 | h264 | ~24 min |
| `1080p_60_wide` | 1920 | 1080 | 60 | h264 | ~12 min |
| `1080p_120_wide` | 1920 | 1080 | 120 | h264 | ~6 min |
| `2.7K_60_wide` | 2704 | 1520 | 60 | h264 | ~8 min |
| `2.7K_120_wide` | 2704 | 1520 | 120 | h264 | ~4 min |
| `4K_30_wide` | 3840 | 2160 | 30 | h265 | ~7 min |
| `4K_60_wide` | 3840 | 2160 | 60 | h265 | ~4 min |
| `5.3K_30_wide` | 5312 | 2988 | 30 | h265 | ~5 min |
| `5.3K_60_wide` | 5312 | 2988 | 60 | h265 | ~3 min |

### アスペクト比違い

`aspect_mode: crop` (default) または `stretch`。

- `crop`: ffmpeg `-vf "scale=W:H:force_original_aspect_ratio=decrease,crop=W:H"` — 中央クロップ。学習用途で自然。
- `stretch`: ffmpeg `-vf "scale=W:H"` — 単純スケール（歪む）。

`pad`（黒帯）は学習データに不適なので非サポート。

### Codec metadata 戦略

ffmpeg を **常に通す**ことで dataset 上の MP4 codec を制御可能にする：

- **downscale 時** → libx264 で再エンコード → `info.json codec=libx264` で正解
- **完全一致時** (`-c:v copy`) → 元の GoPro codec（h264/h265）が保持される

実装簡略化のため、**`init_dataset` の features 書き込み時点では `"video.codec": "libx264"` を仮置き**する。完全一致 stream copy で h265 だった場合、metadata と実 codec がズレうるが本 spec では許容（後続 spec で post-DL ffprobe による正確化を検討）。downscale ケース（target 解像度を意図的に下げる典型）では正解。

### 例

| YAML 指定 | 選択 native preset | downscale 必要 | dataset 上の解像度 |
|---|---|---|---|
| 1920x1080@30 | `1080p_30_wide` | No (stream copy) | 1920×1080 |
| 1280x720@30 | `1080p_30_wide` | Yes | 1280×720 |
| 640x480@30 | `1080p_30_wide` | Yes | 640×480 |
| 1280x720@60 | `1080p_60_wide` | Yes | 1280×720 |
| 1920x1080@25 | （なし）→ `ConfigError` | — | — |
| 7680x4320@30 | （なし）→ `ConfigError` | — | — |
| 2704x1520@60 | `2.7K_60_wide` | No (stream copy) | 2704×1520 |

## Chaptered recording handling (α 方針)

GoPro は SD 上のファイルが ~4GB（FAT32 制限）に達すると自動で次の chapter ファイルへ切り替わる。

### 方針

1. **エピソード長制限を doc 化**（README + spec）。preset ごとの目安を表で。
2. **chapter 切れを DLWorker / Recorder が検出**:
   - `episode_start` 時の `before_files` snapshot と `episode_stop` 時の差分から **新ファイル群**を抽出。
   - 新ファイル数 ≥ 2 で **同一 chapter group**（GoPro chapter group は **末尾 4 桁の数字が共通、先頭 2 桁が `01..02..03` と増える**: 例 `GH010001.MP4` / `GL020001.MP4` / `GX030001.MP4`）→ chapter split とみなす。
3. **検出時の挙動**:
   - **最初の chapter のみ DL → ffmpeg pass → dataset に置く**。
   - 残りの chapter は **SD 上に orphan として残置**（手動 pull 案内を README に）。
   - `HardwareError("warning", "chapter split detected for episode N: only first chapter saved, additional chapters left on SD")` を ErrorBus に publish。
4. **将来拡張**: 全 chapter を ffmpeg-concat で 1 MP4 にまとめる対応は別 spec。

## Components

### `backend/mimicrec/gopro/types.py`（新規）

```python
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class GoProSpec:
    """info.json features 用の resolved 値（YAML target = downscale 後）。
    `gopro/types.py` に置く理由: `recording/dataset_layout.py:init_dataset` が
    `GoProSpec` をパラメータで受ける。`recording/` → `gopro/types.py` の一方向
    依存に留め、`gopro/device.py`（重い import: open_gopro 等）への循環を避ける。"""
    name: str
    width: int           # YAML target（downscale 後の解像度）
    height: int          # 同上
    fps: int
    codec: str           # 暫定 "libx264"（ffmpeg 経由前提）


@dataclass
class MediaItem:
    filename: str        # "GX010001.MP4" 形式
    size: int
    mtime_ns: int        # camera-clock 由来


@dataclass(frozen=True)
class NativePreset:
    """GoPro 内部 preset 表のエントリ。Phase 0 verification で固定。"""
    name: str            # human readable
    sdk_id: int          # open_gopro の preset ID
    width: int
    height: int
    fps: int
    native_codec: str    # "h264" or "h265"（参考用）
    chapter_seconds: int # 4GB 到達までの目安
```

### `backend/mimicrec/gopro/device.py`（新規）

```python
class GoProDevice:
    """1 物理カメラを表す。SDK client の所有者。"""

    def __init__(
        self,
        name: str,
        usb_serial: str,
        width: int,
        height: int,
        fps: int,
        aspect_mode: str = "crop",     # "crop" or "stretch"
    ) -> None:
        """preset 選択を __init__ で行う。適合 preset 無しなら ConfigError。"""

    @property
    def name(self) -> str: ...
    @property
    def usb_serial(self) -> str: ...
    @property
    def is_disabled(self) -> bool: ...
    @property
    def selected_preset(self) -> NativePreset:
        """この device が録画する native preset。"""
    @property
    def aspect_mode(self) -> str: ...

    def get_spec(self) -> GoProSpec:
        """YAML target 値を返す（downscale 後、info.json に書く値）。"""

    async def connect(self) -> None:
        """順序:
          1. WiredGoPro を初期化
             - 内部で USB-CDC-NCM 経由 HTTP セッションを確立
             - mDNS で GoPro hostname を resolve
          2. set_date_time(now)
          3. video モードへ切替
          4. selected_preset を適用（SDK の load_preset 系）
          5. get_camera_state を見て storage_remaining が閾値（500MB）以下なら
             FatalHardwareError を上げる
          UDP preview は **ここでは開始しない**（GoProPreviewSource 側が start）。
          失敗時は disable() + HardwareError publish（registry 側で gather 結果 inspect）。"""

    async def disconnect(self) -> None: ...

    # control plane（GoProRecorder が呼ぶ）
    async def shutter_on(self) -> None: ...
    async def shutter_off(self) -> None: ...

    async def media_list(self) -> list[MediaItem]:
        """SD カード上のファイル一覧。"""

    # preview plane（GoProPreviewSource が呼ぶ）
    async def start_preview(self, port: int) -> None: ...
    async def stop_preview(self) -> None: ...

    # DL plane（DLWorker が呼ぶ）
    async def download_file(self, sd_filename: str, dest: Path) -> None: ...
    async def get_storage_remaining(self) -> int: ...

    def disable(self, reason: str) -> None:
        """以後 shutter/preview/download を no-op にする。一度だけログ出力。"""
```

`__init__` で `(width, height, fps)` から `selected_preset` を resolve する。`_NATIVE_PRESETS: list[NativePreset]` をモジュール定数で持ち、Phase 0 verification 後に確定。

### `backend/mimicrec/gopro/preview.py`（新規）

```python
class GoProPreviewSource:
    """Camera I/F 実装。device の SDK 経由で preview start を依頼し、
    UDP MPEG-TS を pyav でデコードして preview frame を返す。
    Frame.preview_only=True を立てる。"""

    name: str   # = device.name

    def __init__(self, device: GoProDevice, udp_port: int): ...

    async def connect(self) -> None:
        """device.start_preview(udp_port) → UDP socket を bind →
        pyav の InputContainer を **`asyncio.to_thread` で別スレッド**で開いて
        decode loop を回す。decode した最新フレームを asyncio.Queue(maxsize=1) に
        push（drop-on-full）。device が disabled なら no-op。"""

    async def disconnect(self) -> None:
        """device.stop_preview() → UDP source 終了 → pyav ループは EOF / IOError で
        抜ける → thread join。最大 2 秒待ち、超過したら諦め。"""

    async def read(self) -> Frame:
        """asyncio.Queue から最新フレームを取る。
        device.is_disabled の状態では: 永久に解放されない `asyncio.Event` を
        await して clean idle 状態（cancel まで block、HardwareError spam を回避）。"""
```

UDP ポートは registry が **デバイスごとに別ポートを割り当てる**（ベース 18556 + index）。

### `backend/mimicrec/gopro/recorder.py`（新規）

```python
@dataclass
class _EpisodeState:
    episode_index: int
    episode_start_mono_ns: int

class GoProRecorder:
    """control plane の view。DLQueue へ enqueue する責務を持つ。"""

    def __init__(self, device: GoProDevice, dl_queue: DLQueue, paths: DatasetPaths): ...

    async def start_episode(self, episode_index: int, t_host_mono_ns: int) -> None:
        """device が disabled なら no-op。
        1. before_files = media_list snapshot（known_files に追加）
        2. shutter_on()
        3. _EpisodeState(episode_start_mono_ns=time.monotonic_ns()) を保存
        失敗（shutter_on が IOError 等）→ device.disable()、HardwareError publish。
        ※ 旧 spec の start-time media_list polling は構造的に動かないため廃止。"""

    async def stop_episode(self, episode_index: int) -> None:
        """device が disabled なら no-op。
        1. shutter_off()（最大 3 回 retry）
        2. media_list を取り、known_files との差分から「このエピソードで作られた
           新ファイル群」を抽出
        3. **chapter 検出**:
           - 新ファイル数 ≥ 2 で同一 chapter group（末尾 4 桁共通、先頭 2 桁通し番号）
             → chapter split とみなす
           - 最初の chapter（先頭 2 桁が最小）を select、残りは known_files に追加して
             warning publish
        4. 新ファイルが 0 → HardwareError publish して enqueue skip
        5. GoProDLJob を組んで dl_queue.enqueue。
           cam_name = device.name
           chunk_index = resolve_chunk(episode_index)
           sd_filename = 選んだ chapter
           episode_start_mono_ns = state.episode_start_mono_ns
           episode_stop_mono_ns = time.monotonic_ns()
           **dest path は持たない** — DLWorker 実行時に paths.episode_video() で recompute。"""
```

### `backend/mimicrec/gopro/dl_queue.py`（新規）

```python
@dataclass
class GoProDLJob:
    """sidecar JSON に直結する schema。dest path は持たない。"""
    job_id: str                      # uuid4
    gopro_serial: str
    sd_filename: str
    episode_index: int
    chunk_index: int
    cam_name: str
    episode_start_mono_ns: int
    episode_stop_mono_ns: int

    def to_json(self) -> dict: ...
    @classmethod
    def from_json(cls, d: dict) -> "GoProDLJob": ...

class DLQueue:
    """`.pending/gopro_dl/<job_id>.json` への永続化付きキュー。
    全ファイル I/O は `asyncio.to_thread` で実行（event loop ブロッキング回避）。"""

    def __init__(self, pending_dir: Path):
        """pending_dir.mkdir(parents=True, exist_ok=True)。"""

    async def enqueue(self, job: GoProDLJob) -> None:
        """to_thread で:
        1. tmp パスに JSON 書き込み + os.fsync(file)
        2. atomic rename (os.replace)
        3. dir fsync（atomic rename の永続化保証）
        その後 in-memory asyncio.Queue に積む。"""

    async def dequeue(self) -> GoProDLJob: ...

    async def mark_done(self, job_id: str) -> None:
        """to_thread で sidecar JSON を削除 + dir fsync（既に無くてもエラーにしない）。"""

    @classmethod
    def restore(cls, pending_dir: Path) -> "DLQueue":
        """1. pending_dir.mkdir
           2. pending_dir/*.json を読み GoProDLJob に戻す（ロード順 = ファイル名 sort 順）
           3. in-memory queue にすべて積む"""
```

### `backend/mimicrec/gopro/dl_worker.py`（新規）

```python
class GoProDLWorker:
    """全デバイス横断で 1 個。DL を直列化する。"""

    def __init__(
        self,
        queue: DLQueue,
        devices: dict[str, GoProDevice],   # serial -> device
        paths: DatasetPaths,
        errors: ErrorBus,
        shutdown_grace_sec: float = 30.0,
    ): ...

    async def run(self) -> None:
        """ループ:
          job = await queue.dequeue()
          device = devices.get(job.gopro_serial)
          if device is None or device.is_disabled:
              errors.publish(HardwareError(...))
              continue   # sidecar 残置 → 次セッション再試行

          tmp_raw = paths.pending_dir / f'gopro_dl_{job.job_id}_raw.mp4'
          tmp_out = paths.pending_dir / f'gopro_dl_{job.job_id}_out.mp4'

          # Resume-from-tmp: 前回の DL 完了後の move で失敗したケース
          skip_dl = (
            tmp_raw.exists()
            and tmp_raw.stat().st_size > 0
            and (await _matches_sd(device, job.sd_filename, tmp_raw.stat().st_size))
          )
          if not skip_dl:
              await device.download_file(job.sd_filename, tmp_raw)

          # Duration check（"録画ロス" の片側だけ警告する）
          # episode_start_mono_ns は host 時計で実際の record start より 100-300ms
          # 遅い、shutter_off も同じく tail を持つ → 健全な MP4 は expected より
          # やや短い。**2.0 秒以上短い** を threshold に。
          duration = await asyncio.to_thread(probe_mp4_duration, tmp_raw)
          expected = (job.episode_stop_mono_ns - job.episode_start_mono_ns) / 1e9
          if duration < expected - 2.0:
              await errors.publish(HardwareError(
                  f'GoPro recording shorter than episode: ep {job.episode_index} '
                  f'duration={duration:.3f}s expected≈{expected:.3f}s'))

          # ffmpeg pass: downscale or stream copy
          spec = device.get_spec()
          native = device.selected_preset
          if native.width == spec.width and native.height == spec.height:
              await ffmpeg_copy(tmp_raw, tmp_out)
          else:
              await ffmpeg_downscale(
                  tmp_raw, tmp_out,
                  target_w=spec.width, target_h=spec.height,
                  aspect_mode=device.aspect_mode,
              )
          tmp_raw.unlink(missing_ok=True)

          dest = paths.episode_video(job.chunk_index, job.cam_name, job.episode_index)
          dest.parent.mkdir(parents=True, exist_ok=True)
          shutil.move(str(tmp_out), str(dest))
          await queue.mark_done(job.job_id)

        例外発生時: sidecar / tmp_raw 残置 → ErrorBus publish → continue（worker 自体は死なない）
        """

    async def stop(self) -> None:
        """1. 受信停止フラグを立てる（dequeue は cancel）
           2. in-flight job がいたら shutdown_grace_sec まで待つ
           3. 経過したら job task を cancel（sidecar / tmp_raw 残置 → resume）"""
```

### `backend/mimicrec/gopro/ffmpeg_pass.py`（新規）

```python
async def ffmpeg_copy(src: Path, dst: Path) -> None:
    """全 stream を stream copy で dst にコピー（GPMF 維持、再エンコードなし）。"""
    cmd = ["ffmpeg", "-y", "-i", str(src), "-map", "0", "-c", "copy", str(dst)]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    rc = await proc.wait()
    if rc != 0:
        raise HardwareError(f"ffmpeg_copy failed: {(await proc.stderr.read()).decode()}")

async def ffmpeg_downscale(
    src: Path, dst: Path,
    target_w: int, target_h: int,
    aspect_mode: str,
) -> None:
    """video を libx264 で再エンコード + scale。GPMF data stream は -c:d copy で維持。"""
    if aspect_mode == "crop":
        vf = f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,crop={target_w}:{target_h}"
    elif aspect_mode == "stretch":
        vf = f"scale={target_w}:{target_h}"
    else:
        raise ConfigError(f"unknown aspect_mode: {aspect_mode}")

    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-map", "0",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-vf", vf,
        "-c:d", "copy",
        "-an",
        str(dst),
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    rc = await proc.wait()
    if rc != 0:
        raise HardwareError(f"ffmpeg_downscale failed: {(await proc.stderr.read()).decode()}")
```

### `backend/mimicrec/gopro/registry.py`（新規）

```python
class GoProDeviceRegistry:
    """session lifecycle に紐付き、全 GoProDevice を持つ。"""

    def __init__(self, devices: list[GoProDevice], paths: DatasetPaths, errors: ErrorBus):
        """asserts: 名前 / serial が一意。"""

    async def start(self) -> None:
        """1. 各 device.connect() を asyncio.gather(return_exceptions=True) で並行実行。
              **結果を必ず inspect** して、Exception は ErrorBus に publish + device.disable。
              連結を握り潰さない。
           2. DLQueue.restore(paths.pending_dir / 'gopro_dl')
           3. 各 device に対して GoProRecorder, GoProPreviewSource を生成
           4. preview_source の UDP ポートを 18556 + index で割り当て
           5. DLWorker.run() を asyncio.create_task"""

    async def stop(self) -> None:
        """1. DLWorker.stop() を await（in-flight 完了 or 30s で cancel）
           2. 各 PreviewSource.disconnect()
           3. 各 device.disconnect()
           sidecar JSON / tmp_raw は残置（次セッションで resume）"""

    async def episode_start(self, episode_index: int, t_host_mono_ns: int) -> None:
        """**`gather(return_exceptions=True)` の結果を必ず inspect**。
        例外が出た recorder の device を disable し、ErrorBus に publish。"""

    async def episode_stop(self, episode_index: int) -> None:
        """同上。"""

    def preview_sources(self) -> dict[str, "GoProPreviewSource"]: ...
    def gopro_specs(self) -> dict[str, GoProSpec]: ...
    @property
    def pending_count(self) -> int: ...
```

### `backend/mimicrec/gopro/mock.py`（新規）

```python
class MockGoProDevice:
    """SDK を import せずに動く。"""

    def __init__(
        self,
        name: str,
        usb_serial: str,
        width: int = 1920,
        height: int = 1080,
        fps: int = 30,
        aspect_mode: str = "crop",
        fixture_mp4: Path | str | None = None,    # 文字列許容、内部で Path 化
        emit_preview: bool = False,
        storage_remaining: int = 1_000_000_000,
        chapters_per_episode: int = 1,             # >1 で chapter split をシミュレート
    ): ...
```

`fixture_mp4` を `str | Path` 受け（YAML 由来 str を Hydra が渡す）→ `__init__` で `Path` に正規化。`chapters_per_episode > 1` で `shutter_off` 時に複数 file を生成して chapter テストを駆動。

### Hydra config（新規）

`configs/gopros/gopro_external.yaml`：

```yaml
_target_: mimicrec.gopro.device.GoProDevice
name: gopro_external
usb_serial: "C3441234567890"
width: 1920
height: 1080
fps: 30
aspect_mode: crop
```

### Cross-cutting changes（既存ファイルへの追加）

| ファイル | 変更内容 |
|---|---|
| `backend/mimicrec/types.py` | `Frame` に `preview_only: bool = False` フィールド追加 |
| `backend/mimicrec/recording/pending.py` | `append_row` で `frames[name].value.preview_only` をチェックし True なら video writer に渡さない（silent skip）。row 自体は append。 |
| `backend/mimicrec/recording/pending.py` | `open_video_writers` の引数 `cameras` から GoPro 由来カメラを除外する（呼び出し側責任、registry が gopro 名一覧を提供）。 |
| `backend/mimicrec/recording/dataset_layout.py` | `init_dataset` に `gopro_specs: dict[str, GoProSpec] \| None = None` を追加。`GoProSpec` は `mimicrec.gopro.types` から import。features dict に GoPro 専用エントリを書く（codec="libx264" 仮置き）。 |
| `backend/mimicrec/api/schemas.py` | `_BaseSessionRequest.gopros: list[str] = []`（後方互換 default）、`SessionStatePayload.gopros` も同。 |
| `backend/mimicrec/api/deps.py` | (1) `req.gopros` を読む、(2) `configs/gopros/<n>.yaml` から `GoProDevice` を instantiate、(3) `GoProDeviceRegistry` を構築・start、(4) preview_sources を `cams` dict に merge してから `CameraManager` を構築、(5) `init_dataset` に `gopro_specs=registry.gopro_specs()` を渡す、(6) `app.state.gopro_registry` に保存、(7) `req.cameras` から GoPro 名は除外、(8) `req.cameras` と `req.gopros` の名前空間 disjoint を assert。 |
| `backend/mimicrec/api/routes/...` | session_meta / SessionStatePayload に `"gopros": list[str]` 追加。`GET /api/session/gopro_pending` を1個追加。 |
| `backend/mimicrec/cameras/manager.py` | **変更なし**。`Frame.preview_only` は `_run_camera` で素通り。チェックは `PendingEpisode` 側でのみ行う。 |
| `frontend/src/...` | pending DL 件数バッジ。session 終了時に「N pending」が残っていたら警告ダイアログ。**GoPro 用 構造化フォームは作らない**（Settings の JSON textarea fallback で編集）。 |
| `pyproject.toml` | `open_gopro` 依存追加（Phase 0 verification 後に version pin）。 |
| `README.md` | GoPro 用セクション追加（YAML スキーマ、preset 別 chapter 制限表、NCM 環境セットアップ手順、ハードウェアテスト走らせ方、ffmpeg 必須）。 |

## Data flow

### Session 起動時

```
1. api/deps.py: load configs (cameras + gopros)
   - GoPro 系 YAML は instantiation 時点で preset 選択 + ConfigError チェック
2. instantiate GoProDevice[] from configs/gopros/
3. GoProDeviceRegistry(devices=..., paths=..., errors=error_bus)
4. await registry.start()
   ├─ asyncio.gather([d.connect() for d in devices], return_exceptions=True)
   │   - WiredGoPro init (NCM + HTTP + mDNS)
   │   - set_date_time / video モード / load_preset / storage check
   │   失敗: device.disable + errors.publish
   │   gather 戻り値も inspect、未 publish 例外を補完
   ├─ DLQueue.restore(paths.pending_dir / 'gopro_dl')
   ├─ 各 d: GoProRecorder, GoProPreviewSource 生成
   └─ DLWorker.run() を asyncio.create_task
5. preview_sources = registry.preview_sources()
6. cams = {**opencv_cams, **preview_sources}
7. CameraManager(cameras=cams, error_bus=...)
8. await camera_manager.start()
   └─ 各 cam.connect()（GoProPreviewSource は device.start_preview + UDP socket bind +
       asyncio.to_thread(decode_loop) を起動）
9. init_dataset (新規データセット時のみ) with gopro_specs=registry.gopro_specs()
10. app.state.gopro_registry = registry
```

### Episode lifecycle

```
episode_start(idx, t_host):
  await camera_manager.episode_start(idx, t_host)
  await registry.episode_start(idx, t_host)
    asyncio.gather([r.start_episode(idx, t_host) for r in recorders], return_exceptions=True)
    結果 inspect → 例外 device disable + publish

  各 recorder.start_episode の中身:
    1. before_files = media_list snapshot（known_files に追加）
    2. shutter_on()
    3. _EpisodeState(episode_start_mono_ns=time.monotonic_ns())

episode_stop(idx):
  await registry.episode_stop(idx)
    asyncio.gather + inspect

  各 recorder.stop_episode の中身:
    1. shutter_off()（最大3 retry）
    2. after_files = media_list
    3. new_files = after_files - known_files
    4. chapter detection:
       - len(new_files) >= 2 で同 group → chapter split
       - 最初の chapter を select
       - 残りは known に追加 + warning publish
    5. new file が 0 → HardwareError publish して enqueue skip
    6. GoProDLJob を組んで dl_queue.enqueue
  return immediately
```

### DLWorker ループ

`Components > GoProDLWorker.run` の pseudocode 参照（重複説明を避ける）。

### Session 終了時

```
1. registry.stop()
   ├─ DLWorker.stop()（30s grace then cancel、sidecar/tmp 残置）
   ├─ 各 PreviewSource.disconnect()（thread join 含む）
   └─ 各 device.disconnect()
2. UI に「N pending GoPro DLs」を出す
3. ユーザーに quit 警告
```

## Time sync caveat

本設計は **`set_date_time()` のみ** を使い、達成精度は **±1 秒程度**。フレーム単位の同期は出来ない。

`episode_start_mono_ns` は shutter_on 後の host 時計で、実際の GoPro recording start より **100〜500ms 程度遅れる**。`episode_stop_mono_ns` も shutter_off の RT で同程度のラグ。よって episode-level の duration check は **±数百 ms 精度しか期待できず**、threshold は **2.0 秒** に設定（短い側のみ警告）。

## Transport (USB-CDC-NCM) reality

`open_gopro.WiredGoPro` は **MTP/独自プロトコルではなく**、

- USB を物理層に
- CDC-NCM ドライバで仮想イーサインタフェース（`enxXXXXXXXXXXXX` 形式の NIC）
- DHCP/Link-local で IP 取得
- mDNS で `gopro_<serial>.local` を resolve
- そこに HTTP リクエスト

という構造で動く。Linux 側の制約：

- `cdc_ncm` モジュールがロードされている必要（標準カーネルなら入っている）
- NetworkManager が新規 NIC を **auto-managed** にしている必要（`unmanaged-devices` 設定で除外されているとつながらない）
- `avahi-daemon` が走っており mDNS が resolve できる必要
- ufw / nftables が GoPro IP を block していない（典型的に link-local `169.254.x.x` 帯）
- `usbcore.autosuspend=-1` または GoPro 個別の autosuspend 無効化

これらは **Phase 0 verification で確認** + **README に環境セットアップ手順** として記載。

## Failure handling

| 事象 | 挙動 | sidecar / tmp | 影響 |
|---|---|---|---|
| `device.connect()` 失敗（USB 認識せず／firmware 不整合） | device disable、`HardwareError` publish | — | 該当 GoPro 1台のみ影響、他カメラ無事 |
| **CDC-NCM インタフェース未認識（`cdc_ncm` 未ロード）** | `WiredGoPro` 初期化が IOError、device disable | — | dmesg / lsusb で原因確認、README 参照 |
| **NetworkManager が NIC を unmanaged 扱い** | DHCP 取れず timeout、`HardwareError` publish | — | NetworkManager.conf で除外解除 |
| **mDNS で GoPro hostname resolve 失敗** | `WiredGoPro` 初期化 timeout、`HardwareError` publish | — | avahi-daemon 再起動、firewall mDNS 通過確認 |
| **firewall が GoPro IP（169.254.x.x）block** | HTTP request timeout、`HardwareError` publish | — | ufw allow 設定 |
| **USB autosuspend で interface 切断** | session 中の任意 SDK call が IOError、device.disable | session 中は再接続しない | autosuspend 無効化を README |
| `set_video_mode()` 失敗（photo モード等） | device disable、`HardwareError` publish | — | shutter してもファイルできない事態を未然防止 |
| `get_storage_remaining < 500MB` | `FatalHardwareError` で session 起動失敗 | — | 起動時のみ |
| `shutter_on()` 失敗 | 該当 episode は GoPro 抜きで進む、`HardwareError` 警告 | — | recorder の state 無し、stop も no-op |
| **chapter 検出 (new files >= 2 で同 group)** | 最初の chapter のみ enqueue、残りは orphan、`HardwareError(severity="warning")` | — | episode 長制限超え。doc 案内に従い preset/長さを調整 |
| **stop で new file が 0** | enqueue skip、`HardwareError` publish | — | SD に MP4 残らず（録画失敗） |
| `shutter_off()` 失敗 → 3 回 retry も失敗 | `HardwareError`、enqueue skip | — | SD に MP4 残置、device は disable 候補 |
| **session 中の USB 抜け／device IOError** | shutter/preview/download いずれかで例外、device.disable() | sidecar 残置 → 次回 device 復帰で resume | 以後の episode は GoPro 抜きで進む |
| **photo/timelapse モードで GoPro 起動済み** | connect の `set_video_mode` で video に切替。失敗なら disable | — | 起動失敗で気付ける |
| DLWorker 中の `download_file` 失敗 | sidecar 残置、errors publish、worker は次の job へ | 残置 | 次回起動時 restore で再 DL |
| **`shutil.move` 失敗（cross-device、ENOSPC、EACCES）** | tmp 残置、sidecar 残置、errors publish | 残置 | 次回起動時、resume-from-tmp で move からやり直し |
| **`ffmpeg downscale/copy` 失敗** | tmp_raw 残置、sidecar 残置、errors publish | 残置 | 次回再試行（`tmp_raw` 残っていれば DL skip）。ffmpeg バイナリ未インストールは session 起動時に検出して FatalHardwareError |
| **MP4 duration が expected より 2.0s 以上短い** | `HardwareError` 警告（致命ではない）、DL は完遂 | 削除（mark_done） | record loss 疑い。長い側は許容 |
| **`pending_dir` 不在（初回起動）** | `DLQueue.restore` が `mkdir` で作成 | — | 影響無し |
| **同一データセットへの並行 session** | 検出しない（既存制約踏襲） | 不定 | README に1セッション/データセットを明記 |
| アプリクラッシュ（SIGKILL 含む） | sidecar / tmp_raw 残る → 次回 `DLQueue.restore()` で in-memory queue に再ロード、tmp_raw 残っていれば DL skip | 残置 | 全 pending が自動再開 |
| GoPro 電池切れ session 中 | shutter/download IOError → device.disable() | sidecar 残置 | 次回 device 復帰時 worker が拾う |
| **`asyncio.gather(return_exceptions=True)` 結果 inspect 漏れ** | （実装規約）`registry.start/episode_*` のテストで強制例外を入れ、ErrorBus publish が来ることを検証 | — | テストで規約担保 |

## Multi-GoPro USB realities

- DLWorker は全デバイス横断で **直列**（ffmpeg 含む）。同時 DL は不可能（実装上の保証）。
- N≥2 なら **別の USB コントローラ root**（物理的に違うチップ）に挿すことを推奨。`lsusb -t` で確認。
- DL 中（download_file + ffmpeg）の同 GoPro はプレビューが詰まることがある。frame drop は許容、`HardwareError` には**しない**。
- 各 GoPro は **個別の USB-Ethernet NIC（IP）を持つ**。複数台時に IP 競合しないことを `ip addr` で確認可能。
- 動作検証は最大 2 台まで。3 台以上は本 spec の保証範囲外。

## Pre-implementation verification

実装に入る前に **必ず実機で確認すべき項目**。各項目に明示的な Plan B を持つ：

| # | 確認内容 | Plan B if 失敗 |
|---|---|---|
| 1 | `open_gopro` の `WiredGoPro` で Hero 11 が `set_date_time` / `set_shutter` / video モード切替 / preset 適用 / `media_list` / `download_file` / preview start・stop / `get_camera_state` / `get_camera_capabilities` を全部サポートしているか（実装時点の API シグネチャを記録）| **本 spec を shelve**。BLE+USB ハイブリッド設計を別 spec で起こす |
| 2 | Hero 11 ファームウェアバージョンと `open_gopro` の互換性 | 互換ファーム版を README に pin |
| 3 | **Hero 11 の native preset 一覧 + 各 preset の (w, h, fps, codec, sdk_id) を実機で enum**（`get_camera_capabilities` または preset 名→state のマッピング） | preset 表が読めない → spec の表（出発セット）をハードコードで使い、コード内コメントに「実機検証済 firmware バージョン」を明記 |
| 4 | UDP プレビューの実コーデック・解像度・fps（pyav が扱えるか） | pyav 不可なら `ffmpeg` バイナリへの subprocess fallback |
| 5 | `shutter_on` 後の `media_list` 挙動: 録画完了まで file が出てこないことを確認（spec の polling 廃止判断の根拠） | 即時更新する場合、polling 復活で gopro_t0 をより正確にする最適化が可能（任意） |
| 6 | USB 直挿し vs ハブ経由の DL スループット差（実測） + 各 preset で 4GB に到達する時間（chapter 制限の実値）| ハブ低速なら multi-GoPro 運用 README ガイドで USB コントローラ分散推奨。chapter 制限は実測値に合わせ表を更新 |
| 7 | **Linux NCM 環境**: `cdc_ncm` ロード確認 / NetworkManager 自動管理確認 / Avahi 動作確認 / firewall (`ufw`/`nftables`) の link-local 通過確認 / autosuspend 無効化方法 | この環境準備手順を README に詳細記載 |
| 8 | **chapter 動作の実証**: 1080p60 を 4GB 超えるまで連続録画 → SD 上に 2 chapter 出来ることを確認 → media_list で group prefix が「最後 4 桁が同じ、先頭 2 桁が増える」パターンであることを確認 | パターンが違うなら chapter 検出ロジックを修正 |
| 9 | **`get_camera_state` の storage_remaining フィールド名**を実機で確認（spec の例は推測） | 実フィールド名に合わせて実装 |
| 10 | **ffmpeg の GPMF stream copy** (`-c:d copy`) が Hero 11 MP4 で動くか実機検証。`ffprobe` で出力 MP4 に GoPro MET handler が残ることを確認 | 動かないなら `-map 0 -c copy -c:v libx264 -vf scale...` 等の代替で再評価 |
| 11 | `ffmpeg` バイナリのバージョン要件（GPMF data stream copy が使える ffmpeg 4.x+）| README に `ffmpeg --version >= 4.4` を明記 |

**実装スタート判定**: 1 が PASS であれば着手可。3, 8, 9 は spec 値をパッチで合わせるだけ。10 が FAIL なら GPMF 保持戦略を見直し（最悪 raw GPMF blob を sidecar 保存）。1, 7, 10 は設計を根本から書き直すレベル。

## Testing

### Unit tests（GoPro 実機なしで CI 実行可）

- `MockGoProDevice` を使った `GoProRecorder.start_episode → stop_episode → enqueue` の通常 flow（chapter 1 つ）。
- `MockGoProDevice(chapters_per_episode=2)` で chapter 検出 → 最初の chapter のみ enqueue、`HardwareError(warning)` publish の確認。
- `MockGoProDevice` で stop 時に new file が 0 → enqueue されない、orphan ログ確認。
- `DLQueue` の永続化／restore（sidecar JSON の create/fsync/delete を tmpdir で確認、fsync 系の executor 経由実行を確認）。
- `DLWorker` の MP4 duration mismatch 検出（fixture MP4 を使う、ffmpeg は実機 ffmpeg）。
- `DLWorker` の resume-from-tmp 動作（`shutil.move` を monkeypatch して失敗 → 再起動 → tmp_raw 残ってる前提で再試行）。
- `DLWorker` の **ffmpeg downscale テスト**: 実 fixture MP4（GPMF 含む短い Hero 11 サンプル）を入力 → downscale 出力 → `ffprobe` で `(w, h)` が target 通り、GoPro MET data stream が残っていることを確認。
- `DLWorker` の **ffmpeg copy テスト** (native==target ケース): 出力が input と stream-equivalent。
- **PendingEpisode の preview_only 契約（GoPro 関与なし）**: `Frame(preview_only=True)` を直接構築 → `PendingEpisode.append_row` → video writer は呼ばれない / row は parquet に書かれる。GoPro mock 不要。
- **Preview source が preview_only=True を emit する積分テスト**: `MockGoProDevice(emit_preview=True)` を使い、CameraManager 経由で流れたフレームの `preview_only` フラグを確認（連結を切らずに）。
- `GoProDeviceRegistry` の name/serial 重複でコンストラクタが ValueError。
- **`GoProDevice.__init__` の preset 自動選択テスト**: `(width, height, fps)` の組み合わせに対して期待 preset が選ばれる。fps=25 や width 上限超で `ConfigError`。
- **`registry.episode_start/stop` の例外伝搬テスト**: 1 つの recorder が例外 → 他は完走しつつ ErrorBus publish。
- `init_dataset(gopro_specs=...)` で `info.json.features.observation.images.<gopro>.info.has_gpmf=True` + shape が **YAML target** 解像度。

### Integration tests（GoPro 実機 + USB 接続が必要）

`pytest -m gopro_hardware` で実行。CI からは除外。

- 1 台の Hero 11 で 3 episode 連続収録 → DL → ffmpeg pass → MP4 が `videos/observation.images.<name>/chunk-000/episode_*.mp4` に置かれる。
- 録画した MP4 を `ffprobe -show_streams` して `handler_name=GoPro MET` のトラックがある（GPMF 残存確認、downscale 後）。
- session 中に `kill -9 backend pid` → 再起動 → 未取得の MP4 が dataset に揃う。
- 2 台同時接続で 3 episode 録画 → DL ログを見ると 1 件ずつ順番に処理されている。
- preview UI に GoPro の映像が出ることを目視確認。
- **chapter 切れの実証**: `1080p_60_wide` で 13 分録画 → SD 上に 2 chapter → DL は最初の chapter のみ → ErrorBus に warning。
- **解像度ダウンスケール実証**: YAML で `width=1280, height=720` 指定 → 出力 MP4 が 1280×720 + GPMF 保持。
- **NCM 検証**: `ip link` / `lsusb -t` で接続を確認、`avahi-resolve -n gopro_<serial>.local` が IP を返す。

### Dev environment for integration tests

- `open_gopro==<version>` を `pyproject.toml` に pin（Phase 0 verification 後に確定）。
- Hero 11 firmware: 動作確認バージョンを README に明記。
- USB ケーブル: GoPro 純正 USB-C。
- `ffmpeg`（>= 4.4）+ `ffprobe` システムバイナリインストール済み。
- Linux: `cdc_ncm` ロード済 + NetworkManager 動作 + avahi-daemon 動作。
- Fixture MP4: `tests/fixtures/gopro/sample_episode.mp4`（短い実 Hero 11 動画、GPMF 込み、~5MB）。
- `conftest.py` で `markers = "gopro_hardware: needs physical Hero 11"`、`addopts = -m 'not gopro_hardware'`。

### CI 設定

- `.github/workflows/...` で unit tests のみ（`-m 'not gopro_hardware'`）。
- ffmpeg は CI runner にインストール（GitHub Actions の標準 image にあり）。

## Out of scope reminders

- **GPMF 抽出 / IMU を parquet 化する処理は本 feature では書かない**。
- **シャッター latency 補償のための同期信号**は本 feature では入れない。
- **GoPro 設定 UI の構造化フォーム**は本 feature では入れない（既存 JSON textarea fallback で編集）。
- **ホットプラグでの session 中 device 再接続**。
- **同一データセットへの並行 session の安全化**。
- **長尺エピソード（chapter 結合）対応**。最初の chapter のみ。multi-chapter は別 spec。
- **`info.json` codec を post-DL ffprobe で正確化**する処理。常に "libx264" 仮置き（再エンコード前提）。完全一致 stream copy で h265 だった場合の metadata 不整合は許容（後続 spec で）。
