# GoPro Hero 11 recording integration — design

## Problem

MimicRec は今 `OpenCVCamera`（V4L2 UVC）でしかカメラ収録を扱えない。広角・高画質・手振れ補正・各種センサ（IMU/温度/GPS）を一緒に録りたいケースで、GoPro Hero 11 を「もう1つのカメラ」として LeRobot v3.0 形式に並べて記録できるようにしたい。

GoPro は通常の UVC カメラと違い、

- フレームを host が逐次 read する API ではなく **SDカードに自身で録画する**
- ライブ映像は別系統で **UDP MPEG-TS の低解像度プレビュー**として流れる
- IMU 等は録画 MP4 の **GPMF (GoPro Metadata Format) トラックに同梱**される

ため、既存の `Camera.read() -> Frame` モデルにそのまま乗らない。専用の抽象を入れて既存パイプラインと共存させる。

## Goals

1. 1 台以上の GoPro Hero 11 を `configs/gopros/*.yaml` で宣言でき、session 起動で自動接続される。
2. エピソード start/stop に追従して GoPro 側も録画 start/stop し、SDカードに 1 episode = 1 MP4 を作る。
3. その MP4 を **非同期** にホストへ pull し、LeRobot 形式の `videos/observation.images.<gopro_name>/chunk-XXX/episode_XXXXXX.mp4` に配置する。
4. 操作者が収録中に GoPro の構図を確認できるよう、UDP プレビューを既存のカメラプレビュー UI に出す（ただし episode parquet には書かない）。
5. 収録途中でアプリがクラッシュ／停止しても、SD 上に残っている MP4 を後から拾い直して該当 episode に紐付けられる（永続キュー）。
6. IMU 等のセンサデータは **MP4 の GPMF トラックに埋め込まれたまま保持**し、`info.json` にその存在をマーカーとして記録する。

## Definition of done

実装完了の判定は以下の全項目を満たすこと：

- [ ] `configs/gopros/<name>.yaml` を作って session を起動すると、GoPro が USB 接続され、UI のプレビューに UDP 映像が流れる。
- [ ] 1 episode 収録 → episode_stop 後 1〜数秒で `videos/observation.images.<gopro_name>/chunk-000/episode_000000.mp4` が dataset に置かれる。
- [ ] その MP4 を `ffprobe -show_streams` すると GPMF (handler_name `GoPro MET`) トラックが含まれる。
- [ ] `info.json` の features エントリに `observation.images.<gopro_name>` があり `info.has_gpmf=true` が立っている。
- [ ] session 中に SIGKILL → 再起動で `.pending/gopro_dl/<uuid>.json` が resume され、未取得の MP4 が dataset に揃う。
- [ ] 2 台同時運用で DL が直列化される（DLWorker のログで確認）。
- [ ] GoPro なしでも `MockGoProDevice` ベースの unit test が通る（CI 含む）。
- [ ] `Frame.preview_only=True` のフレームが `PendingEpisode` の **video writer 経路に渡らない**（row 自体は parquet に append される）ことを単体テストで確認。

## Non-goals (Out of scope)

- **リアルタイムに GoPro の高解像度フレームを取得**して制御ループに使うこと（構造的に不可能）。
- **フレーム単位（≤数十 ms）の時刻同期**。本設計の精度は **±1 秒程度**（後述）。タイトな同期が必要になったら別 feature で同期信号を導入する。
- GoPro 側の録画 preset を **UI から動的に切り替える**こと。最初は YAML で固定、SDK 経由でセッション開始時に適用する。
- **GPMF を別ファイルへ抽出**して parquet 化すること（MP4 内に温存する方針）。将来 IMU を学習に使う段階で別途 loader / 変換を書く。
- **Wi-Fi / BLE 経由の制御**。USB 有線のみ。BLE は SDK の都合で必要なら裏で使うが、運用上は USB ケーブル接続前提。
- **GoPro セッション中のホットプラグでの再接続**。session 開始時に揃っていることを前提とする。session 中の切断は「壊れたデバイス」として扱い再接続は試みない。
- **複数 GoPro を 1 つの USB ハブで限界まで並列駆動**。実機検証は最大 2 台までを想定。多数同時運用時の帯域問題は運用 doc に記載するに留める。
- **同一データセットへの並行セッション** — 既存の制約（pending dir のロック無し）を踏襲し、`.pending/gopro_dl/` 競合は対象外。README に1セッション/データセットを明記する。
- 既知バグ：`dataset_layout.py:75` の OpenCV カメラ向け「`camera_resolutions` 未指定時の 480×640 デフォルト」は本 feature では直さない。本 feature は `gopro_specs` を別途渡す経路で GoPro 用エントリを書くため、デフォルト経路には触らない。

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
| 多台数 | N 台対応 | DL は全デバイス横断で **直列化**（実機検証は最大 2 台） |
| IMU/GPMF | MP4 内に温存 | 抽出しない、`info.json` にマーカーのみ |
| クライアント所有権 | 1 デバイス = 1 SDK client | `GoProDevice` が所有、preview/recorder はその view |
| キュー永続化 | `.pending/gopro_dl/<uuid>.json` | enqueue 時点で fsync、move 完了で削除 |
| ジョブのデータセットパス | **相対パス**で sidecar に保存 | 起動時に `paths.videos_dir` で resolve、データセット移動に強い |
| エラー伝搬 | DL worker → ErrorBus | 既存 `HardwareError` 経路に乗せる |
| Mock | `MockGoProDevice` / `MockGoProPreviewSource` | CI で GoPro 物理接続なしでも全 flow が回る |
| Config 配置 | `configs/gopros/*.yaml` | `cameras/` とは別ディレクトリ。既存 `width/height` 仮定との衝突を避ける |
| 起動順 | Registry → CameraManager | preview_source は registry が用意、CameraManager に merge して渡す |
| Disabled device | 一度ログ、以降 silent skip | `CameraManager._run_camera` の fail-open に倣う |

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
   │ - shutter,     │  │ ...            │    │                    │
   │   media_list,  │  │                │    │                    │
   │   download,    │  │                │    │                    │
   │   start/stop_  │  │                │    │                    │
   │   preview      │  │                │    │                    │
   └─────┬──────┬───┘  └────────────────┘    └────────────────────┘
         │      │
         │      └─────────► GoProRecorder (control plane view)
         │                    └─► DLQueue.enqueue(GoProDLJob)
         │
         └─────────► GoProPreviewSource (UDP+pyav view, Camera I/F)
                       │
                       ▼
              CameraManager.cameras dict (新エントリ)
                       │
                       ▼
              JPEG preview fan-out (既存)
              ※ Frame.preview_only=True のため、
                PendingEpisode は無視する
```

ポイント：

- **1 物理デバイス = 1 `GoProDevice` インスタンス = 1 SDK client**。`open_gopro` は同一プロセス内で同一カメラへの client を 2 つ作れない構造のため、所有権を 1 箇所に集約する。
- **`GoProPreviewSource` は `Camera` インターフェースを実装する read-only view**。CameraManager から見ると他のカメラと同じだが、内部的に SDK client は共有しない（コマンドは `GoProDevice` 経由）。
- **`GoProRecorder` は control plane の view**。session orchestrator から `start_episode` / `stop_episode` を受け、SDK client を介して shutter コマンドを送る。
- **DLWorker は全 `GoProDevice` 横断で 1 個**（直列化）。複数 GoPro が同時に DL を要求しても 1 つずつ順番に処理する。
- **`GoProDeviceRegistry` は CameraManager と peer**。session orchestrator が両方を持ち、registry を **先に start** して preview_sources を集めてから CameraManager を構築する。

## Components

### `backend/mimicrec/gopro/types.py`（新規）

```python
@dataclass(frozen=True)
class GoProSpec:
    """info.json features 用の resolved 値。
    `gopro/types.py` に置く理由: `recording/dataset_layout.py:init_dataset` が
    `GoProSpec` をパラメータで受ける。`recording/` → `gopro/types.py` の一方向
    依存に留め、`gopro/device.py`（重い import: open_gopro 等）への循環を避ける。"""
    name: str
    width: int
    height: int
    fps: int
    codec: str           # "h264" / "h265"

@dataclass
class MediaItem:
    filename: str        # "GX010001.MP4" 形式
    size: int
    mtime_ns: int        # camera-clock 由来、host clock とのマップは別経路
```

### `backend/mimicrec/gopro/device.py`（新規）

```python
class GoProDevice:
    """1 物理カメラを表す。SDK client の所有者。
    制御コマンドは全部ここを通る（preview/recorder は view）。"""

    def __init__(self, name: str, usb_serial: str, recording_preset: str): ...

    @property
    def name(self) -> str: ...
    @property
    def usb_serial(self) -> str: ...

    async def connect(self) -> None:
        """順序:
          1. WiredGoPro を初期化
          2. set_date_time(now) を投げる
          3. set_video_mode() で video モードへ強制（photo/timelapse 等を排除）
          4. recording preset を適用
          5. get_camera_state を見て storage_remaining が閾値（500MB）以下なら
             FatalHardwareError を上げる
          UDP preview は **ここでは開始しない**（GoProPreviewSource 側が start）。"""

    async def disconnect(self) -> None:
        """SDK client を閉じる。multiple-call 安全。"""

    # control plane（GoProRecorder が呼ぶ）
    async def shutter_on(self) -> None: ...
    async def shutter_off(self) -> None: ...

    async def media_list(self) -> list[MediaItem]:
        """SD カード上のファイル一覧（型定義は gopro/types.py 参照）。"""

    # preview plane（GoProPreviewSource が呼ぶ）
    async def start_preview(self, port: int) -> None:
        """SDK 経由でカメラに「UDP MPEG-TS を host:<port> へ流せ」と指示。
        （ホスト側 socket は開かない — それは PreviewSource の仕事）"""

    async def stop_preview(self) -> None: ...

    # info.json 用の resolved spec
    def get_spec(self) -> GoProSpec:
        """recording_preset から (width, height, fps, codec) を解決。
        内部に preset → (w, h, fps, codec) の lookup table を持つ。
        Hero 11 の代表的 preset の出発セット:
          - '1080p_60_wide'    -> (1920, 1080, 60, 'h264')
          - '1080p_30_wide'    -> (1920, 1080, 30, 'h264')
          - '2.7K_60_wide'     -> (2704, 1520, 60, 'h264')
          - '4K_30_wide'       -> (3840, 2160, 30, 'h265')
          - '4K_60_wide'       -> (3840, 2160, 60, 'h265')
          - '5.3K_30_wide'     -> (5312, 2988, 30, 'h265')
        実装時に SDK ドキュメント・実機検証で表を埋める。
        unknown preset は connect() 時点で `FatalHardwareError("unknown preset: ...")` を上げ、
        device を disable する（YAML typo を即時に検知）。"""

    # DL plane（DLWorker が呼ぶ）
    async def download_file(self, sd_filename: str, dest: Path) -> None: ...
    async def get_storage_remaining(self) -> int: ...

    # state
    @property
    def is_disabled(self) -> bool: ...
    def disable(self, reason: str) -> None:
        """以後 shutter/preview/download を no-op にする。一度だけログ出力。"""
```

### `backend/mimicrec/gopro/preview.py`（新規）

```python
class GoProPreviewSource:
    """Camera I/F 実装。device の SDK 経由で preview start を依頼し、
    UDP MPEG-TS を pyav でデコードして preview frame を返す。
    Frame.preview_only=True を立てる（recording パスから誤って書かれない保証）。"""

    name: str   # = device.name

    def __init__(self, device: GoProDevice, udp_port: int): ...

    async def connect(self) -> None:
        """device.start_preview(udp_port) → UDP socket を bind →
        pyav の InputContainer を開く → decode loop を asyncio.create_task で起動。
        device が disabled なら no-op で returns（CameraManager の fail-open と整合）。"""

    async def disconnect(self) -> None: ...

    async def read(self) -> Frame:
        """pyav の decode loop が pushed した最新フレームを返す。
        必ず Frame.preview_only=True を立てる。

        device.is_disabled の状態では: 永久に解放されない `asyncio.Event` を
        await して clean idle 状態になる（cancel まで block）。
        例外を上げないことで `CameraManager._run_camera` が 50ms ごとに
        HardwareError を publish する spam ループを避ける。"""
```

UDP ポートは registry が **デバイスごとに別ポートを割り当てる**（ベース 8556 + index）。ポート衝突時は次ポートを試す。

### `backend/mimicrec/gopro/recorder.py`（新規）

```python
@dataclass
class _EpisodeState:
    episode_index: int
    sd_filename: str | None         # start_episode の polling で取れたら set
    gopro_t0_mono_ns: int | None    # 同上
    episode_start_mono_ns: int

class GoProRecorder:
    """control plane の view。DLQueue へ enqueue する責務を持つ。"""

    def __init__(
        self,
        device: GoProDevice,
        dl_queue: DLQueue,
        paths: DatasetPaths,
    ): ...

    async def start_episode(self, episode_index: int, t_host_mono_ns: int) -> None:
        """device が disabled なら no-op。
        1. shutter_on()
        2. media_list を 100ms ごとに poll、最大 2.0s。
           前回の episode から増えた .MP4 ファイルを検出したら
             sd_filename = それ
             gopro_t0_mono_ns = time.monotonic_ns() at detection
        3. polling 失敗時は (None, None) のまま継続。
        4. _EpisodeState を内部に保存。
        失敗（shutter_on が IOError 等）→ device.disable()、HardwareError publish、
        以後は no-op。"""

    async def stop_episode(self, episode_index: int) -> None:
        """device が disabled なら no-op。
        1. shutter_off()（最大 3 回 retry）
        2. _EpisodeState.sd_filename が None なら今 media_list を呼んで
           「このセッション開始以降に作成された最新の .MP4」を探す。
           見つかれば sd_filename に詰める。
           見つからなければ HardwareError publish して enqueue は **しない**
           （SD 上に orphan として残る — README に「手動 pull」手順を記載）。
        3. GoProDLJob を組んで dl_queue.enqueue。
           cam_name = device.name
           chunk_index = resolve_chunk(episode_index)
           gopro_t0_mono_ns は None のままでも入れる（duration check 側で None 判定）。
           **dest path は DLWorker 実行時に `paths.episode_video(chunk_index, cam_name, episode_index)`
           で recompute する**（sidecar JSON に絶対/相対パス文字列を保存しない — レイアウト関数の
           将来変更に追従できるようにするため）。"""
```

### `backend/mimicrec/gopro/dl_queue.py`（新規）

```python
@dataclass
class GoProDLJob:
    """sidecar JSON に直結する schema。
    **dest path は持たない** — DLWorker 実行時に
    `paths.episode_video(chunk_index, cam_name, episode_index)` で recompute する。
    これによりデータセット移動 + DatasetPaths レイアウト関数の将来変更の両方に追従する。"""
    job_id: str                      # uuid4
    gopro_serial: str
    sd_filename: str                 # enqueue 時には必ず resolved
    episode_index: int
    chunk_index: int                 # `resolve_chunk(episode_index)` の denormalized cache
    cam_name: str
    gopro_t0_mono_ns: int | None     # None なら duration check skip
    episode_stop_mono_ns: int

    def to_json(self) -> dict: ...
    @classmethod
    def from_json(cls, d: dict) -> "GoProDLJob": ...

class DLQueue:
    """`.pending/gopro_dl/<job_id>.json` への永続化付きキュー。"""

    def __init__(self, pending_dir: Path):
        """pending_dir が存在しなければ mkdir(parents=True, exist_ok=True)。"""

    async def enqueue(self, job: GoProDLJob) -> None:
        """1. sidecar JSON を tmp パスに書いて os.fsync → atomic rename
           2. in-memory asyncio.Queue に積む"""

    async def dequeue(self) -> GoProDLJob: ...

    async def mark_done(self, job_id: str) -> None:
        """sidecar JSON を削除（既に無くてもエラーにしない）。"""

    @classmethod
    def restore(cls, pending_dir: Path) -> "DLQueue":
        """1. pending_dir.mkdir
           2. pending_dir/*.json を読み GoProDLJob に戻す
           3. ロード順は filename ソート順（決定論的）
           4. in-memory queue にすべて積む"""
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
              errors.publish(HardwareError(f'... no device for serial {serial}'))
              # sidecar は残す（次セッションで device 復帰したら再試行）
              continue

          tmp = paths.pending_dir / f'gopro_dl_{job.job_id}.mp4'

          # Resume-from-tmp: 前回の DL 完了後の move で失敗した場合の再開
          need_download = not (tmp.exists() and tmp.stat().st_size > 0
                               and tmp.stat().st_size == probe_sd_size(device, job.sd_filename))
          if need_download:
              await device.download_file(job.sd_filename, tmp)

          # MP4 duration check（"録画ロス" の片側だけ警告する）
          # gopro_t0 は polling 検出時刻なので実際の record start より 100-300ms 遅い、
          # shutter_off も 100-300ms の tail を持つので、健全な MP4 は expected より
          # わずかに長くなる。**短い**方向のズレだけが record loss を意味する。
          if job.gopro_t0_mono_ns is not None:
              duration = probe_mp4_duration(tmp)
              expected = (job.episode_stop_mono_ns - job.gopro_t0_mono_ns) / 1e9
              if duration < expected - 0.5:
                  errors.publish(HardwareError(
                      f'GoPro recording shorter than episode: ep {job.episode_index} '
                      f'duration={duration:.3f}s expected≈{expected:.3f}s'))

          dest = paths.episode_video(job.chunk_index, job.cam_name, job.episode_index)
          dest.parent.mkdir(parents=True, exist_ok=True)
          shutil.move(str(tmp), str(dest))    # cross-device 安全（fallback to copy+unlink）
          await queue.mark_done(job.job_id)

        例外発生時:
          - sidecar は残す（次回 restore で復活）
          - errors.publish(HardwareError(...))
          - inner loop continue（worker 自体は死なない）
        """

    async def stop(self) -> None:
        """1. 受信停止フラグを立てる（dequeue は cancel）
           2. in-flight job がいたら shutdown_grace_sec まで待つ
           3. 経過したら job task を cancel（sidecar 残置）"""
```

### `backend/mimicrec/gopro/registry.py`（新規）

```python
class GoProDeviceRegistry:
    """session lifecycle に紐付き、全 GoProDevice を持つ。"""

    def __init__(
        self,
        devices: list[GoProDevice],
        paths: DatasetPaths,
        errors: ErrorBus,
    ):
        """asserts:
          - len({d.name for d in devices}) == len(devices)
          - len({d.usb_serial for d in devices}) == len(devices)
          duplicate ならば ValueError。"""

    async def start(self) -> None:
        """1. 各 device.connect() を gather。失敗した device は disable して継続。
           2. DLQueue.restore(paths.pending_dir) → in-memory queue に既存ジョブを乗せる。
           3. DLWorker.run() を asyncio.create_task。
           4. 各 device に対して GoProRecorder, GoProPreviewSource を生成（disabled でも生成、no-op 化）。
           5. preview_source の UDP ポートを 8556 + index で割り当て（衝突時は +1 で retry）。"""

    async def stop(self) -> None:
        """1. DLWorker.stop() を await（in-flight 完了 or 30s で cancel）
           2. 各 PreviewSource.disconnect()
           3. 各 device.disconnect()
           sidecar JSON は残置（次セッションで resume）"""

    async def episode_start(self, episode_index: int, t_host_mono_ns: int) -> None:
        """各 GoProRecorder.start_episode を gather（disabled は no-op で即 return）。"""

    async def episode_stop(self, episode_index: int) -> None:
        """各 GoProRecorder.stop_episode を gather。"""

    def preview_sources(self) -> dict[str, GoProPreviewSource]:
        """name -> source。session orchestrator が CameraManager に merge する。
        disabled な device の source も含む（CameraManager は fail-open で
        connect 失敗を握り潰すので問題ない）。"""

    def gopro_specs(self) -> dict[str, GoProSpec]:
        """info.json 用に各 device の spec を返す（disabled でも spec は返す）。"""

    @property
    def pending_count(self) -> int:
        """UI に「N pending DLs」を出すための値。"""
```

### `backend/mimicrec/gopro/mock.py`（新規）

```python
class MockGoProDevice(GoProDevice):
    """SDK を import せずに動く。"""

    def __init__(
        self,
        name: str,
        usb_serial: str,
        recording_preset: str = "1080p_60_wide",
        fixture_mp4: Path | None = None,   # download_file 時の fixture
        emit_preview: bool = False,        # True なら start_preview で UDP に
                                            # フィクスチャ動画を流すスレッドを起こす
    ): ...

    # 実装:
    # - connect/disconnect: 内部フラグ切り替えのみ
    # - shutter_on/off: 内部カウンタ進める。media_list が新ファイル名を返すように
    # - media_list: 内部状態に基づいた fake list を返す
    # - download_file: fixture_mp4 があれば shutil.copy、無ければ空 MP4 ヘッダを書く
    # - start_preview: emit_preview=True なら別スレッドで fixture を UDP 送出
    # - get_storage_remaining: 1GB 固定（テストで失敗ケースは別途 SmallStorageMockGoProDevice）
```

`emit_preview=True` のテストで `Frame.preview_only=True` の生成・伝搬を検証する。

### Hydra config（新規）

`configs/gopros/gopro_external.yaml`：

```yaml
_target_: mimicrec.gopro.device.GoProDevice
name: gopro_external
usb_serial: "C3441234567890"
recording_preset: "1080p_60_wide"   # SDK の Video Settings preset。
                                     # 解像度/fps/codec は GoProDevice.get_spec()
                                     # で resolve され、info.json に書かれる
preview:
  enabled: true                      # false なら start_preview しない、
                                      # CameraManager にも出ない
```

YAML には `width/height` を **書かない**。先行するカメラ系コード（`api/deps.py:154`）が `width`/`height` を default 640/480 にフォールバックするため、書くと誤値が `init_dataset` に渡る。GoPro の解像度は `recording_preset` から `GoProDevice.get_spec()` 経由で resolve される。

### Cross-cutting changes（既存ファイルへの追加）

実装中に触る必要がある既存ファイル：

| ファイル | 変更内容 |
|---|---|
| `backend/mimicrec/types.py` | `Frame` に `preview_only: bool = False` フィールド追加 |
| `backend/mimicrec/recording/pending.py` | `append_row` で `frames[name].value.preview_only` をチェックし、True なら video writer に渡さない（silent skip）。row 自体は通常通り append。 |
| `backend/mimicrec/recording/pending.py` | `open_video_writers` の引数 `cameras` から GoPro 由来カメラを除外する（呼び出し側責任、registry が gopro 名一覧を提供）。 |
| `backend/mimicrec/recording/dataset_layout.py` | `init_dataset` に `gopro_specs: dict[str, GoProSpec] \| None = None` を追加（`GoProSpec` は `mimicrec.gopro.types` から import — `gopro/types.py` は leaf module なので循環依存にならない）。features dict に GoPro 専用エントリを書く（後述）。 |
| `backend/mimicrec/api/schemas.py` | `_BaseSessionRequest` に `gopros: list[str] = field(default_factory=list)` を追加（既存クライアントは送らないので default 空リストで後方互換）。`SessionStatePayload` 系にも `gopros: list[str] = []` を追加して response にも GoPro 名を載せる。 |
| `backend/mimicrec/api/deps.py` | (1) `req.gopros` を読む、(2) `configs/gopros/<n>.yaml` から `GoProDevice` を instantiate、(3) `GoProDeviceRegistry` を構築・start、(4) preview_sources を `cams` dict に merge してから `CameraManager` を構築、(5) `init_dataset` に `gopro_specs=registry.gopro_specs()` を渡す、(6) `app.state.gopro_registry` に保存、(7) `req.cameras` から GoPro 名は除外（OpenCV 側のみ）。`req.cameras` と `req.gopros` の名前空間は disjoint であることを deps.py で assert する（YAML が両方に置かれる事故を防ぐ）。 |
| `backend/mimicrec/api/routes/...` | session_meta / SessionStatePayload に `"gopros": list[str]` 追加。frontend に pending DL 件数を expose する endpoint を1個追加（`GET /api/session/gopro_pending`）。 |
| `backend/mimicrec/cameras/manager.py` | **変更なし**。`Frame.preview_only` は `_run_camera` で素通り（LatestValue / JPEG fan-out には流す）。チェックは `PendingEpisode` 側でのみ行う。 |
| `frontend/src/...` | pending DL 件数バッジ。session 終了時に「N pending」が残っていたら警告ダイアログ。 |

### `init_dataset` の features 拡張

現状 `dataset_layout.py:71-86` は `camera_names: list[str]` をループして `observation.images.<cam>` を書く。これを次のように拡張：

```python
def init_dataset(
    ds_root, fps, joint_names,
    camera_names,                              # OpenCV 系のみ
    *,
    robot_type=None,
    gripper_convention=None,
    proprio_layout=None,
    camera_resolutions=None,                   # OpenCV 系の解像度
    gopro_specs: dict[str, GoProSpec] | None = None,   # 新規
):
    ...
    for cam in camera_names:
        # 既存のまま
        ...

    if gopro_specs:
        for name, spec in gopro_specs.items():
            features[f"observation.images.{name}"] = {
                "dtype": "video",
                "shape": [spec.height, spec.width, 3],
                "names": ["height", "width", "channels"],
                "info": {
                    "video.height": spec.height,
                    "video.width": spec.width,
                    "video.codec": spec.codec,    # "h264"
                    "video.pix_fmt": "yuv420p",
                    "video.is_depth_map": False,
                    "video.fps": spec.fps,
                    "video.channels": 3,
                    "has_audio": False,
                    "has_gpmf": True,
                },
            }
    ...
```

OpenCV 側の 480×640 デフォルトフォールバック（`camera_resolutions` 未指定時）には触らない。Hero 11 video モード収録は常に GPMF を含むため、`has_gpmf: True` は無条件で立てる。

## Data flow

### Session 起動時

```
1. api/deps.py: load configs (cameras + gopros)
2. instantiate GoProDevice[] from configs/gopros/
3. GoProDeviceRegistry(devices=..., paths=..., errors=error_bus)
4. await registry.start()
   ├─ for d in devices: d.connect()
   │    ├─ WiredGoPro init
   │    ├─ set_date_time(now)
   │    ├─ set_video_mode()
   │    ├─ apply preset
   │    └─ get_camera_state → storage check
   │   失敗: d.disable(reason)、errors.publish
   ├─ DLQueue.restore(paths.pending_dir)  ← クラッシュリカバリ
   ├─ DLWorker.run() を asyncio.create_task
   └─ for d: 生成 GoProRecorder(d, queue, paths)
              生成 GoProPreviewSource(d, port=8556+idx)
5. preview_sources = registry.preview_sources()
6. cams = {**opencv_cams, **preview_sources}  ← merge
7. CameraManager(cameras=cams, error_bus=...)
8. await camera_manager.start()
   └─ 各 cam.connect() を内部で呼ぶ
       └─ GoProPreviewSource.connect():
           - device.start_preview(udp_port)
           - UDP socket bind
           - pyav decode loop 起動
       device.is_disabled なら no-op
9. init_dataset (新規データセット時のみ) with gopro_specs=registry.gopro_specs()
10. app.state.gopro_registry = registry
```

### Episode lifecycle

```
episode_start(idx, t_host):
  await camera_manager  # OpenCV 側は既存通り
  await registry.episode_start(idx, t_host)
    for each enabled recorder:
      shutter_on()
      poll media_list（100ms × 20 回 = 最大 2s）して新ファイル検出
      detect: sd_filename = match, gopro_t0_mono_ns = time.monotonic_ns()
      _EpisodeState を内部保存
    enabled でない/失敗した recorder は skip

episode_stop(idx):
  await registry.episode_stop(idx)
    for each enabled recorder:
      shutter_off()
      if state.sd_filename is None:
        retry media_list now、最新 .MP4 を取る
        まだ None: errors.publish、enqueue skip（orphan）
      else:
        job = GoProDLJob(...)
        await dl_queue.enqueue(job)   ← sidecar fsync後に in-memory queue
  return immediately（DL は裏）
```

### DLWorker ループ（pseudocode）

```
loop:
  job = await queue.dequeue()
  try:
    device = devices.get(job.gopro_serial)
    if device is None or device.is_disabled:
      errors.publish(HardwareError(...))
      continue   # sidecar 残置 → 次回再試行

    tmp = paths.pending_dir / f'gopro_dl_{job.job_id}.mp4'

    # resume-from-tmp（前回 shutil.move 失敗ケースの救済）
    skip_dl = (
      tmp.exists()
      and tmp.stat().st_size > 0
      and tmp.stat().st_size == await device.probe_sd_size(job.sd_filename)
    )
    if not skip_dl:
      await device.download_file(job.sd_filename, tmp)

    # duration check（"短い" 方向だけ警告 — record loss 検出用、
    # 詳細は Components > GoProDLWorker 参照）
    if job.gopro_t0_mono_ns is not None:
      duration = probe_mp4_duration(tmp)
      expected = (job.episode_stop_mono_ns - job.gopro_t0_mono_ns) / 1e9
      if duration < expected - 0.5:
        errors.publish(HardwareError(f'GoPro recording shorter than episode {job.episode_index}'))

    dest = paths.episode_video(job.chunk_index, job.cam_name, job.episode_index)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tmp), str(dest))   # 同一 FS なら rename、跨いだら copy+unlink
    await queue.mark_done(job.job_id)

  except asyncio.CancelledError:
    raise   # shutdown
  except Exception as e:
    errors.publish(HardwareError(f'GoPro DL failed for ep {job.episode_index}: {e}'))
    # sidecar は残す
```

### Session 終了時

```
1. registry.stop()
   ├─ DLWorker.stop()
   │   ├─ accept_new = False
   │   ├─ wait inflight up to 30s（grace period）
   │   └─ timeout したら task.cancel() — sidecar JSON 残置
   ├─ 各 PreviewSource.disconnect()
   │   └─ device.stop_preview() → UDP socket close → pyav close
   └─ 各 device.disconnect() → SDK client close
2. UI に「N pending GoPro DLs」を出す
3. ユーザーに quit 警告 — 「pending 件残っています、SDカードを抜かないでください」
```

## Time sync caveat

本設計は **`set_date_time()` のみ** を使い、達成精度は **±1 秒程度**。これは：

- `set_date_time()` の解像度が 1 秒
- USB コマンドの RT 補償をしていない
- GPMF の `STMP` がカメラ内部時計ベース

ため。**フレーム単位の同期は出来ない**。IMU を学習で使う段階で精度が必要になった場合は、別 spec で同期信号（LED フラッシュ／音声チャープ等）導入を検討する。本 spec ではそこまで踏み込まない。

`shutter_on` 後の `media_list` polling で `gopro_t0_mono_ns` をホスト時計上に記録するので、**MP4 と episode の対応・MP4 duration mismatch 検出は ±数百 ms 精度で動く**。これは episode-level の整合性検証用であり、IMU の frame-level alignment 用途ではない点に注意。

## Failure handling

| 事象 | 挙動 | sidecar | 影響 |
|---|---|---|---|
| `device.connect()` 失敗（USB 認識せず／firmware 不整合） | device を disable、`HardwareError` publish | — | 該当 GoPro 1台のみ影響、他カメラ無事 |
| `set_video_mode()` 失敗（photo モードのまま等） | device を disable、`HardwareError` publish | — | shutter してもファイルできない事態を未然防止 |
| `get_storage_remaining < 500MB` | `FatalHardwareError` で session 起動失敗 | — | 起動時しか起こらない（収録中は別） |
| `shutter_on()` 失敗 | 該当 episode は GoPro 抜きで進む、`HardwareError` 警告 | — | recorder は state を持たない、stop も no-op |
| `media_list` polling timeout（start 時） | `gopro_t0=None`、stop 時に再試行 | — | 整合性は保てる、duration check のみ skip |
| `media_list` 再試行も失敗（stop 時） | enqueue skip、orphan ログ出力 | — | SD に MP4 残置、手動 pull 案内（README） |
| `shutter_off()` 失敗 → 3 回 retry も失敗 | `HardwareError`、enqueue skip | — | SD に MP4 残置、device は disable 候補 |
| **session 中の USB 抜け／device IOError** | shutter/preview/download いずれかで例外、device.disable() | 該当 episode の job が enqueue 済みなら sidecar 残置 → 次回 device 復帰で resume | 以後の episode は GoPro 抜きで進む |
| **photo/timelapse モードで GoPro 起動済み** | connect の `set_video_mode` で video に切替。失敗なら disable。 | — | 起動失敗で気付ける |
| DLWorker 中の `download_file` 失敗 | sidecar 残置、errors publish、worker は次の job へ | 残置 | 次回起動時 restore で再 DL |
| **`shutil.move` 失敗（cross-device、ENOSPC、EACCES）** | tmp 残置、sidecar 残置、errors publish | 残置 | 次回起動時、resume-from-tmp で move からやり直し（再 DL は走らない） |
| MP4 duration が expected より 500ms 以上短い | `HardwareError` 警告（致命ではない）、DL は完遂 | 削除（mark_done） | record loss 疑い。長い側は許容（polling/tail latency 由来） |
| DL中に `probe_sd_size` が device エラーで失敗（USB blip） | 例外で worker が continue、sidecar 残置、次回 session で再試行 | 残置 | 該当 device が `is_disabled=True` になっていれば次の job も skip。session 中の自動復旧はしない |
| **`pending_dir` 不在（初回起動）** | `DLQueue.restore` が `mkdir(parents=True, exist_ok=True)` で作成 | — | 影響無し |
| **同一データセットへの並行 session** | 検出しない（既存制約踏襲）。`mark_done` 競合は最後勝ち | 不定 | README に1セッション/データセットを明記、本 spec では対象外 |
| アプリクラッシュ（SIGKILL 含む） | sidecar が残る → 次回 `DLQueue.restore()` で全件 in-memory queue に再ロード | 残置 | 全 pending が自動再開 |
| GoPro 電池切れ session 中 | shutter/download IOError → device.disable() | sidecar 残置 | 次回 device 復帰時 worker が拾う |

## Multi-GoPro USB realities

USB3 ハブで複数 GoPro を扱う場合の運用ガイド：

- DLWorker は全デバイス横断で **直列**。同時 DL は不可能（実装上の保証）。
- N≥2 なら **別の USB コントローラ root**（物理的に違うチップ）に挿すことを推奨。lsusb -t で tree 構造を確認。
- DL 中の同 GoPro はプレビューが詰まることがある。preview frame drop は許容、`HardwareError` には**しない**。
- 動作検証は最大 2 台まで。3 台以上は本 spec の保証範囲外。

## Pre-implementation verification

実装に入る前に **必ず実機で確認すべき項目**。各項目に明示的な Plan B を持つ：

| # | 確認内容 | Plan B if 失敗 |
|---|---|---|
| 1 | `open_gopro` 最新版の `WiredGoPro` で Hero 11 が `set_date_time`/`set_shutter`/`set_video_mode`/`media_list`/`download_file`/`start_preview`/`stop_preview`/`get_camera_state` を全部サポートしているか | **本 spec を shelve**。BLE+USB ハイブリッド設計を別 spec で起こす（クライアント所有権の単純さが崩れるので別物として扱う） |
| 2 | Hero 11 ファームウェアバージョン（`H22.01.02.32.00` 系）と `open_gopro` の互換性 | 互換ファーム版を README にピン記載、必要なら user に upgrade 指示 |
| 3 | UDP プレビューの実コーデック・解像度・fps（pyav が扱えるか） | pyav が無理なら `ffmpeg` バイナリへの subprocess fallback。preview-only 用途なので低速でも可。Plan B で実装規模ほぼ変わらず |
| 4 | `media_list` polling の latency（shutter_on 後にいつ新ファイルが appear するか実測） | 2.0s で取れない場合は polling timeout を 4.0s に伸ばし、UI に「録画開始まで〜秒」表示。ただし episode 全体が短い時のロスは別途検討 |
| 5 | USB 直挿し vs ハブ経由の DL スループット差（実測） | ハブで著しく遅いなら multi-GoPro 運用の README ガイドで USB コントローラ分散を強く推奨 |

**実装スタート判定**: 1 が PASS であれば着手可。2-5 のうち FAIL したものは spec のパラメータ調整で対応する。1 だけは設計を根本から書き直すことになる。

## Testing

### Unit tests（GoPro 実機なしで CI 実行可）

- `MockGoProDevice` を使った `GoProRecorder.start_episode → stop_episode → enqueue` の通常 flow。
- `MockGoProDevice` で `media_list` polling timeout シミュレーション → stop_episode 側 fallback で sd_filename 取得 → enqueue されること。
- `MockGoProDevice` で start/stop 両方 polling 失敗 → enqueue されない、orphan ログ確認。
- `DLQueue` の永続化／restore（sidecar JSON の create/fsync/delete を tmpdir で確認）。
- `DLWorker` の MP4 duration mismatch 検出（fixture MP4 を使う）。
- `DLWorker` の resume-from-tmp 動作（`shutil.move` を monkeypatch して失敗 → 再起動 → tmp が残ってる前提で再試行 → 今度は成功）。
- **PendingEpisode の preview_only 契約（GoPro 関与なし）**: `Frame(preview_only=True)` を直接構築 → `PendingEpisode.append_row` → video writer は呼ばれない / row は parquet に書かれる、を1つの単体テストで検証する。GoPro mock は不要。
- **Preview source が preview_only=True を emit する積分テスト**: `MockGoProDevice(emit_preview=True)` + `MockGoProPreviewSource` を使い、CameraManager 経由で流れたフレームの `preview_only` フラグを確認する（生成と伝搬の両方）。
- `GoProDeviceRegistry` の name/serial 重複でコンストラクタが ValueError を上げる。
- `init_dataset(gopro_specs=...)` で `info.json.features.observation.images.<gopro>.info.has_gpmf=True` が書かれる。

### Integration tests（GoPro 実機 + USB 接続が必要）

`pytest -m gopro_hardware` で実行。CI からは除外。

- 1 台の Hero 11 で 3 episode 連続収録 → DL → MP4 が `videos/observation.images.<name>/chunk-000/episode_*.mp4` に置かれる。
- 録画した MP4 を `ffprobe -show_streams` して `handler_name=GoPro MET` のトラックがある（GPMF 残存確認）。
- session 中に `kill -9 backend pid` → 再起動 → 未取得の MP4 が dataset に揃う。
- 2 台同時接続で 3 episode 録画 → DL ログを見ると 1 件ずつ順番に処理されている。
- preview UI に GoPro の映像が出ることを目視確認。

### Dev environment for integration tests

- `open_gopro==<version>` を `pyproject.toml` に pin（実装時に確定。verification 段階で実物確認後）。
- Hero 11 firmware: 実装時点で動作確認したバージョンを README に明記。
- USB ケーブル: GoPro 純正 USB-C ケーブル（社外品はネゴシエーション失敗例あり）。
- Fixture MP4: `tests/fixtures/gopro/sample_episode.mp4`（短い実 GoPro 動画、GPMF 込み、~5MB）。リポジトリにバイナリで含める。
- `conftest.py` で `pytest_configure` に `markers = "gopro_hardware: needs physical Hero 11"` を登録、`addopts = -m 'not gopro_hardware'` をデフォルトに。

### CI 設定

- `.github/workflows/...` で unit tests のみ実行（`-m 'not gopro_hardware'`）。
- 著者ローカルで integration test を流す手順を README に記載。

## Out of scope reminders

- **GPMF 抽出 / IMU を parquet 化する処理は本 feature では書かない**。MP4 にそのまま埋まったまま。loader 側の対応は別 feature。
- **シャッター latency 補償のための同期信号（LED 等）は本 feature では入れない**。±1 秒精度で運用する前提。
- **GoPro 設定 UI**（preset 切り替え等）は本 feature では入れない。YAML 編集のみ。`configs/gopros/*.yaml` は手書き（または将来別 spec で UI を足す）。frontend の Settings 系画面（`configs/cameras/` を読む既存画面）には GoPro は出ない — これは設計上の意図。
- **ホットプラグでの session 中 device 再接続**。disable したら基本セッション終了まで disabled。
- **同一データセットへの並行 session の安全化**。既存制約を継続。
