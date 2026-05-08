# Camera capability selection — design

## Problem

`configs/cameras/*.yaml` は今 `device_id` / `width` / `height` しか持たない。`OpenCVCamera` は cv2 のデフォルト fourcc で開くため、UVC カメラだと多くの場合 YUYV にネゴシエートされ、1280×720 が 10fps に落ちる。ユーザーは MJPEG を選んで 30fps を出したいが、選択肢を知る手段も指定する手段も無い。

加えて関連する既知バグ: `backend/mimicrec/recording/dataset_layout.py:73,76` が info.json の `shape` / `video.width` / `video.height` を `480×640` 固定書き込みしており、実 mp4 解像度との不整合がデータセットメタデータに残る。

## Goals

1. Settings の Edit モーダルから、各カメラの利用可能な (pixel format, resolution, capture fps) を見て選択して、camera YAML に保存できる。
2. 保存された値で OpenCVCamera が実際に開けることを保証する (cv2 が黙ってネゴシエートを変えるなら検出して止める)。
3. 同じ feature の中で info.json 解像度ハードコードを直して、実カメラ解像度を info.json に書き込む。

## Non-goals (Out of scope)

- 露出 / ゲイン / ホワイトバランス等の V4L2 controls (露出制御は別 feature)
- カメラのホットプラグや、セッション中の解像度変更
- 同一 `device_id` を 2 つの YAML から指している場合の検証
- Multi-plane formats (`(mplane)`) — cv2 V4L2 backend が非対応なので parser でフィルタ
- Stepwise / Continuous frame size を持つフォーマット (主に H264 のソフトウェアエンコーダ系) — parser で skip し UI には出さない (将来必要なら別 feature)
- 録画 codec / pix_fmt の選択 (`info.json` の `video.codec=libx264`, `video.pix_fmt=yuv420p` は PyAV エンコーダ側の話で、本 feature が触る V4L2 capture format とは別レイヤ)
- MockCamera / SimCamera 用の構造化 UI (今回は `_target_ === mimicrec.cameras.opencv_camera.OpenCVCamera` のときだけ構造化フォーム)
- `/dev/videoN` 番号の永続安定化 (USB 再接続で番号が変わる場合がある — 別途 udev rules 等の運用課題)

## Architecture overview

```
┌────────────────────────────────────┐
│ Frontend (Edit modal)              │
│                                    │
│  [editingConfig.group === "cameras"│      GET /api/settings/devices/cameras/{device_id}/capabilities
│   && _target_ === OpenCVCamera] ── │ ──────────────────────────────────────────────────────────▶
│   ┌──────────────────────────────┐ │      JSON: list[FormatCaps]
│   │ CameraConfigForm             │ │ ◀──────────────────────────────────────────────────────────
│   │ - device_id: <select>        │ │
│   │ - pixel_format: <select>     │ │      PUT /api/settings/configs/cameras/{name}
│   │ - width x height: <select>   │ │ ──────────────────────────────────────────────────────────▶
│   │ - capture_fps: <select>      │ │      (server validates by opening the camera, then writes YAML)
│   │ [Cancel] [Save]              │ │ ◀──────────────────────────────────────────────────────────
│   └──────────────────────────────┘ │      200 (saved) | 409 (validation failed: cv2 negotiated diff)
│                                    │
│  [other group OR not OpenCVCamera] │
│   既存の JSON textarea (no change) │
└────────────────────────────────────┘
```

## Components

### Backend new

#### `backend/mimicrec/cameras/v4l2_caps.py`

```python
@dataclass
class FrameSize:
    width: int
    height: int
    fps: list[int]  # discrete frame rates available at this size

@dataclass
class FormatCaps:
    fourcc: str       # 4-char code, e.g. "MJPG", "YUYV"
    description: str  # human label, e.g. "Motion-JPEG (compressed)"
    sizes: list[FrameSize]

def enumerate_capabilities(device_path: str) -> list[FormatCaps]:
    """Shell out to `v4l2-ctl --list-formats-ext --device=<path>` and parse stdout.

    Returns:
        list of FormatCaps; empty list if v4l2-ctl is unavailable or device cannot be queried.

    Skipped silently:
        - multiplane formats (description contains "(mplane)")
        - stepwise / continuous frame sizes
        - stepwise / continuous frame intervals
    """
```

Parsing rule reference: `v4l2-ctl --list-formats-ext` の出力構造:

```
ioctl: VIDIOC_ENUM_FMT
    Type: Video Capture
    [0]: 'MJPG' (Motion-JPEG, compressed)
        Size: Discrete 1280x720
            Interval: Discrete 0.033s (30.000 fps)
        ...
```

`Type: Video Capture` だけ採択。`Type: Video Capture Multiplanar` などは無視。

#### `GET /api/settings/devices/cameras/{device_id}/capabilities`

`device_id` は整数 (`/dev/video<N>` の N)。response は `list[FormatCaps]`。

エラー処理:
- v4l2-ctl コマンド失敗 / unavailable → 200 with `[]` (空リスト)。フロントは "capabilities unavailable, fallback to manual edit" を表示。
- `/dev/video{N}` が存在しないか cv2 で open できないノード → 404
- すべての応答に `Cache-Control: no-store` (settings の他の GET と同じ)

#### `PUT /api/settings/configs/cameras/{name}` (validate before write)

既存エンドポイントを拡張。リクエスト body は今まで通り `{"content": <yaml dict>}`。

`content._target_ == "mimicrec.cameras.opencv_camera.OpenCVCamera"` のとき:
1. 仮の `OpenCVCamera` を構築 (`device_id` / `width` / `height` / `pixel_format` / `capture_fps`)
2. `cap.open()` を試行
3. `cap.get(CAP_PROP_FOURCC)` / `CAP_PROP_FRAME_WIDTH` / `CAP_PROP_FRAME_HEIGHT` / `CAP_PROP_FPS` を読み戻し、要求と一致するか比較
4. 一致 → `cap.release()` → YAML 書き込み (既存ロジック)
5. 不一致 → `cap.release()` → 409 Conflict + `{"detail": "validation failed: requested MJPG/1920x1080@30, got YUYV/1920x1080@10"}`
6. カメラがビジー (`isOpened() == False`) → 検証スキップ + 200 + warning header `X-Validation-Skipped: device-busy` (フロント側で「バリデーションは session 開始時まで延期されました」を出す)

`_target_` が OpenCVCamera 以外なら検証ロジック無し (現状通り)。

### Backend modified

#### `backend/mimicrec/cameras/opencv_camera.py`

```python
class OpenCVCamera:
    def __init__(
        self,
        name: str,
        device_id: int = 0,
        width: int = 640,
        height: int = 480,
        pixel_format: str | None = None,
        capture_fps: int | None = None,
    ): ...

    def _open(self):
        path = f"/dev/video{self._device_id}"
        self._cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
        if not self._cap.isOpened():
            self._cap = cv2.VideoCapture(self._device_id)
        if not self._cap.isOpened():
            raise RuntimeError(f"cannot open camera {self._device_id} ({path})")

        # Property setting order (V4L2 typical):
        # fourcc → width/height → fps
        if self._pixel_format is not None:
            self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self._pixel_format))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        if self._capture_fps is not None:
            self._cap.set(cv2.CAP_PROP_FPS, self._capture_fps)

        # Strict readback validation (per user decision):
        self._verify_negotiated_or_raise()

    def _verify_negotiated_or_raise(self):
        actual_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fourcc = _decode_fourcc(int(self._cap.get(cv2.CAP_PROP_FOURCC)))
        actual_fps = int(round(self._cap.get(cv2.CAP_PROP_FPS)))

        mismatches = []
        if actual_w != self._width or actual_h != self._height:
            mismatches.append(f"size: requested {self._width}x{self._height}, got {actual_w}x{actual_h}")
        if self._pixel_format is not None and actual_fourcc != self._pixel_format:
            mismatches.append(f"fourcc: requested {self._pixel_format}, got {actual_fourcc}")
        if self._capture_fps is not None and actual_fps != self._capture_fps:
            mismatches.append(f"fps: requested {self._capture_fps}, got {actual_fps}")

        if mismatches:
            self._cap.release()
            raise RuntimeError(
                f"camera {self.name}: cv2 negotiated different parameters: {'; '.join(mismatches)}"
            )
```

`_decode_fourcc(int)` は 4-byte unsigned int を 4-char string に変換するユーティリティ。

#### `backend/mimicrec/recording/dataset_layout.py`

`init_dataset()` のシグネチャを修正し、ハードコード `480×640` をカメラごとの実値で置換:

```python
def init_dataset(
    root: Path,
    *,
    fps: int,
    joint_names: list[str],
    camera_names: list[str],
    camera_resolutions: dict[str, tuple[int, int]],  # NEW: {camera_name: (width, height)}
    robot_type: str,
    gripper_convention: dict | None = None,
    proprio_layout: dict | None = None,
):
    ...
    for cam in camera_names:
        w, h = camera_resolutions[cam]  # was: hardcoded 480/640
        info["features"][f"observation.images.{cam}"] = {
            "shape": [h, w, 3],
            "names": ["height", "width", "channels"],
            "video": {
                "video.height": h, "video.width": w,
                ...
            }
        }
```

#### Caller update: `backend/mimicrec/api/deps.py::create_session_from_request`

`init_dataset` の呼び出し時にカメラ解像度 dict を渡す:

```python
camera_resolutions = {
    cam_name: (int(cam_cfgs[cam_name]["width"]), int(cam_cfgs[cam_name]["height"]))
    for cam_name in req.cameras
}
init_dataset(ds_root, ..., camera_resolutions=camera_resolutions, ...)
```

YAML に `width` / `height` が無い (MockCamera 等) ケース: その adapter は `device_id` も無く `OpenCVCamera` でもないので、camera_resolutions に含めない or fallback として adapter インスタンスから読む。`MockCamera(width=64, height=48)` のような値もコンストラクタ引数で持っているので `cam_kwargs.get("width", ...)` で取れる。

### Frontend new

#### `frontend/src/api/cameras.ts`

```ts
export interface FrameSize { width: number; height: number; fps: number[]; }
export interface FormatCaps { fourcc: string; description: string; sizes: FrameSize[]; }

export const fetchCameraCapabilities = (deviceId: number) =>
  apiFetch<FormatCaps[]>(`/api/settings/devices/cameras/${deviceId}/capabilities`);
```

#### `frontend/src/components/CameraConfigForm.tsx`

Props: `{ name, currentContent, detectedCameras, onSave, onCancel }`.

State: `deviceId`, `pixelFormat`, `width`, `height`, `captureFps`, `capabilities`, `loading`, `error`.

ロジック:
- `deviceId` が変わったら capabilities を再取得 (selection の cascading dropdown を再構成)
- `pixelFormat` 選択肢 = `capabilities.map(f => f.fourcc)`
- `(width, height)` 選択肢 = 選択中 format の `sizes`
- `captureFps` 選択肢 = 選択中 (format, size) の `fps[]`
- 初期値: 既存 YAML の値があればそれをデフォルト選択 (capabilities 取得後にマッチを探す)
- Save クリック時: `apiFetch(...PUT...)` を呼んで、409 Conflict なら error フィールドに detail 表示、200 なら閉じて `loadConfigs()` を呼ぶ
- 200 with `X-Validation-Skipped: device-busy` ヘッダーがあれば「保存されました (検証は session 開始時まで延期)」を出す

### Frontend modified

#### `frontend/src/pages/SettingsPage.tsx`

Edit モーダル内の textarea を、条件付きで `CameraConfigForm` に置換:

```tsx
{editingConfig.group === "cameras"
 && (editingConfig.content as any)._target_ === "mimicrec.cameras.opencv_camera.OpenCVCamera"
  ? <CameraConfigForm
      name={editingConfig.name}
      currentContent={editingConfig.content}
      detectedCameras={cameras}
      onSave={() => { setEditingConfig(null); loadConfigs(); }}
      onCancel={() => setEditingConfig(null)}
    />
  : <textarea ... />}
```

`detectedCameras` は既存の `cameras` ステート (Devices セクションが既に保持している `available` cameras リスト)。

## Data flow

### 編集フロー

1. User は SettingsPage で `cameras/wrist` の Edit ボタンをクリック
2. `editingConfig` が set され、モーダルが開く
3. `_target_ === "...OpenCVCamera"` なので `CameraConfigForm` がレンダー
4. CameraConfigForm マウント時に `fetchCameraCapabilities(currentContent.device_id)` を呼ぶ
5. ドロップダウンは capabilities でフィルタされて表示。現在の YAML 値が選択肢にあれば pre-select、無ければ最初の選択肢にフォールバック
6. User が値を変えて Save
7. PUT /api/settings/configs/cameras/wrist が走る
8. バックエンドは検証 (open & readback) → 一致なら YAML 書き込み、不一致なら 409
9. 成功なら `loadConfigs()` でリストを refresh

### 録画フロー (info.json fix)

1. User がセッション開始 (POST /api/session/start)
2. `create_session_from_request` で各 cam YAML を読み、`camera_resolutions` dict を構築
3. `init_dataset()` がそれを受け取り info.json に正しい (width, height) を書き込む
4. `manager.start()` で `OpenCVCamera._open()` が走り、strict readback で要求と negotiated が一致しているか検証
5. 一致しなければ RuntimeError → セッション起動失敗 (既存の `_run_camera` 例外ハンドリング経由でユーザーに伝播)
6. 一致すれば録画は始まる。Mp4EpisodeWriter は frame buffer から実寸を読むので mp4 と info.json は一致

## Error handling

| エラー | 振る舞い |
|---|---|
| v4l2-ctl 未インストール | capabilities = `[]`、フロントは「キャパビリティ取得不可」表示、JSON textarea にフォールバックは無し (構造化フォームのまま、ドロップダウンが空) |
| `/dev/video{N}` 無し | capabilities endpoint が 404、フロントは「デバイス未検出」表示 |
| Save 時 cv2 negotiate ミスマッチ | PUT が 409 + detail。フロントは modal 内に error バナー、YAML は書き込まない |
| Save 時 カメラビジー | PUT が 200 + `X-Validation-Skipped: device-busy`。YAML は書き込まれる。session_start で再検証される |
| Session 起動時 ミスマッチ | `OpenCVCamera._open()` が RuntimeError → `_run_camera` がログ出して return (既存挙動)。session 自体は開始されるが、当該カメラだけ未接続。ユーザーは Settings で見直す |
| YAML に `pixel_format` / `capture_fps` が無い | adapter は今まで通り cv2 デフォルトで開く。strict readback はその場合 fourcc / fps の比較を skip (「未指定」は「指定無し」として扱う) |

## Testing

### Backend

- `tests/unit/test_v4l2_caps.py` (NEW) — `tests/unit/test_camera_manager.py` 隣接
  - Fixture は同ファイル内の multi-line string 定数 (実機の v4l2-ctl 出力をキャプチャしたもの)
  - `test_parse_uvc_camera()` — 典型的な UVC 出力をパースして 2 format × N サイズ × M fps を返すことを assert
  - `test_skips_multiplane_format()` — `(mplane)` ラベル付きフォーマットを除外
  - `test_skips_stepwise_size()` — Stepwise エントリは含まれない
  - `test_v4l2_ctl_missing_returns_empty()` — v4l2-ctl が 127 や FileNotFoundError を返したとき `[]`
- `tests/api/test_settings_routes.py` (EXTEND)
  - `test_camera_capabilities_returns_parsed_list(monkeypatch)` — `enumerate_capabilities` を monkeypatch して JSON 形を確認
  - `test_camera_capabilities_has_no_store_cache_control()` — 既存の Cache-Control 慣習に揃える
  - `test_camera_capabilities_returns_404_for_missing_device()`
  - `test_put_camera_config_validates_and_writes(tmp_path, monkeypatch)` — open & readback を monkeypatch、一致時に YAML 書き込み
  - `test_put_camera_config_returns_409_on_mismatch(monkeypatch)` — 不一致時 409 で YAML 未変更
  - `test_put_camera_config_skips_validation_when_busy(monkeypatch)` — `isOpened()=False` でスキップ + warning header
- `tests/unit/test_dataset_layout.py` (NEW) — `tests/unit/test_exporter_info_json.py` 隣接
  - `test_init_dataset_writes_per_camera_resolution()` — `camera_resolutions={"wrist": (1920, 1080), "front": (640, 480)}` で渡し info.json の `shape` / `video.width` / `video.height` を検証

### Frontend

- 自動テストは現状フロントに無いので、手動検証 (実機 + 単体検証):
  - 実機で MJPG 1920×1080@30 を選択 → Save → wrist.yaml が更新される
  - その状態でセッション開始 → mp4 が 1920×1080、info.json も 1920×1080
  - わざと未対応の組み合わせ (架空) を直接 YAML に書いて session_start → RuntimeError
  - `pnpm exec tsc --noEmit` クリーン

## Decision log

| 決定 | 選択 | 理由 |
|---|---|---|
| 能力列挙の手段 | `v4l2-ctl` シェルアウト | 環境にあり、出力フォーマット安定、依存ゼロ、parser テストが書きやすい |
| FPS 名 | `capture_fps` | session 側 `fps` (録画レート) との衝突回避 |
| Mismatch 時 | session_start で RuntimeError | ユーザーが意図しない fourcc/fps で録画されるリスクを避ける |
| Save 時 検証 | open/readback して 409 で early-fail | session_start 失敗より UX が早い。ビジー時は session_start に延期 |
| info.json 修正 | 同 spec で実施 | 解像度を選べるようにすると不整合がより目立つ。両方直さないと意味が半減 |
| Stepwise / mplane | parser で skip | cv2 V4L2 backend が非対応 |
| MockCamera/SimCamera 用 UI | `_target_` でゲート、textarea のまま | device_id を持たないので構造化フォームに無理がある |

## Risk

- **`v4l2-ctl` 出力フォーマット変更**: 上流が変えると parser が壊れる。緩和策: fixture テストで CI 検出、catch-all で `[]` フォールバック (frontend は「取得不可」表示)
- **cv2 readback と実 streaming のずれ**: cap.get() が嘘をつくケースがゼロでない (一部のドライバ)。緩和策: 実際の最初のフレームの shape も session_start で確認する後続 enhancement (今回は scope 外、必要なら別 feature で追加)
- **`/dev/video<N>` 番号が安定しない**: 実機で USB を抜き差しすると wrist.yaml の `device_id: 0` が別カメラを指す可能性。緩和策: spec で OOS と明記、別途 udev rules で対応 (運用課題)
- **同時編集の競合**: 二人が同じ wrist.yaml を編集しても overwrite される (既存挙動)。本 feature では変更無し
- **`init_dataset` シグネチャ変更による下位互換**: テストや別の呼び出し箇所で壊れる可能性。緩和策: `camera_resolutions: dict[...] | None = None` にして None なら従来の hardcode に fallback、ただし migration 期間後にデフォルト None を撤去 — もしくは破壊的変更で 1 回直す。今回は **破壊的変更 (None デフォルト無し) を選ぶ** — 呼び出し箇所は `deps.py` の 1 箇所のみで grep 容易

## Files changed

**New:**
- `backend/mimicrec/cameras/v4l2_caps.py`
- `tests/unit/test_v4l2_caps.py` (fixture data inline)
- `tests/unit/test_dataset_layout.py`
- `frontend/src/api/cameras.ts`
- `frontend/src/components/CameraConfigForm.tsx`

**Modified:**
- `backend/mimicrec/cameras/opencv_camera.py` (kwargs 追加 + readback 検証)
- `backend/mimicrec/api/routes/settings.py` (capabilities endpoint, PUT validation)
- `backend/mimicrec/recording/dataset_layout.py` (`init_dataset` シグネチャに `camera_resolutions`)
- `backend/mimicrec/api/deps.py` (`create_session_from_request` から `camera_resolutions` を渡す)
- `frontend/src/pages/SettingsPage.tsx` (Edit モーダルの分岐)
- `tests/api/test_settings_routes.py` (新エンドポイント + PUT 検証)

**Memory cleanup:**
- `~/.claude/projects/-home-tirobot-MimicRec/memory/MEMORY.md` から info.json バグエントリを削除 (修正されたので)
- `bug_info_json_resolution_hardcoded.md` を削除 (同上)
