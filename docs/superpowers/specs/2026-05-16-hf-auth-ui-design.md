# Hugging Face auth — UI 完結化 design

## Problem

現状の HF Hub push 機能は実装済み（`backend/mimicrec/cloud/hf_pusher.py`、`backend/mimicrec/api/routes/cloud.py`、`frontend/src/pages/DatasetsPage.tsx`）だが、**認証だけはターミナルから `huggingface-cli login` を叩かないと通せない**。UI からは「未認証です」状態しか見えず、push を試すと 401 が返るだけでフロー上の段差が大きい。

これを **UI 上でトークンを貼ってログイン/ログアウト完結** にする。push 系コードのロジックは触らず、認証経路だけを「ターミナル必須 → UI で完結」に置き換える。

## Goals

1. Settings ページから HF アクセストークンを入力 → 検証 → 保存 がワンパスで完結する。
2. **既存 push コードを変更しない**：認証は引き続き `huggingface_hub.get_token()` 経由（CLI キャッシュ流用）。
3. ログアウトもボタン1つで完結（CLI キャッシュ削除）。
4. 既に `huggingface-cli login` 済みの環境ではその username を UI に反映する（後方互換）。
5. 無効トークン・空トークンを保存に進めず、明確なエラーで返す。
6. `HF_TOKEN` 等の環境変数経由の認証は尊重し、誤って消そうとした場合にユーザに状況を説明する。

## Definition of done

- [ ] Settings ページに「Cloud / Hugging Face」セクションが追加されている。
- [ ] 未認証状態でトークン入力 → Save → スピナー → `@username` 表示までが UI 上で完結する（CLI を一切開かない）。
- [ ] 認証済状態で Logout 押下 → 未認証状態に戻る。
- [ ] 既に `huggingface-cli login` 済の環境で Settings を開くと、`@username` が表示される。
- [ ] 無効トークンを Save すると 401 が返り、入力欄下にエラーが表示され、キャッシュには書かれない。
- [ ] 空/空白だけのトークンは frontend 側の trim チェックでサーバまで送られない（"Please paste a token." 表示）。defense-in-depth として backend も同 body を受けたら 400 を返す（直接 curl 等経由）。
- [ ] `HF_TOKEN` 環境変数で認証されている状態では Login も Logout も 409 を返し、UI 側でボタンが disabled + 「`HF_TOKEN` env var を unset してから操作してください」と説明される。CLI キャッシュには手を出さない。
- [ ] Login 直後にサイドバーの `hub: @username` が更新される（`hf-auth-changed` CustomEvent で SidebarStatus が refetch）。
- [ ] `huggingface_hub.login()` 内部でディスク書き込みに失敗した場合、サーバは 500 を返し、`auth_cache` は **古い値で残らず invalidate** されている。
- [ ] `huggingface_hub.logout()` が例外を投げた場合、サーバは 500 を返す（握り潰さない）。
- [ ] `whoami` が成功したが `name` フィールドが取れなかった場合、401 ではなく 502 "unexpected response from Hugging Face" を返す。
- [ ] `POST /api/cloud/login` と `/cloud/logout` は `Origin` header が同一オリジンでない場合 403 を返す（簡易 CSRF 防御）。
- [ ] 既存 `POST /api/datasets/{ds}/hub/push` の 401 エラーメッセージが「Settings → Hugging Face からサインインしてください」を案内する形に更新されている。
- [ ] Token がレスポンスログ・エラーメッセージ・**ディスク永続化先（hub.json などアプリ固有）**・**サーバ側プロセスメモリ（route 関数 local 変数より長生きする場所）** のいずれにも残らない。フロントの component-local state には失敗時のみリトライ用に in-memory で保持され、success/unmount で消える（後述）。
- [ ] tests: `tests/api/test_cloud_auth.py` に login/logout の正常 + 異常パスをカバーする unit + API test がある。

## Non-goals

- **OAuth Device Flow**：将来検討。本 PR ではトークン直接入力のみ。
- **暗号化保存**：HF CLI 自身が `~/.cache/huggingface/token` を平文で持っているため整合的に平文のままにする。アプリ側で追加の暗号化はしない。
- **トークンの自動 rotation / refresh**：HF トークンは長期発行が前提。期限切れの自動 refresh はしない。
- **Multi-user 対応**：MimicRec は単一マシン・単一ユーザー前提のローカルアプリ。複数アカウント切替や per-dataset の別トークン指定は対象外。
- **既存 push 機能の挙動変更**：`hf_pusher.py` / `snapshot.py` / `push_state.py` の中身は触らない。
- **サイドバー `hub:` 行のクリッカブル化**：本 PR ではラベル/ステータス表示のみで、Settings 遷移リンクは追加しない（後続改修）。
- **`HUGGING_FACE_HUB_TOKEN` 以外のレガシー env var**（`HUGGINGFACE_HUB_TOKEN` 等）への網羅対応：`huggingface_hub` が公式にサポートする `HF_TOKEN` と `HUGGING_FACE_HUB_TOKEN` の2つだけ env-locked 検出に使う。

## Decisions summary

| 項目 | 決定 | 補足 |
|---|---|---|
| 認証保存先 | `~/.cache/huggingface/token` (CLI と同じ) | `huggingface_hub.login(token, add_to_git_credential=False)` を呼ぶ |
| 認証取得 | `huggingface_hub.get_token()` のまま | 既存 push コード変更ゼロ |
| Save 時の検証 | `HfApi().whoami(token=token)` で必ず検証 | 通った場合のみ `login()` を呼ぶ |
| トークン形式 | 任意の HF token 文字列を受け入れる | `hf_` プレフィクス強制はしない（HF 側で形式変更がありうるため）|
| Logout 動作 | `huggingface_hub.logout()` | env-locked 時は **Login も Logout も 409 で拒否**（理由: env-locked 中は `get_token()` が env 値を優先するため CLI キャッシュをいじっても無意味かつ混乱の元） |
| Env-locked 検出 | `HF_TOKEN` または `HUGGING_FACE_HUB_TOKEN` が set かつ非空 | これら以外の経路は env-locked と判定しない |
| `whoami` の name 欠落時 | 502 "unexpected response from Hugging Face" | 401 は誤誘導なので避ける |
| `hf_login()` の失敗 | 500 を返し、cache invalidation は `try/finally` で必ず実行 | 古い cache 値が残らないこと |
| `hf_logout()` の失敗 | 例外を握り潰さず 500 を返す | "204 を返したのに実は消えていない" 状態を作らない |
| トークン送信 | HTTP body (JSON) のみ | クエリ文字列禁止 |
| トークンの masking | `<input type="password">` | コピー貼り付けは許可 |
| Frontend での state 保持 | **Save 成功時 or unmount でクリア**。失敗時はリトライ用にコンポーネント local state に保持する（永続化なし、ログ出力なし、DOM 表示は masking 維持） | 完全 0 ではなく "in-memory only" と spec で明記する |
| 認証キャッシュ | login/logout の前に **try/finally で必ず invalidate** | 中途半端な状態を作らない |
| エラー UI | インライン赤帯（入力欄下） | toast は出さない |
| サイドバー hub: 行更新 | login/logout 後に `window.dispatchEvent(new CustomEvent("hf-auth-changed"))`、SidebarStatus が listen して refetch | shared store 導入は避ける（既存パターンを壊さない） |
| CSRF 防御 | `/cloud/login` と `/cloud/logout` で `Origin` header の **same-origin チェック**、不一致なら 403 | localhost 攻撃面の最低限カバー |
| 既存 push 401 メッセージ | 文言のみ更新 | "Settings → Hugging Face からサインインしてください" |

## Architecture

```
Frontend (React)
└─ SettingsPage
    └─ HuggingFaceCard.tsx  (新規)
        ├─ GET  /api/cloud/auth-status     既存
        ├─ POST /api/cloud/login           新規  body: { token }
        └─ POST /api/cloud/logout          新規

Backend (FastAPI)
└─ api/routes/cloud.py
    ├─ GET  /cloud/auth-status   既存・拡張（env_locked フィールドを返す）
    ├─ POST /cloud/login         新規
    └─ POST /cloud/logout        新規

(push パス: 既存のまま無変更)
```

## Components

### Backend: `backend/mimicrec/api/routes/cloud.py` への追加

```python
import os
from huggingface_hub import HfApi, login as hf_login, logout as hf_logout, get_token
from huggingface_hub.errors import HfHubHTTPError  # 正規パス (verified on huggingface_hub 0.35.x)

_ENV_TOKEN_VARS = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")


class LoginRequest(BaseModel):
    token: str = Field(..., min_length=1)


def _env_token_present() -> bool:
    return any(os.environ.get(v, "").strip() for v in _ENV_TOKEN_VARS)


def _invalidate_auth_cache(request: Request) -> None:
    request.app.state.auth_cache = None


def _require_same_origin(request: Request) -> None:
    """Reject cross-origin POSTs (minimal CSRF guard for localhost)."""
    origin = request.headers.get("origin")
    if origin is None:
        # Same-origin browser requests omit Origin only for safe methods;
        # for POST/PUT/DELETE we always expect it from fetch/XHR.
        raise HTTPException(status_code=403, detail="origin header required")
    expected = f"{request.url.scheme}://{request.url.netloc}"
    if origin != expected:
        raise HTTPException(status_code=403, detail="cross-origin request rejected")


@router.post("/cloud/login")
async def cloud_login(request: Request, body: LoginRequest) -> AuthStatus:
    _require_same_origin(request)
    if _env_token_present():
        raise HTTPException(
            status_code=409,
            detail="HF_TOKEN env var is set; unset it before signing in from the UI",
        )

    token = body.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="token is required")

    # 1) validate via whoami
    try:
        who = HfApi().whoami(token=token)
    except HfHubHTTPError as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        if code in (401, 403):
            raise HTTPException(status_code=401, detail="invalid token")
        raise HTTPException(status_code=503, detail="could not reach Hugging Face")
    except Exception:
        raise HTTPException(status_code=503, detail="could not reach Hugging Face")

    # whoami returns Dict per huggingface_hub 0.35.x; no attr fallback needed.
    username = who.get("name") if isinstance(who, dict) else None
    if not username:
        # 200 OK but missing identity — surface as upstream protocol error, not "invalid token".
        raise HTTPException(status_code=502, detail="unexpected response from Hugging Face")

    # 2) write CLI cache. Cache invalidation is guaranteed by try/finally so we
    #    don't leak a stale auth_cache value if hf_login() raises.
    try:
        try:
            hf_login(token=token, add_to_git_credential=False)
        except Exception:
            # disk full / permission / library validation. Do NOT include token in message.
            raise HTTPException(status_code=500, detail="failed to persist auth token")
    finally:
        _invalidate_auth_cache(request)

    value = {
        "authenticated": True,
        "username": username,
        "checked_at": _iso_now(),
        "env_locked": False,  # branch above guarantees env is not set
    }
    request.app.state.auth_cache = {"t": time.monotonic(), "value": value}
    return AuthStatus(**value)


@router.post("/cloud/logout", status_code=204)
async def cloud_logout(request: Request):
    _require_same_origin(request)
    if _env_token_present():
        raise HTTPException(
            status_code=409,
            detail="token is provided via HF_TOKEN env var; unset it to log out",
        )
    try:
        try:
            hf_logout()
        except Exception:
            # Real failure (permission / FS error). Do not return 204 if delete didn't happen.
            raise HTTPException(status_code=500, detail="failed to clear stored auth token")
    finally:
        _invalidate_auth_cache(request)
    return None
```

**重要**: token は `detail` / ログ / 例外メッセージのいずれにも含めない（"invalid token" / "failed to persist auth token" など token-free な文字列のみ）。`HfHubHTTPError` のレスポンスボディは token を含まないが、念のため `str(e)` をそのまま返さない設計にする。

**`auth-status` 側にも修正が必要**:

```python
@router.get("/cloud/auth-status")
async def auth_status(request: Request, refresh: int = 0) -> AuthStatus:
    cache = getattr(request.app.state, "auth_cache", None)
    now = time.monotonic()
    if not refresh and cache is not None and now - cache["t"] < _AUTH_TTL_SEC:
        return AuthStatus(**cache["value"])

    env_locked = _env_token_present()
    token = get_token()
    authenticated = False
    username: str | None = None
    if token:
        try:
            who = HfApi().whoami(token=token)
            username = who.get("name") if isinstance(who, dict) else None
            authenticated = username is not None
        except Exception:
            authenticated = False
    value = {
        "authenticated": authenticated,
        "username": username,
        "checked_at": _iso_now(),
        "env_locked": env_locked,
    }
    request.app.state.auth_cache = {"t": now, "value": value}
    return AuthStatus(**value)
```

`AuthStatus` モデルにも `env_locked: bool` を追加（既存 `auth-status` のレスポンスにも反映される、フロントが両方で同じ shape を期待できる）。

### Frontend: 新規 `frontend/src/components/HuggingFaceCard.tsx`

```tsx
type Mode = "idle" | "saving" | "loggingOut";

const AUTH_CHANGED_EVENT = "hf-auth-changed";

export function HuggingFaceCard() {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [mode, setMode] = useState<Mode>("idle");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const envLocked = auth?.env_locked ?? false;

  useEffect(() => {
    fetchAuthStatus().then(setAuth).catch(() => setAuth(null));
  }, []);

  // 成功時のみ token state を空に戻す。失敗時はリトライ用に保持
  // （永続化なし、コンポーネント local memory のみ）。
  const onSave = async () => {
    const t = token.trim();
    if (!t) {
      setError("Please paste a token.");
      return;
    }
    setMode("saving");
    setError(null);
    try {
      const next = await postLogin(t);
      setAuth(next);
      setToken("");
      window.dispatchEvent(new CustomEvent(AUTH_CHANGED_EVENT));  // サイドバー refetch トリガ
    } catch (e) {
      setError(humanReadable(e));
    } finally {
      setMode("idle");
    }
  };

  const onLogout = async () => {
    setMode("loggingOut");
    setError(null);
    try {
      await postLogout();
      setAuth({
        authenticated: false,
        username: null,
        env_locked: false,
        checked_at: new Date().toISOString(),
      });
      window.dispatchEvent(new CustomEvent(AUTH_CHANGED_EVENT));
    } catch (e) {
      setError(humanReadable(e));
    } finally {
      setMode("idle");
    }
  };

  // unmount で token を必ず捨てる
  useEffect(() => () => setToken(""), []);

  // render: 未認証 / 認証済 / env-locked の3状態。
  // env-locked では Save / Logout 両方 disabled + 説明文を表示。
}
```

**サイドバー連動** (`frontend/src/components/SidebarStatus.tsx` の `useEffect` 内に追加):

```tsx
useEffect(() => {
  let alive = true;
  const refresh = () =>
    fetchAuthStatus()
      .then((s) => alive && setAuth(s))
      .catch(() => alive && setAuth(null));
  refresh();
  const onChange = () => refresh();
  window.addEventListener("hf-auth-changed", onChange);
  return () => {
    alive = false;
    window.removeEventListener("hf-auth-changed", onChange);
  };
}, []);
```

`hf-auth-changed` event は文字列リテラルを共通化するためだけの定数。新しい store 層は導入しない。

### Frontend: `frontend/src/api/cloud.ts` への追加

```ts
export interface AuthStatus {
  authenticated: boolean;
  username: string | null;
  checked_at: string;
  env_locked: boolean;  // 追加
}

export const postLogin = (token: string) =>
  apiFetch<AuthStatus>("/api/cloud/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });

export const postLogout = () =>
  apiFetch<void>("/api/cloud/logout", { method: "POST" });
```

### Frontend: Settings ページへの組み込み

`frontend/src/pages/SettingsPage.tsx` の JSX を修正:

```tsx
<HardwareStatusBlock ... />
<HuggingFaceCard />        {/* ← 追加 */}
<ConfigurationsTabs ... />
```

### 既存 push エンドポイントのメッセージ更新

`backend/mimicrec/api/routes/cloud.py:129`

```python
# before
raise HTTPException(status_code=401, detail="not authenticated; run `huggingface-cli login`")
# after
raise HTTPException(status_code=401, detail="not authenticated; sign in from Settings → Hugging Face")
```

frontend 側で 401 を catch して詳細メッセージを `last_push_error` に既に出している箇所はそのまま動く（文字列のみ変更）。

## Data flow

### Login

```
1. user pastes "hf_xxx" → click Save
2. frontend: trim, empty チェック → POST /api/cloud/login { token } (with Origin header)
3. backend:
   a. _require_same_origin → Origin 不一致なら 403
   b. _env_token_present → True なら 409 "HF_TOKEN env var is set; unset it..."
   c. trim、空なら 400
   d. HfApi().whoami(token=token) を呼ぶ
        - 401/403 → 401 "invalid token"
        - その他失敗 → 503 "could not reach Hugging Face"
        - 200 だが name 欠落 → 502 "unexpected response from Hugging Face"
        - 成功 → username 取得
   e. try: huggingface_hub.login(token, add_to_git_credential=False)
            ↓ 例外 → 500 "failed to persist auth token"
      finally: app.state.auth_cache = None  (古い値を残さない)
   f. app.state.auth_cache = { t: monotonic, value: AuthStatus(...env_locked=False) }
   g. AuthStatus を return
4. frontend: setAuth(next)、token state クリア、window.dispatchEvent("hf-auth-changed")
5. SidebarStatus: イベントで refetch → hub: @username 更新
```

### Logout

```
1. user clicks Logout
2. frontend: POST /api/cloud/logout (with Origin header)
3. backend:
   a. _require_same_origin → Origin 不一致なら 403
   b. _env_token_present() なら 409 を返す
   c. try: huggingface_hub.logout()  ← cache file 削除
            ↓ 例外 → 500 "failed to clear stored auth token"
      finally: app.state.auth_cache = None
   d. 204
4. frontend: setAuth({ authenticated: false, env_locked: false, ... })、event dispatch
```

### auth-status (既存) の拡張

```
GET /api/cloud/auth-status
レスポンス追加フィールド: env_locked: bool
  - HF_TOKEN or HUGGING_FACE_HUB_TOKEN が set かつ非空なら true
```

UI はこのフィールドで Logout ボタンの活性/非活性を決める。

## API endpoints

### POST `/api/cloud/login`

Request:
```json
{ "token": "hf_xxxxxxxxxxxxx" }
```

Headers: `Origin: <same-origin>` 必須。

- Origin header 欠落 → 403 `{ "detail": "origin header required" }`
- Origin 不一致 → 403 `{ "detail": "cross-origin request rejected" }`
- env var 経由認証中 → 409 `{ "detail": "HF_TOKEN env var is set; unset it before signing in from the UI" }`
- token 空/空白 → 400 `{ "detail": "token is required" }`
- whoami が 401/403 → 401 `{ "detail": "invalid token" }`
- whoami 200 だが name 欠落 → 502 `{ "detail": "unexpected response from Hugging Face" }`
- whoami 接続失敗 → 503 `{ "detail": "could not reach Hugging Face" }`
- `hf_login()` 失敗（ディスク等） → 500 `{ "detail": "failed to persist auth token" }`
- 成功 → 200 `AuthStatus`（`env_locked: false` 固定）

### POST `/api/cloud/logout`

Headers: `Origin: <same-origin>` 必須。

- Origin header 欠落 → 403 `{ "detail": "origin header required" }`
- Origin 不一致 → 403 `{ "detail": "cross-origin request rejected" }`
- env var 経由認証中 → 409 `{ "detail": "token is provided via HF_TOKEN env var; unset it to log out" }`
- `hf_logout()` 失敗 → 500 `{ "detail": "failed to clear stored auth token" }`
- 成功 → 204 No Content

### GET `/api/cloud/auth-status` (既存・拡張)

Response:
```json
{
  "authenticated": true,
  "username": "TakakiMaeda",
  "checked_at": "2026-05-16T...",
  "env_locked": false
}
```

## Security considerations

| リスク | 対策 |
|---|---|
| Token が HTTP ログに残る | クエリ文字列禁止 / body のみ。FastAPI のデフォルトログは URL のみ |
| Token がアプリログに残る | login route で `logger.*` / `print` で token を出力する箇所を作らない。レビューチェックリストに「token 文字列のフォーマット引数を grep」を入れる |
| Token が例外メッセージで漏れる | `HfHubHTTPError` の `str(e)` をそのまま返さず、固定の安全な文字列だけ返す ("invalid token" / "could not reach Hugging Face" 等) |
| Token が React state に長居 | Save 成功時 / コンポーネント unmount で `setToken("")`。失敗時はリトライ性のため component-local memory に保持するが、永続化なし・DOM は masking 維持。トレードオフを spec で明示 |
| Token が DevTools / 履歴に残る | input は `type="password"`、`autoComplete="off"`、フォームの `action` 不在 |
| 平文でディスクに残る | HF CLI 自身が `~/.cache/huggingface/token` を平文保存。本機能で挙動を変えない（既存と整合） |
| CSRF（localhost で稼働中の API への外部ページからの POST） | `/cloud/login` と `/cloud/logout` で `Origin` header の same-origin チェック。不一致は 403。Simple request 化を避けるため、必ず `Content-Type: application/json` で POST する（frontend は `apiFetch` 既定）|
| `HfHubHTTPError` のレスポンスボディ漏洩 | 直接 `detail` に含めない。`e.response.status_code` のみ参照 |

## Test plan

### Unit / API

`tests/api/test_cloud_auth.py` 新規:

**Login 正常系**
- `test_login_success`: `HfApi.whoami` を mock して `{"name": "alice"}` を返す → 200、AuthStatus.username == "alice"、`env_locked: false`、`huggingface_hub.login` が `add_to_git_credential=False` で呼ばれた
- `test_login_invalidates_cache_before_response`: 事前に `auth_cache` を set → login 後に新しい AuthStatus で上書きされている

**Login バリデーション**
- `test_login_empty_token`: body `{"token": ""}` → 400
- `test_login_whitespace_token`: body `{"token": "   "}` → 400
- `test_login_missing_origin`: Origin header なし → 403
- `test_login_cross_origin`: Origin が同一でない → 403

**Login 異常系**
- `test_login_invalid_token`: `HfApi.whoami` が `HfHubHTTPError` (status 401) を raise → 401 "invalid token"、`hf_login` が呼ばれない、`auth_cache` 触られない
- `test_login_whoami_403`: 403 raise → 401 "invalid token"（権限不足も "invalid token" に丸める）
- `test_login_network_error`: `HfApi.whoami` が `ConnectionError` raise → 503
- `test_login_whoami_no_name`: `whoami` が `{"orgs": []}` (name 欠落) → 502
- `test_login_hf_login_write_fails`: `hf_login` が `OSError("disk full")` raise → 500 "failed to persist auth token"、token は detail/log に **含まれない**こと、`auth_cache` が None で残らない (try/finally)

**Login 環境変数干渉**
- `test_login_env_locked`: `monkeypatch.setenv("HF_TOKEN", "x")` → 409、`whoami` も `hf_login` も呼ばれない
- `test_login_env_locked_legacy_var`: `HUGGING_FACE_HUB_TOKEN` set → 409

**Logout**
- `test_logout_success`: monkeypatch `hf_logout` → 204、mock が呼ばれた、`auth_cache` が None
- `test_logout_idempotent`: cache 無い状態でも 204（`hf_logout` が冪等な範囲で）
- `test_logout_env_locked`: `monkeypatch.setenv("HF_TOKEN", "x")` → 409、`hf_logout` が呼ばれない
- `test_logout_hf_logout_fails`: `hf_logout` が `PermissionError` raise → 500（握り潰さない）、`auth_cache` は finally で invalidate されている
- `test_logout_missing_origin`: Origin header なし → 403
- `test_logout_cross_origin`: 不一致 → 403

**auth-status (拡張)**
- `test_auth_status_env_locked_field`: `HF_TOKEN` set 状態で GET → `env_locked: true`
- `test_auth_status_no_env_locked`: env 無し + token cache 無し → `env_locked: false, authenticated: false`

**セキュリティ静的チェック**
- `test_no_token_in_logs` (grep test): repo 全体で `f"...{token}"` パターン / `logger.*(token)` がないこと（pytest が backend 配下を grep）

### Frontend integration (任意、Playwright が無ければ手動)

- 未認証 → トークン入力 → Save → スピナー → `@username` 表示まで遷移
- サイドバー `hub:` が同時に `@username` に更新される（CustomEvent）
- 無効トークンで Save → エラー赤帯、入力欄に値は残る（リトライ可能）、`token` state は backend には再送されない限り保持
- env_locked モード: 入力欄/ボタン disabled、説明文表示
- Logout → サイドバー含めて 全部 `—` / "not logged in" に戻る

### Live (opt-in)

- 実 HF token で login → push → logout を end-to-end で1周（CI では skip、`HF_TOKEN_TEST` env 有時のみ）

### Manual / smoke

- 実トークン（個人）で UI から Save → サイドバー `hub:` が `@<self>` に切り替わる
- そのまま既存 `POST /datasets/{ds}/hub/push` を叩いて push が成功する（既存挙動が壊れていない確認）
- Logout → サイドバー `hub:` が `—` に戻る
- 無効トークン（`hf_invalid_dummy`）で Save → 入力欄下に "invalid token"

## Migration / backwards compatibility

- 既存ユーザーが `huggingface-cli login` 済みなら：起動直後の `auth-status` で username を表示、Logout ボタンが押せる状態。`HF_TOKEN` env を使っている場合は env_locked 表示。
- 既存の `POST /datasets/{ds}/hub/push` の 401 メッセージ文字列が変わるが、frontend 側で文言を hardcode していないため影響なし（`last_push_error` にそのまま流すだけ）。
- 既存 `auth-status` レスポンスに `env_locked` フィールド追加：frontend で必須にしても OK（同 PR でフロント両方更新するため）。

## Open questions / future work

- **OAuth Device Flow** — トークン直接コピペを避けたいユーザー向け（v2）
- **サイドバー `hub:` 行のクリック → Settings 遷移** — 後続 PR で discoverability 向上
- **Per-dataset 別アカウント push** — 個人 vs 組織 repo の切替（v2）
- **暗号化保存** — OS keyring 連携（v2）

## Risks

| リスク | 対策 |
|---|---|
| `huggingface_hub.login()` の挙動が将来変わる | バージョンを `>=0.34, <1.0` に pin、CI でバージョン上限テスト |
| `whoami` レスポンス形式が変わる | `huggingface_hub 0.35.x` 時点で `Dict` 返却を前提。dict 以外なら `username = None` で扱い、結果 502 "unexpected response" に落とす |
| Token がブラウザの自動補完で別フォームに漏れる | `autoComplete="off"` + `type="password"` |
| ローカル攻撃者の盗み見 | HF CLI 自身が同じ場所に平文保存している前提なので、本機能で悪化しない |
| **env-locked のユーザーがハマる** | UI で常時バナー表示 + Login/Logout disabled + 「`HF_TOKEN` を unset してから操作してください」を明示 |
| **`hf_login()` 中の race（途中失敗）で `auth_cache` が古いまま** | `try/finally` で必ず `_invalidate_auth_cache()` を実行 |
| **同マシン上の悪意あるローカルプロセスからの POST** | Origin チェックで cross-origin を 403。同一プロセス内 same-origin を装われたら防げないが、その時点で token 読み取りも自由なので本機能のスコープ外 |
| Codex 指摘の "token in React state on failure"（再試行のため残る） | spec で "in-memory only、unmount でクリア" を明文化。完全 0 はリトライ UX を著しく損ねるためトレードオフを取る |
