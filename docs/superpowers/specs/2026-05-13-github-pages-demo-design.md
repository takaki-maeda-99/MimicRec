# GitHub Pages Browser-Only Demo — Design

**Date**: 2026-05-13
**Status**: Draft

## Goal

Publish a browser-only "try it" version of MimicRec on GitHub Pages so a
technical visitor (hiring candidate, collaborator) can click through the
**Record → Episodes → Replay** flow without installing anything or owning a
robot.

## Non-goals

- Settings, Inference, Cloud, Hub, Export: stubbed with 503; demo banner only.
- Multiple cameras or multiple episodes bundled (one of each).
- Persistence across reloads. Demo state lives in memory; reload resets it.
- Mobile layout. Existing desktop layout is what's shipped.
- Replacing the existing local-first product. The demo is a separate build
  artifact; the standard `pnpm dev` / production build is unchanged.

## Audience and success criteria

Audience: an engineer evaluating MimicRec who landed on the GitHub repo.

Success: in under 2 minutes a visitor can
1. Open the Pages URL,
2. Hit "Start session" → "Start episode" → watch live camera + joint
   telemetry → "Stop" → "Save",
3. See the saved episode appear in the Episodes list,
4. Open Replay and watch it play back,

without seeing broken pages, console errors, or `fetch failed` toasts on
the core flow. Stubbed pages (Settings/Inference) show a clear "not
available in demo" message rather than blowing up.

## Approach

Use **MSW (Mock Service Worker) v2** to intercept both `fetch()` and
WebSocket traffic in the browser. The frontend code (`apiFetch`,
`WsConnection`, page components) is **unmodified**. A dynamic `import()` in
`main.tsx`, gated on `import.meta.env.VITE_DEMO`, registers handlers
before React mounts.

Why MSW over rolling our own client swap:

- Handlers are declarative and read alongside the real API surface.
- Service Worker layer keeps mock code completely out of production
  bundles via tree-shaking and dynamic import.
- WebSocket interception (`ws.link()`) is first-class as of MSW v2, which
  matters for `/ws/session`, `/ws/state`, and `/ws/cameras/:name`.

Alternatives considered:

- **Build-time API client swap.** Replace `api/client.ts` and `api/ws.ts`
  with demo implementations under a Vite flag. Rejected: parallel
  implementations drift, and we lose the "real code path runs unmodified"
  guarantee.
- **Static JSON fixtures only.** No `setInterval` telemetry, no live
  recording feel. Rejected: doesn't satisfy success criterion 2.

## Architecture

```
GitHub Pages  (https://takaki-maeda-99.github.io/MimicRec/)
  └── /MimicRec/
        ├── index.html
        ├── assets/*.js          React bundle (built with VITE_DEMO=true)
        ├── mockServiceWorker.js MSW-generated Service Worker
        └── demo/
              ├── episode_0/
              │   ├── meta.json      joints timeline + episode metadata
              │   └── cam_front.mp4  recorded camera footage
              └── seed.json          initial datasets/episodes/configs lists

Browser
  main.tsx
    └─ if (VITE_DEMO) await import('./demo/setup').then(s => s.start())
         └─ MSW worker.start({ scope: '/MimicRec/', onUnhandledRequest: 'bypass' })
            ├─ REST handlers   (rest-handlers.ts) → demoStore
            └─ WS handlers     (ws-handlers.ts)
                                 ├─ /ws/session    session/episode/replay progress
                                 ├─ /ws/state      joint timeline @ 30 Hz
                                 ├─ /ws/cameras/:n MP4 → JPEG blob @ 30 Hz
                                 ├─ /ws/teleop     accept & drop
                                 └─ /ws/inference  close(1008)
  Then React mounts as usual; all api/* and ws/* code paths are unmodified.
```

## Components

### `frontend/src/demo/store.ts`

Module-scope in-memory store:

```ts
export const demoStore = {
  datasets: [{ name: "demo_dataset", num_episodes: 1, total_frames: 240 }],
  episodes: [seedEpisode],         // EpisodeSummary[]
  session: { state: "idle", ... }, // SessionStatePayload
  recordingStartedAt: null as number | null,
  replayIndex: null as number | null,
};

export const events = new EventTarget(); // 'recording-start' | 'recording-stop' | 'replay-start' | 'replay-stop' | 'session-changed'
```

Mutations go through helper functions that also dispatch on `events`, so
WS handlers can react without polling.

### `frontend/src/demo/rest-handlers.ts`

MSW `http.*` handlers for the endpoints required by the core flow:

| Endpoint | Behavior |
|---|---|
| `GET /api/datasets` | `demoStore.datasets` |
| `POST /api/datasets` | 503 `{ detail: "Not available in demo" }` |
| `DELETE /api/datasets/:ds` | 503 |
| `GET /api/datasets/:ds/tasks` | `[{ task_index: 0, task: "demo_task", instruction: "Pick the cube" }]` |
| `GET /api/datasets/:ds/episodes` | `demoStore.episodes` (honors `include_deleted`) |
| `DELETE /api/datasets/:ds/episodes/:idx` | Toggle tombstone on matching episode |
| `GET /api/configs/:group` | Names list (static, see seed.json) |
| `GET /api/configs/camera_roles` | `{ roles: ["front", "wrist"] }` |
| `GET /api/settings/configs/:group` | Same as above with full ConfigEntry |
| `GET /api/session/state` | `demoStore.session` |
| `POST /api/session/start` | `state="ready"`, dispatch `session-changed` |
| `POST /api/session/end` | `state="idle"`, dispatch `session-changed` |
| `POST /api/episode/start` | `state="recording"`, `recordingStartedAt=Date.now()`, dispatch `recording-start` |
| `POST /api/episode/stop` | `state="review"`, dispatch `recording-stop` |
| `POST /api/episode/save` | Push fake episode (copy of seed with new index + timestamp), `state="ready"` |
| `POST /api/episode/discard` | `state="ready"` |
| `POST /api/replay/start` | `state="recording"` (subState replay), `replayIndex=0`, dispatch `replay-start` |
| `POST /api/replay/stop` | `state="ready"`, dispatch `replay-stop` |
| `POST /api/robot/estop` | `{ ok: true }`, set internal flag |
| `POST /api/robot/clear_estop` | `{ ok: true }` |
| `* /api/cloud/*`, `* /api/datasets/:ds/hub*`, `POST /api/datasets/:ds/export` | 503 |
| `GET /api/session/gopro_pending` | `[]` |
| `* /api/settings/devices/*` | 503 |

Anything not listed: `onUnhandledRequest: 'bypass'` lets real requests
(to static `demo/*` files) go through to the network.

### `frontend/src/demo/ws-handlers.ts`

MSW `ws.link()` handler. One link object, three `.addEventListener('connection')`
branches keyed on URL path:

**`/ws/session`** — On `recording-start`, every 33ms emit
`{ type: 'episode_progress', data: { num_frames: elapsed*30, ... } }`. On
`replay-start`, emit `{ type: 'replay_progress', data: { frame_index, total_frames: 240, speed: 1.0 } }`
until `replayIndex` hits 240 → auto-stop. Also re-emits
`{ type: 'session_state', data: demoStore.session }` whenever `session-changed`
fires.

**`/ws/state`** — Always-on. From the moment the WS connects, cycles
through `meta.json.joints` (array of joint-state snapshots) at 30 Hz,
looping. Used by EEMonitor regardless of session phase.

**`/ws/cameras/:name`** — Always-on (the camera preview is visible even
when idle). Uses a singleton `CameraPlayer` (see below) that decodes one
MP4 to JPEG blobs. Each connected client gets the same blob stream. The
`:name` parameter is ignored — only one camera is bundled.

**`/ws/teleop`** — Accept connection, ignore all incoming messages.

**`/ws/inference`** — `client.close(1008)` immediately.

### `frontend/src/demo/camera-player.ts`

Singleton that loads `demo/episode_0/cam_front.mp4` into a hidden
`<video>` element, plays in a loop, and:

```ts
const video = document.createElement('video');
video.src = `${BASE_URL}demo/episode_0/cam_front.mp4`;
video.muted = true; video.loop = true; video.playsInline = true;
video.style.display = 'none';
document.body.appendChild(video);
await video.play();

const canvas = new OffscreenCanvas(224, 224);
const ctx = canvas.getContext('2d')!;

const subscribers = new Set<(b: Blob) => void>();
const tick = () => {
  ctx.drawImage(video, 0, 0, 224, 224);
  canvas.convertToBlob({ type: 'image/jpeg', quality: 0.85 })
    .then(b => subscribers.forEach(fn => fn(b)));
  video.requestVideoFrameCallback(tick);
};
video.requestVideoFrameCallback(tick);
```

WS handler subscribes / unsubscribes on client connect / close.

### `frontend/src/demo/setup.ts`

```ts
import { setupWorker } from 'msw/browser';
import { restHandlers } from './rest-handlers';
import { wsHandler } from './ws-handlers';

export async function start() {
  const worker = setupWorker(...restHandlers, wsHandler);
  await worker.start({
    serviceWorker: { url: `${import.meta.env.BASE_URL}mockServiceWorker.js` },
    onUnhandledRequest: 'bypass',
  });
}
```

### `frontend/src/main.tsx` — minimal edit

```ts
if (import.meta.env.VITE_DEMO) {
  const { start } = await import('./demo/setup');
  await start();
}
createRoot(document.getElementById('root')!).render(<App />);
```

The dynamic `import()` keeps demo code out of production bundles.

### Demo banner

Add to `frontend/src/components/Layout.tsx` directly above the nav:

```tsx
{import.meta.env.VITE_DEMO && (
  <div className="bg-amber-500 text-black text-center text-sm py-1">
    Demo mode — recordings reset on reload.
    {' '}<a href="https://github.com/takaki-maeda-99/MimicRec" className="underline">View source</a>
  </div>
)}
```

## Fixture data

Captured from a real session on hardware (any robot, any task):

**`public/demo/episode_0/meta.json`**:
```json
{
  "episode_index": 0,
  "task": "Pick the red cube",
  "duration_sec": 8.0,
  "num_frames": 240,
  "fps": 30,
  "cameras": ["front"],
  "robot": "so101",
  "joints": [
    { "t": 0.0, "positions": [0.1, -0.3, 0.5, ...], "gripper": 0.0 },
    ...
  ]
}
```

`joints` is a precomputed time series; the WS handler indexes into it by
`elapsed * fps`.

**`public/demo/episode_0/cam_front.mp4`**: 224×224, H.264, 30 fps, ~8 s,
target ≤1.5 MB. Encoded with `ffmpeg -i raw.mp4 -vf scale=224:224 -c:v
libx264 -crf 28 -preset slow cam_front.mp4`.

**`public/demo/seed.json`**: initial Episodes list (one entry pointing at
`episode_0`) plus config-group name lists (`robot`, `teleop`, `cameras`,
`tasks`, `mappers`). Hand-maintained — the file is small and lets us
control exactly which configs surface in the demo without coupling the
demo build to backend `configs/` layout.

## Build, deploy, file layout

### New files

```
frontend/src/demo/{setup,rest-handlers,ws-handlers,store,camera-player,seed}.ts
frontend/public/demo/episode_0/{meta.json,cam_front.mp4}
frontend/public/demo/seed.json
frontend/public/mockServiceWorker.js   (generated by `npx msw init`)
.github/workflows/pages.yml
```

### Modified files

| File | Change | Lines |
|---|---|---|
| `frontend/vite.config.ts` | `base: process.env.VITE_DEMO ? '/MimicRec/' : '/'` | +1 |
| `frontend/src/main.tsx` | Demo bootstrap (dynamic import + await) | +5 |
| `frontend/src/components/Layout.tsx` | Demo banner above existing nav | +6 |
| `frontend/package.json` | Add `msw` devDep, `"build:demo": "VITE_DEMO=true tsc && VITE_DEMO=true vite build"` script | +2 |
| `README.md` / `README.ja.md` | Live demo link section | +5 |

Everything in `api/`, `pages/`, `state/`, `components/` (other than the
layout banner edit) is **unchanged**.

### GitHub Action

`.github/workflows/pages.yml`:

```yaml
name: Deploy demo to GitHub Pages
on:
  push: { branches: [main] }
  workflow_dispatch: {}
concurrency:
  group: pages
  cancel-in-progress: true
jobs:
  build-deploy:
    runs-on: ubuntu-latest
    permissions: { pages: write, id-token: write, contents: read }
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with: { version: 9 }
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: pnpm
          cache-dependency-path: frontend/pnpm-lock.yaml
      - run: pnpm install --frozen-lockfile
        working-directory: frontend
      - run: pnpm build:demo
        working-directory: frontend
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with: { path: frontend/dist }
      - id: deployment
        uses: actions/deploy-pages@v4
```

One-time manual step: in GitHub repo Settings → Pages → Source: "GitHub
Actions".

## Edge cases and gotchas

- **Service Worker scope under `/MimicRec/`**: must pass
  `serviceWorker.url` with `BASE_URL` prefix. `onUnhandledRequest: 'bypass'`
  is required so MSW doesn't intercept fetches for the bundled MP4 or
  static assets.
- **First-load worker registration**: MSW registers the worker on first
  visit. There's a one-time race where the React app could fire requests
  before the worker is active. Guard by `await worker.start()` before
  `createRoot`.
- **Hard refresh during recording**: a known limitation; the demo banner
  warns. State resets cleanly because everything is in-memory.
- **MP4 autoplay policy**: muted + playsInline lets autoplay work on all
  desktop browsers. No user gesture required.
- **OffscreenCanvas browser support**: ubiquitous on desktop Chrome /
  Firefox / Safari 17+. If we want to support older Safari, fall back to a
  hidden on-screen `<canvas>` (trivial branch).
- **Existing 503 handling**: page components that hit stubbed endpoints
  (Settings, Export, Inference) need to degrade gracefully. Spot-check
  during implementation; if a page throws, add a minimal error-state
  rendering. Behavior in production is unchanged because those calls
  succeed there.
- **MSW v2 WebSocket API stability**: shipped GA in 2024. Pin to ≥2.4 in
  `package.json` to avoid the early-beta APIs.

## Testing

- `pnpm build` (production, no `VITE_DEMO`) succeeds and bundle does
  **not** contain `msw`, `demo/`, or `mockServiceWorker` references.
  Verify with `grep -r msw frontend/dist || echo CLEAN`.
- `pnpm build:demo` succeeds; `pnpm preview` serves the result; manual
  walkthrough of the three flows passes without console errors.
- Existing Python test suite is unaffected (no backend changes).
- No new unit tests for the demo layer. Hand-rolled mocks don't benefit
  from being tested with another set of mocks; manual smoke covers it.

## Out of scope (explicit)

- Settings, Inference, Cloud, Hub, Export functionality
- Multi-camera, multi-episode bundling
- localStorage persistence
- Mobile responsive layout
- Programmatic E2E tests for the demo
- Recording from the user's webcam (could be a future iteration)
