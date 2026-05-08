# GoPro Hero 11 recording integration — design

## Problem

MimicRec は今 `OpenCVCamera`（V4L2 UVC）でしかカメラ収録を扱えない。広角・高画質・手振れ補正・各種センサ（IMU/温度/GPS）を一緒に録りたいケースで、GoPro Hero 11 を「もう1つのカメラ」として LeRobot v3.0 形式に並べて記録できるようにしたい。

GoPro は通常の UVC カメラと違い、

- フレームを host が逐次 read する API ではなく **SDカードに自身で録画する**
- ライブ映像は別系統で **UDP MPEG-TS の低解像度プレビュー**として流れる
- IMU 等は録画 MP4 の **GPMF (GoPro Metadata Format) トラックに同梱**される

ため、既存の `Camera.read() -> Frame` モデルにそのまま乗らない。専用の抽象が必要。

## Goals

1. 1 台以上の GoPro Hero 11 を `configs/cameras/*.yaml` で宣言でき、session 起動で自動接続される。
2. エピソード start/stop に追従して GoPro 側も録画 start/stop し、SDカードに 1 episode = 1 MP4 を作る。
3. その MP4 を **非同期** にホストへ pull し、LeRobot 形式の `videos/observation.images.<gopro_name>/chunk-XXX/episode_XXXXXX.mp4` に配置する。
4. 操作者が収録中に GoPro の構図を確認できるよう、UDP プレビューを既存のカメラプレビュー UI に出す。
5. 収録途中でアプリがクラッシュ／停止しても、SD 上に残っている MP4 を後から拾い直して該当 episode に紐付けられる（永続キュー）。
6. IMU 等のセンサデータは **MP4 の GPMF トラックに埋め込まれたまま保持**し、`info.json` にその存在をマーカーとして記録する。

## Non-goals (Out of scope)

- **リアルタイムに GoPro の高解像度フレームを取得**して制御ループに使うこと（構造的に不可能）。
- **フレーム単位（≤数十 ms）の時刻同期**。本設計の精度は **±1 秒程度**（後述）。タイトな同期が必要になったら別 feature で同期信号を導入する。
- GoPro 側の録画 preset（解像度/fps/視野角/HyperSmooth 等）を **UI から動的に切り替える**こと。最初は YAML で固定、SDK 経由でセッション開始時に適用する。
- **GPMF を別ファイルへ抽出**して parquet 化すること（MP4 内に温存する方針）。将来 IMU を学習に使う段階で別途 loader / 変換を書く。
- **Wi-Fi / BLE 経由の制御**。USB 有線のみ。BLE は SDK の都合で必要なら裏で使うが、運用上は USB ケーブル接続前提。
- **GoPro セッション中のホットプラグ**（接続/切断/USBポート変更）対応。session 開始時に揃っていることを前提とする。
- **複数 GoPro を 1 つの USB ハブで限界まで並列駆動**。実機検証は最大 2 台までを想定。多数同時運用時の帯域問題は運用 doc に記載するに留める。
- 既知バグ：`dataset_layout.py` の解像度 480×640 ハードコード問題は本 feature では直さない（別 spec `2026-05-09-camera-capability-selection-design.md` 側で扱う）。

## Decisions summary

| 項目 | 決定 | 補足 |
|---|---|---|
| 役割 | 高品質収録 + 後処理 | リアルタイム取り込みはしない |
| 機種 | Hero 11 | `WiredGoPro` で USB 制御（実装前にファームウェアサポート要検証） |
| 録画単位 | per-episode shutter | 1 episode = 1 MP4（SD 上） |
| DL タイミング | 非同期 | episode_stop はノンブロッキングで返る |
| DL 経路 | USB 有線 | Wi-Fi/BLE は使わない |
| 時刻同期 | `set_date_time()` のみ | 精度 **±1 秒程度**（claim を下方修正） |
| プレビュー | UDP MPEG-TS デコード | preview-only フラグ付き、episode parquet には絶対に入れない |
| 多台数 | N 台対応 | DL は全デバイス横断で **直列化** |
| IMU/GPMF | MP4 内に温存 | 抽出しない、`info.json` にマーカーのみ |
| クライアント所有権 | 1 デバイス = 1 SDK client | preview と recorder はその view |
| キュー永続化 | `.pending/gopro_dl/<uuid>.json` | enqueue 時点で書き込み、move 完了で削除 |
| エラー伝搬 | DL worker → ErrorBus | 既存 `HardwareError` 経路に乗せる |
| Mock | `MockGoProDevice` | GoPro 物理接続なしでテスト可能 |

## Architecture overview

```
┌────────────────────────────────────────────────────────────────┐
│ Session orchestrator (既存)                                     │
│                                                                 │
│  episode_start(t_host) ──┐                                      │
│  episode_stop()       ───┤                                      │
└──────────────────────────┼──────────────────────────────────────┘
                           │
                  ┌────────▼────────────────────────────────────┐
                  │ GoProDeviceRegistry (新規)                   │
                  │  - holds GoProDevice[]                       │
                  │  - fans episode lifecycle to all devices     │
                  └────────┬────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
   ┌────────────┐    ┌────────────┐    ┌────────────┐
   │ GoProDevice│    │ GoProDevice│    │   Mock     │
   │  (real)    │    │  (real)    │    │ GoProDevice│
   └─────┬──────┘    └────────────┘    └────────────┘
         │
         │ owns:
         ├── open_gopro WiredGoPro client (singleton per device)
         ├── GoProPreviewSource  ──→ CameraManager (preview-only)
         └── GoProRecorder       ──→ DLQueue (persistent) ──→ DLWorker
                                                                   │
                                                                   ▼
                                                         dataset/videos/
                                                         observation.images
                                                         .<gopro_name>/...
```

ポイント：

- **1 物理デバイス = 1 `GoProDevice` インスタンス = 1 SDK client**。`open_gopro` は同一プロセス内で同一カメラへの client を 2 つ作れない構造のため、所有権を 1 箇所に集約する。
- **`GoProPreviewSource` は `Camera` インターフェースを実装する read-only view**。CameraManager から見ると他のカメラと同じだが、内部的に SDK client は触らず、UDP socket だけを読む。
- **`GoProRecorder` は control plane の view**。session orchestrator から `start_episode` / `stop_episode` を受け、SDK client を介して shutter コマンドを送る。
- **DLWorker は全 `GoProDevice` 横断で 1 個**（直列化）。複数 GoPro が同時に DL を要求しても 1 つずつ順番に処理する。

## Components

### `backend/mimicrec/gopro/device.py`（新規）

```python
class GoProDevice:
    """1 物理カメラを表す。SDK client の所有者。"""

    def __init__(self, name: str, usb_serial: str, recording_preset: str): ...

    async def connect(self) -> None:
        """WiredGoPro を初期化し、set_date_time() で時刻同期、
        recording preset を適用、UDP プレビューを開始する。"""

    async def disconnect(self) -> None: ...

    # control plane（GoProRecorder が呼ぶ）
    async def shutter_on(self) -> None: ...
    async def shutter_off(self) -> None: ...
    async def media_list(self) -> list[MediaItem]:
        """SD カード上のファイル一覧。start_episode 直後に polling して
        直近録画ファイル名と mtime を取得する用途。"""

    # preview plane（GoProPreviewSource が呼ぶ）
    def preview_udp_port(self) -> int: ...

    # DL plane（DLWorker が呼ぶ）
    async def download_file(self, sd_filename: str, dest: Path) -> None: ...
```

### `backend/mimicrec/gopro/preview.py`（新規）

```python
class GoProPreviewSource:
    """Camera I/F 実装。UDP MPEG-TS を pyav でデコードして preview frame を返す。
    `Frame.preview_only = True` を立てて、recording パスから誤って書かれないようにする。"""

    name: str

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def read(self) -> Frame: ...
```

`Frame` 型に `preview_only: bool = False` フィールドを足す。`PendingEpisode.append_row` 側で `preview_only=True` のフレームは黙って無視する（または assert で落とす — 設計判断は実装時に確定）。

### `backend/mimicrec/gopro/recorder.py`（新規）

```python
class GoProRecorder:
    """control plane の view。DLQueue へ enqueue する責務を持つ。"""

    def __init__(self, device: GoProDevice, dl_queue: DLQueue): ...

    async def start_episode(self, episode_index: int, t_host_mono_ns: int) -> None:
        """shutter ON。media list を polling して新ファイル名と mtime を取得、
        gopro_t0_mono_ns を内部に記録する。"""

    async def stop_episode(self, episode_index: int) -> None:
        """shutter OFF → DLQueue.enqueue(GoProDLJob(...))。
        実際の DL は worker 側で別タイミングで走る。"""
```

### `backend/mimicrec/gopro/dl_queue.py`（新規）

```python
@dataclass
class GoProDLJob:
    job_id: str          # uuid4
    gopro_serial: str
    sd_filename: str
    episode_index: int
    chunk_index: int
    cam_name: str
    expected_mp4_path: Path
    gopro_t0_mono_ns: int
    episode_stop_mono_ns: int

class DLQueue:
    """`.pending/gopro_dl/<job_id>.json` への永続化付きキュー。"""

    def __init__(self, pending_dir: Path): ...

    async def enqueue(self, job: GoProDLJob) -> None:
        """sidecar JSON を fsync してから in-memory queue に積む。"""

    async def dequeue(self) -> GoProDLJob: ...

    async def mark_done(self, job_id: str) -> None:
        """sidecar JSON を削除。"""

    @classmethod
    def restore(cls, pending_dir: Path) -> "DLQueue":
        """起動時に既存 sidecar を全部 in-memory queue に積み直す。"""
```

### `backend/mimicrec/gopro/dl_worker.py`（新規）

```python
class GoProDLWorker:
    """全デバイス横断で 1 個。DL を直列化する。"""

    def __init__(self, queue: DLQueue, devices: dict[str, GoProDevice], errors: ErrorBus): ...

    async def run(self) -> None:
        """ループ: dequeue → device.download_file → MP4 duration check
        → shutil.move → mark_done。失敗は ErrorBus に publish。"""
```

DL 完了時の MP4 duration vs `episode_stop_mono_ns - gopro_t0_mono_ns` の差が 200ms を超えたら **HardwareError 警告レベル** で publish（致命ではない）。

### `backend/mimicrec/gopro/registry.py`（新規）

```python
class GoProDeviceRegistry:
    """session lifecycle に紐付き、全 GoProDevice を持つ。
    session start で全デバイスを connect し、DLQueue を restore、DLWorker を起動。"""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    async def episode_start(self, episode_index: int, t_host_mono_ns: int) -> None: ...
    async def episode_stop(self, episode_index: int) -> None: ...
```

### `backend/mimicrec/gopro/mock.py`（新規）

`MockGoProDevice`：

- `connect/disconnect` は no-op
- `shutter_on/off` は内部カウンタを進めて偽ファイル名を返す
- `download_file` は fixture MP4 を `shutil.copy` する
- `preview_udp_port` は使われない（Mock は preview 無し or fixture frame をループ再生）

`open_gopro` を import せずに動くこと。テスト環境（CI 等）で GoPro 実機なしでも flow が回ることを担保。

### Hydra config（新規）

`configs/cameras/gopro_<name>.yaml`：

```yaml
_target_: mimicrec.gopro.device.GoProDevice
name: gopro_external
usb_serial: "C3441234567890"
recording:
  preset: "1080p_60_wide"     # GoPro 内部の Video Settings preset
preview:
  enabled: true               # false なら UDP socket を開かず preview UI にも出さない
                              # （プレビュー解像度は GoPro 側固定なので width/height は持たない）
```

### CameraManager 統合

CameraManager の `cameras` dict に `GoProPreviewSource` を **キー名は GoPro device name と同じ**で追加する。CameraManager 自体には GoPro 専用のロジックは入らない（`Frame.preview_only` を尊重する変更だけ）。`GoProDevice` と `GoProPreviewSource` の対応は `GoProDeviceRegistry` が知っている。

### `Mp4EpisodeWriter` 統合

GoPro 由来の MP4 は **`Mp4EpisodeWriter` を経由しない**。`GoProDLWorker` が SD から pull した MP4 をそのまま `videos/observation.images.<gopro_name>/chunk-XXX/episode_XXXXXX.mp4` に置く。LeRobot v3.0 の data_path / video_path テンプレートに従う。

### `info.json` の features エントリ

`init_dataset` で GoPro 由来カメラを features に書き込む際、

```json
"observation.images.gopro_external": {
  "dtype": "video",
  "shape": [1080, 1920, 3],
  "names": ["height", "width", "channels"],
  "info": {
    "video.height": 1080,
    "video.width": 1920,
    "video.codec": "h264",
    "video.pix_fmt": "yuv420p",
    "video.fps": 60,
    "video.channels": 3,
    "has_audio": false,
    "has_gpmf": true
  }
}
```

`has_gpmf: true` が後段の loader にとってのマーカー。Hero 11 の video モード収録は常に GPMF を含むので、`GoProDevice` 由来カメラに対しては常に true で書き込む。

## Data flow

### Session 起動時

```
1. GoProDeviceRegistry.start()
2.  ├─ for device in devices:
3.  │    └─ device.connect()
4.  │        ├─ WiredGoPro init
5.  │        ├─ set_date_time(now)
6.  │        ├─ apply recording preset
7.  │        └─ start UDP preview (if enabled)
8.  ├─ DLQueue.restore(.pending/gopro_dl/) ← クラッシュリカバリ
9.  └─ DLWorker.run() を asyncio.create_task で起動
```

device.connect() のいずれかが失敗した場合：

- **そのデバイスだけ disable** にして session は続行する（他のカメラに影響を出さない）
- ErrorBus に `HardwareError` を publish
- そのデバイスへの shutter コマンドはスキップ、DL も発火しない

### Episode lifecycle

```
episode_start(idx, t_host):
  for each enabled device:
    recorder.start_episode(idx, t_host)
      ├─ device.shutter_on()
      ├─ poll device.media_list() until new file appears (timeout 2s)
      ├─ record gopro_t0_mono_ns ≈ time.monotonic_ns() at first detection
      └─ store {idx, sd_filename, gopro_t0_mono_ns} in recorder

episode_stop(idx):
  for each enabled device:
    recorder.stop_episode(idx)
      ├─ device.shutter_off()
      ├─ build GoProDLJob(...)
      └─ dl_queue.enqueue(job)   ← sidecar JSON を fsync してから returned
  return immediately（DL は裏）
```

### DLWorker ループ

```
loop:
  job = await queue.dequeue()
  try:
    tmp = pending_dir / f"{job.job_id}.mp4"
    await device.download_file(job.sd_filename, tmp)
    duration = probe_mp4_duration(tmp)
    expected = (episode_stop - gopro_t0) / 1e9
    if abs(duration - expected) > 0.2:
      errors.publish(HardwareError(f"GoPro MP4 duration mismatch: {duration} vs {expected}"))
    job.expected_mp4_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(tmp, job.expected_mp4_path)
    queue.mark_done(job.job_id)
  except Exception as e:
    errors.publish(HardwareError(f"GoPro DL failed for episode {job.episode_index}: {e}"))
    # sidecar JSON は残す → 次回起動時に restore される
```

### Session 終了時

```
1. registry.stop()
2.  ├─ DLWorker に stop signal、queue.dequeue() を cancel
3.  │    （inflight の job は完了させる）
4.  ├─ for device in devices:
5.  │    └─ device.disconnect()
6.  └─ 残った job の sidecar JSON は **削除しない**（次回 session で resume）
```

UI には「N 件 GoPro DL pending」を出す。Quit 時にユーザーに「pending 件あります、SDカードを抜かないでください」を警告する。

## Time sync caveat

本設計は **`set_date_time()` のみ** を使い、達成精度は **±1 秒程度**。これは：

- `set_date_time()` の解像度が 1 秒
- USB コマンドの RT 補償をしていない
- GPMF の `STMP` がカメラ内部時計ベース

ため。**フレーム単位の同期は出来ない**。IMU を学習で使う段階で精度が必要になった場合は、別 spec で同期信号（LED フラッシュ／音声チャープ等）導入を検討する。本 spec ではそこまで踏み込まない。

`shutter_on` 後の `media_list` polling で `gopro_t0_mono_ns` をホスト時計上に記録するので、**MP4 と episode の対応・MP4 duration mismatch 検出は ±数百 ms 精度で動く**。これは episode-level の整合性検証用であり、IMU の frame-level alignment 用途ではない点に注意。

## Failure handling

| 事象 | 挙動 |
|---|---|
| `device.connect()` 失敗 | そのデバイスだけ disable、他は継続。`HardwareError` を publish |
| `shutter_on()` 失敗 | episode_start を継続（GoPro なしで進む）、`HardwareError` 警告 |
| `media_list` polling timeout | `gopro_t0` 不明として episode 続行、duration check はスキップ |
| `shutter_off()` 失敗 | `set_shutter` を再試行（最大 3 回）、ダメなら `HardwareError`、DL job は enqueue しない |
| DLWorker 中の `download_file` 失敗 | sidecar JSON は残す、ErrorBus に publish、次の job へ進む。再試行は次回起動時に restore された時点 |
| アプリクラッシュ | sidecar JSON が残る → 次回 `DLQueue.restore()` で in-memory queue に再ロード |
| SD カード満杯 | `set_shutter(on)` がエラーで返る前提（要実機検証）。検出したら `HardwareError`(fatal) で session 停止候補 |
| MP4 duration mismatch >200ms | `HardwareError` 警告（致命ではない）、DL は完遂する |

## Multi-GoPro USB realities

USB3 ハブで複数 GoPro を扱う場合の注意点を doc に明記する：

- DLWorker は全デバイス横断で **直列**。同時 DL は不可。
- N≥2 なら **別の USB コントローラ root**（物理的に違うチップ）に挿すことを推奨。
- DL 中の同 GoPro はプレビューが詰まることがある。preview frame drop は許容、`HardwareError` にはしない。
- 動作検証は最大 2 台までを想定。それ以上は運用で対応。

## Testing

### Unit tests

- `MockGoProDevice` を使った `GoProRecorder` の lifecycle テスト（start_episode → stop_episode → enqueue まで）。
- `DLQueue` の永続化／restore 動作（sidecar JSON の create / fsync / delete を確認）。
- `DLWorker` の MP4 duration mismatch 検出（fixture MP4 を使う）。
- `Frame.preview_only` フラグが `PendingEpisode.append_row` で無視される／弾かれることの確認。

### Integration tests（実機要）

- 1 台の Hero 11 を USB 接続し、3 episode 連続収録 → DL → MP4 が正しいパスに置かれ、GPMF が ffprobe で確認できる。
- session 中に `kill -9` し、再起動して `.pending/gopro_dl/` から resume されることを確認。
- preview UI に GoPro の映像が出ることを目視確認。
- 2 台同時接続でも 1 台ずつ順番に DL される（ログ確認）。

### CI（GoPro 実機なし）

- `MockGoProDevice` ベースの flow テストのみ。

## Dependencies / pre-implementation verification

実装に入る前に **確認が必要な点**：

1. `open_gopro` PyPI 版で **Hero 11 の `WiredGoPro` が `set_date_time` / `set_shutter` / `media_list` / `download_file` / UDP preview start を全部サポート**しているか。バージョンを pin する必要あり。サポートしていない API は BLE fallback が必要になり所有権モデルが複雑化する。
2. `Hero 11` のファームウェアバージョンを実機で確認し、SDK との互換性をチェック。
3. UDP プレビューの **フレームレート・解像度・コーデック**を実機で確認（pyav デコード負荷見積もり用）。
4. `media_list` の polling コストと latency を実測（`shutter_on` 後にいつ新ファイルが appear するか）。
5. USB 直挿し vs ハブ経由の DL スループット差を実測（必要 USB トポロジーの根拠）。

## Out of scope reminders

- **GPMF 抽出 / IMU を parquet 化する処理は本 feature では書かない**。MP4 にそのまま埋まったまま。loader 側の対応は別 feature。
- **シャッター latency 補償のための同期信号（LED 等）は本 feature では入れない**。±1 秒精度で運用する前提。
- **GoPro 設定 UI**（preset 切り替え等）は本 feature では入れない。YAML 編集のみ。
