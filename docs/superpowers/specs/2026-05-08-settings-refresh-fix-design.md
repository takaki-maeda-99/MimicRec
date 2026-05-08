# Settings page refresh fix — design

## Problem

Settings ページの Refresh ボタン（Devices セクション）を押しても、USB デバイスの抜き差しが反映されない。バックエンドの uvicorn を再起動するまで古い情報が表示される。

`curl /api/settings/devices/serial` と `curl /api/settings/devices/cameras` は呼ぶたびに /dev を読み直して新鮮なレスポンスを返すことを確認済み。バックエンド側に永続化キャッシュは無い。

## Root cause (hypothesis)

ブラウザ側の HTTP キャッシュ。

- `apiFetch` (`frontend/src/api/client.ts`) は `fetch()` の `cache` を指定していないため、`"default"` モードになる
- バックエンドのレスポンスには `Cache-Control` も `Last-Modified` も `ETag` も付いていない
- Chrome は heuristic freshness で短期キャッシュを行い得る
- 結果、Refresh クリックの fetch がディスクキャッシュから即返り、バックエンドまでリクエストが届かない
- サーバー再起動時にユーザーが F5 する（または Vite の WS 切断 → 自動リロード）とキャッシュが効かなくなって新鮮なデータが返る

シリアルとカメラの両方が同じ症状を示すという対称性が、共通レイヤ（`fetch` のキャッシュ）が原因という仮説を支持する。`cv2` 固有の問題ならシリアルは正常に動くはず。

加えて `SettingsPage.tsx` の `.catch(() => {})` がエラーを完全に握り潰しているため、失敗時に画面に何も出ず、ユーザーは「効いていない」と感じやすい状態になっている。

## Fix

3 段構え。最小フィックス + 防御 + UX 改善。

### A. フロントエンド (必須)

`frontend/src/api/client.ts`:
- `apiFetch` のデフォルト `cache` を `"no-store"` に。`opts` で上書き可能。

`frontend/src/pages/SettingsPage.tsx`:
- `.catch(() => {})` を消す。エラー時は alert で表示。
- Devices 用に `loading` ステート (`refreshingDevices` など) を追加し、Refresh ボタンに反映 (disabled + ラベル "Refreshing...")。
- Configs と Calibration のセクションに同様の Refresh ボタンを追加し、同じロジックで動かす。
- Devices Refresh ボタンの隣に「Last refreshed: HH:MM:SS」を表示 (任意。仕様としては「最低限ボタン押下が反映された視覚フィードバックがある」)。

### B. バックエンド (防御的)

`backend/mimicrec/api/routes/settings.py`:
- `list_serial_ports`, `list_camera_devices`, `list_calibrations`, `list_group_configs`, `get_config` の各 GET エンドポイントに `Response` ヘッダー `Cache-Control: no-store` を付与。
- 実装は FastAPI の `Response` パラメータ注入で行う:
  ```python
  @router.get("/settings/devices/serial")
  async def list_serial_ports(response: Response):
      response.headers["Cache-Control"] = "no-store"
      ...
  ```
  あるいはミドルウェアで `/api/settings/*` 全体に当てる。今回は個別エンドポイントに付ける方を選ぶ（影響範囲が局所的なので）。

### C. UX (Configs/Calibration の Refresh ボタン追加)

ユーザー要望に従い、Configurations と Calibration セクションにもリフレッシュボタンを設置。Devices と同じパターン。

## Out of scope

- バックエンドの `cv2.VideoCapture` 内部状態の詰め直し（今回の症状はキャッシュで説明可能なので、優先度低）
- React Query への移行（最小フィックスを優先）
- Refresh の自動化（フォーカス時、定期）

## Verification plan

1. ユーザーが手動で実機検証:
   - バックエンド起動後に USB シリアル / USB カメラを抜き差しして、Refresh ボタンで反映されることを確認
   - 失敗時に alert が出ることを確認
2. 既存テスト (`pytest`) がグリーンのまま
3. `pnpm typecheck` (frontend) がグリーン

## Files changed

- `frontend/src/api/client.ts` — `cache: "no-store"` デフォルト化
- `frontend/src/pages/SettingsPage.tsx` — エラー表示、loading 状態、Configs/Calibration の Refresh ボタン
- `backend/mimicrec/api/routes/settings.py` — `Cache-Control: no-store` ヘッダー

## Risk

- `cache: "no-store"` をデフォルトにすると、すべての `apiFetch` 呼び出しがネットワークを叩く。Settings 以外の頻繁にポーリングする箇所（`/api/session/state` を 2 秒間隔）にも影響するが、これは元々 `useQuery` 経由で react-query の cache を使っているので問題なし。`apiFetch` 自体の挙動変更はネットワーク負荷を僅かに増やすだけで、機能影響は無いはず。
