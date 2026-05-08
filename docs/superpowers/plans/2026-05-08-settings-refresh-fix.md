# Settings Page Refresh Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Settings ページの Refresh ボタンが USB hot-plug を反映するよう、ブラウザ HTTP キャッシュ起因のスキップを止め、Configs/Calibration セクションにも Refresh ボタンを追加する。

**Architecture:** 三段構え。(A) フロント側 `apiFetch` のデフォルト `cache` を `"no-store"` に変えてブラウザキャッシュを抑止、(B) バック側 `/api/settings/*` GET エンドポイントに `Cache-Control: no-store` ヘッダーを付与（防御）、(C) SettingsPage の UX を改善（loading state、エラー alert、Configs/Calibration の Refresh ボタン追加）。

**Tech Stack:** React 19 + TypeScript + Vite (frontend) / FastAPI + httpx + pytest-asyncio (backend)

**Spec reference:** `docs/superpowers/specs/2026-05-08-settings-refresh-fix-design.md`

---

## File Structure

| File | Purpose | Action |
|------|---------|--------|
| `backend/mimicrec/api/routes/settings.py` | 設定 API ルーター。GET エンドポイントに `Cache-Control: no-store` 付与 | Modify |
| `tests/api/test_settings_routes.py` | Settings API のテスト（`Cache-Control` 検証） | Create |
| `frontend/src/api/client.ts` | `apiFetch` のデフォルト `cache` を `"no-store"` に | Modify |
| `frontend/src/pages/SettingsPage.tsx` | loading state + alert + Configs/Calibration Refresh ボタン | Modify |

---

## Task 1: Backend — Cache-Control ヘッダー（serial / cameras）

**Files:**
- Modify: `backend/mimicrec/api/routes/settings.py`
- Create: `tests/api/test_settings_routes.py`

- [ ] **Step 1: Write failing tests for Cache-Control header on device endpoints**

`tests/api/test_settings_routes.py` を新規作成:

```python
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from mimicrec.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


def _client_app():
    app = create_app()
    app.state.configs_root = REPO_ROOT / "configs"
    return app


async def test_serial_devices_has_no_store_cache_control():
    app = _client_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/settings/devices/serial")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"


async def test_camera_devices_has_no_store_cache_control():
    app = _client_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/settings/devices/cameras")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_settings_routes.py -v`

Expected: 両テストとも FAIL（`cache-control` ヘッダーが None）

- [ ] **Step 3: Add Response param + header to serial/cameras endpoints**

`backend/mimicrec/api/routes/settings.py` の import 行に `Response` を追加:

```python
from fastapi import APIRouter, Request, Response
```

`list_serial_ports` を修正:

```python
@router.get("/settings/devices/serial")
async def list_serial_ports(response: Response):
    """List available serial ports."""
    response.headers["Cache-Control"] = "no-store"
    ports = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
    result = []
    for port in ports:
        try:
            import serial
            s = serial.Serial(port, timeout=0.1)
            s.close()
            result.append({"port": port, "available": True})
        except Exception:
            result.append({"port": port, "available": False})
    return result
```

`list_camera_devices` を修正:

```python
@router.get("/settings/devices/cameras")
async def list_camera_devices(response: Response):
    """List available camera devices."""
    response.headers["Cache-Control"] = "no-store"
    import cv2
    devices = sorted(glob.glob("/dev/video*"))
    result = []
    for dev in devices:
        dev_id = int(dev.replace("/dev/video", ""))
        cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
        opened = cap.isOpened()
        w, h = 0, 0
        if opened:
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
        result.append({"path": dev, "device_id": dev_id, "available": opened, "width": w, "height": h})
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/test_settings_routes.py -v`

Expected: 両テスト PASS

- [ ] **Step 5: Commit**

```bash
git add backend/mimicrec/api/routes/settings.py tests/api/test_settings_routes.py
git commit -m "$(cat <<'EOF'
feat(api): no-store Cache-Control on settings device endpoints

Prevent browser HTTP cache from short-circuiting Refresh in the Settings
page. /api/settings/devices/{serial,cameras} now returns Cache-Control:
no-store so the browser always hits the backend on Refresh.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Backend — Cache-Control ヘッダー（configs / calibration）

**Files:**
- Modify: `backend/mimicrec/api/routes/settings.py`
- Modify: `tests/api/test_settings_routes.py`

- [ ] **Step 1: Add failing tests for configs/calibration endpoints**

`tests/api/test_settings_routes.py` の末尾に追記:

```python
async def test_list_group_configs_has_no_store_cache_control():
    app = _client_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/settings/configs/cameras")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"


async def test_get_config_has_no_store_cache_control():
    app = _client_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/settings/configs/cameras/mock_cam")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"


async def test_list_calibrations_has_no_store_cache_control():
    app = _client_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/settings/calibration")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_settings_routes.py -v`

Expected: 3 テスト FAIL（`cache-control` ヘッダーが None）

- [ ] **Step 3: Add Response param + header to remaining GET endpoints**

`list_group_configs` を修正:

```python
@router.get("/settings/configs/{group}")
async def list_group_configs(request: Request, group: str, response: Response):
    """List all configs in a group with their contents."""
    response.headers["Cache-Control"] = "no-store"
    root = get_configs_root(request.app)
    group_dir = root / group
    if not group_dir.is_dir():
        raise FileNotFoundError(f"config group '{group}' not found")
    configs = []
    for f in sorted(group_dir.glob("*.yaml")):
        cfg = OmegaConf.load(f)
        configs.append({
            "name": f.stem,
            "file": str(f),
            "content": OmegaConf.to_container(cfg),
        })
    return configs
```

`get_config` を修正:

```python
@router.get("/settings/configs/{group}/{name}")
async def get_config(request: Request, group: str, name: str, response: Response):
    """Get a single config file's contents."""
    response.headers["Cache-Control"] = "no-store"
    root = get_configs_root(request.app)
    path = root / group / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"config '{group}/{name}' not found")
    cfg = OmegaConf.load(path)
    return {"name": name, "group": group, "content": OmegaConf.to_container(cfg)}
```

`list_calibrations` を修正:

```python
@router.get("/settings/calibration")
async def list_calibrations(response: Response):
    """List available calibration files."""
    response.headers["Cache-Control"] = "no-store"
    calib_root = Path.home() / ".cache/huggingface/lerobot/calibration"
    result = {"robots": {}, "teleoperators": {}}
    for category in ["robots", "teleoperators"]:
        cat_dir = calib_root / category
        if not cat_dir.exists():
            continue
        for robot_dir in sorted(cat_dir.iterdir()):
            if robot_dir.is_dir():
                files = [f.stem for f in robot_dir.glob("*.json")]
                result[category][robot_dir.name] = files
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/test_settings_routes.py -v`

Expected: 全 5 テスト PASS

- [ ] **Step 5: Run full backend test suite to check for regressions**

Run: `pytest tests/ -x -q`

Expected: 既存テスト全 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/mimicrec/api/routes/settings.py tests/api/test_settings_routes.py
git commit -m "$(cat <<'EOF'
feat(api): no-store Cache-Control on settings configs/calibration GETs

Extend the Cache-Control: no-store coverage to /settings/configs/* and
/settings/calibration so all Settings-page reads bypass browser cache
on Refresh.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Frontend — `apiFetch` のデフォルトキャッシュ無効化

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Modify apiFetch to default cache to no-store**

`frontend/src/api/client.ts` を以下に置換:

```ts
const BASE = ""; // relative — Vite proxy handles routing

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function apiFetch<T>(
  path: string,
  opts?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...opts?.headers },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    let detail: string;
    if (typeof body.detail === "string") {
      detail = body.detail;
    } else if (Array.isArray(body.detail)) {
      // FastAPI 422: detail is a list of {loc, msg, type} objects.
      detail = body.detail
        .map((e: { loc?: unknown[]; msg?: string }) =>
          e.msg ? `${(e.loc ?? []).join(".")}: ${e.msg}` : JSON.stringify(e))
        .join("; ");
    } else {
      detail = res.statusText;
    }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}
```

注意：`cache: "no-store"` は spread の前に置く。`opts` 側で `cache` を渡されたら上書きされる順序にしておく。

- [ ] **Step 2: Run frontend typecheck**

Run: `cd frontend && pnpm exec tsc --noEmit`

Expected: エラー無し

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "$(cat <<'EOF'
fix(frontend): default apiFetch to cache: 'no-store'

Browser was serving cached GET responses via heuristic freshness, so
clicking Refresh in /settings never reached the backend. All apiFetch
calls now bypass the HTTP cache by default; callers can still opt in
by passing { cache: 'default' } if needed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Frontend — Devices Refresh の loading state + エラー alert

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Add loading state and error alert for loadDevices**

`frontend/src/pages/SettingsPage.tsx` の冒頭付近、state 宣言の直下を修正。

現在 (line 27-32 付近):

```tsx
const [serialPorts, setSerialPorts] = useState<SerialDevice[]>([]);
const [cameras, setCameras] = useState<CameraDevice[]>([]);
const [configs, setConfigs] = useState<Record<string, ConfigEntry[]>>({});
const [editingConfig, setEditingConfig] = useState<ConfigEntry | null>(null);
const [editJson, setEditJson] = useState("");
const [calibrations, setCalibrations] = useState<Record<string, Record<string, string[]>>>({});
```

を以下に変更:

```tsx
const [serialPorts, setSerialPorts] = useState<SerialDevice[]>([]);
const [cameras, setCameras] = useState<CameraDevice[]>([]);
const [configs, setConfigs] = useState<Record<string, ConfigEntry[]>>({});
const [editingConfig, setEditingConfig] = useState<ConfigEntry | null>(null);
const [editJson, setEditJson] = useState("");
const [calibrations, setCalibrations] = useState<Record<string, Record<string, string[]>>>({});
const [refreshingDevices, setRefreshingDevices] = useState(false);
const [refreshingConfigs, setRefreshingConfigs] = useState(false);
const [refreshingCalibrations, setRefreshingCalibrations] = useState(false);
```

`loadDevices` 関数 (line 34-37 付近) を以下に置換:

```tsx
const loadDevices = async () => {
  setRefreshingDevices(true);
  try {
    const [serial, cams] = await Promise.all([
      apiFetch<SerialDevice[]>("/api/settings/devices/serial"),
      apiFetch<CameraDevice[]>("/api/settings/devices/cameras"),
    ]);
    setSerialPorts(serial);
    setCameras(cams);
  } catch (e) {
    alert(`Failed to refresh devices: ${e}`);
  } finally {
    setRefreshingDevices(false);
  }
};
```

- [ ] **Step 2: Wire loading state into the Devices Refresh button**

現在 (line 82-84 付近):

```tsx
<Button variant="outline" size="sm" onClick={loadDevices}>
  Refresh
</Button>
```

を以下に変更:

```tsx
<Button variant="outline" size="sm" onClick={loadDevices} disabled={refreshingDevices}>
  {refreshingDevices ? "Refreshing..." : "Refresh"}
</Button>
```

- [ ] **Step 3: Run typecheck**

Run: `cd frontend && pnpm exec tsc --noEmit`

Expected: エラー無し

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "$(cat <<'EOF'
fix(frontend): surface device-refresh errors and loading state

The previous loadDevices silently swallowed every error via
.catch(() => {}), so users had no signal whether Refresh fired or
failed. Replace with try/catch + alert and a disabled+labelled button
during the round-trip.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Frontend — Configs/Calibration を loading + alert に揃え、Refresh ボタン追加

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Replace loadConfigs with try/catch + loading state**

現在 (line 39-45 付近):

```tsx
const loadConfigs = () => {
  CONFIG_GROUPS.forEach((group) => {
    apiFetch<ConfigEntry[]>(`/api/settings/configs/${group}`)
      .then((data) => setConfigs((prev) => ({ ...prev, [group]: data })))
      .catch(() => {});
  });
};
```

を以下に置換:

```tsx
const loadConfigs = async () => {
  setRefreshingConfigs(true);
  try {
    const results = await Promise.all(
      CONFIG_GROUPS.map(async (group) => {
        const data = await apiFetch<ConfigEntry[]>(`/api/settings/configs/${group}`);
        return [group, data] as const;
      }),
    );
    setConfigs(Object.fromEntries(results));
  } catch (e) {
    alert(`Failed to refresh configs: ${e}`);
  } finally {
    setRefreshingConfigs(false);
  }
};
```

- [ ] **Step 2: Replace loadCalibrations with try/catch + loading state**

現在 (line 47-51 付近):

```tsx
const loadCalibrations = () => {
  apiFetch<Record<string, Record<string, string[]>>>("/api/settings/calibration")
    .then(setCalibrations)
    .catch(() => {});
};
```

を以下に置換:

```tsx
const loadCalibrations = async () => {
  setRefreshingCalibrations(true);
  try {
    const data = await apiFetch<Record<string, Record<string, string[]>>>(
      "/api/settings/calibration",
    );
    setCalibrations(data);
  } catch (e) {
    alert(`Failed to refresh calibrations: ${e}`);
  } finally {
    setRefreshingCalibrations(false);
  }
};
```

- [ ] **Step 3: Add Refresh button to Configurations section header**

現在 (line 126-127 付近):

```tsx
<section className="mb-8">
  <h3 className="text-lg font-semibold mb-3">Configurations</h3>
```

を以下に置換:

```tsx
<section className="mb-8">
  <div className="flex items-center justify-between mb-3">
    <h3 className="text-lg font-semibold">Configurations</h3>
    <Button variant="outline" size="sm" onClick={loadConfigs} disabled={refreshingConfigs}>
      {refreshingConfigs ? "Refreshing..." : "Refresh"}
    </Button>
  </div>
```

- [ ] **Step 4: Add Refresh button to Calibration section header**

現在 (line 186-187 付近):

```tsx
<section>
  <h3 className="text-lg font-semibold mb-3">Calibration</h3>
```

を以下に置換:

```tsx
<section>
  <div className="flex items-center justify-between mb-3">
    <h3 className="text-lg font-semibold">Calibration</h3>
    <Button variant="outline" size="sm" onClick={loadCalibrations} disabled={refreshingCalibrations}>
      {refreshingCalibrations ? "Refreshing..." : "Refresh"}
    </Button>
  </div>
```

- [ ] **Step 5: Run typecheck**

Run: `cd frontend && pnpm exec tsc --noEmit`

Expected: エラー無し

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): Refresh buttons for Configurations and Calibration

Mirror the Devices section: each Settings subsection now has its own
Refresh button with loading state and surface errors via alert. Removes
silent .catch(() => {}) fallbacks that masked failures.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 手動検証

**Files:** N/A (verification only)

- [ ] **Step 1: Start backend**

Run (in one terminal): `uvicorn mimicrec.api.app:app --reload`

- [ ] **Step 2: Start frontend dev server**

Run (in another terminal): `cd frontend && pnpm dev`

- [ ] **Step 3: Open http://localhost:5173/settings in a browser with DevTools open**

Network タブを開いておく。

- [ ] **Step 4: Verify USB hot-plug refreshes**

操作:
1. ブラウザで /settings を開いて Devices セクションを観察
2. USB シリアル / USB カメラを抜く
3. Devices セクションの Refresh ボタンを押す
4. 抜いたデバイスがリストから消える、もしくは `available: false` に変わることを確認
5. 再度差し込んで Refresh
6. リストに復帰して `available: true` になることを確認

Expected: Refresh ボタンを押すたびに DevTools の Network タブで `/api/settings/devices/serial` と `/api/settings/devices/cameras` の新規リクエストが発生（`(disk cache)` ではなく `200` ステータスのリクエスト）。

- [ ] **Step 5: Verify error path**

操作:
1. バックエンドを止める
2. Devices Refresh を押す
3. `Failed to refresh devices: ...` という alert が出ることを確認

- [ ] **Step 6: Verify Configs / Calibration Refresh も同じ挙動**

Configs / Calibration セクションの新規 Refresh ボタンも、ネットワーク呼び出しと loading 表示が機能していることを確認。

---

## Self-Review Checklist

- [x] **Spec coverage:**
  - Spec A (frontend cache: 'no-store') → Task 3
  - Spec A (loading state) → Task 4 (Devices), Task 5 (Configs/Calibration)
  - Spec A (エラー alert / .catch(() => {}) 撤去) → Task 4, Task 5
  - Spec B (backend Cache-Control: no-store) → Task 1, Task 2
  - Spec C (Configs/Calibration の Refresh ボタン) → Task 5
  - Spec verification plan (手動検証) → Task 6
  - Spec self-review 追加項目 (`Cache-Control` の pytest 検証) → Task 1, Task 2
- [x] **Placeholder scan:** No TBD, all code blocks complete, all paths absolute.
- [x] **Type consistency:** `refreshingDevices` / `refreshingConfigs` / `refreshingCalibrations` 同名で使い分け。`Response` のインポート / 注入も全 endpoint で統一。
