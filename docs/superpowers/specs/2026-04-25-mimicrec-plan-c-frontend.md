# MimicRec Plan C — React Frontend

## 1. Purpose

Build the web UI for MimicRec: 4 pages (Datasets, Record, Episodes, Replay) that consume the Plan B FastAPI REST + WebSocket API.

## 2. Scope

**In scope:**
- Vite + React + TypeScript project scaffold
- TailwindCSS + shadcn/ui for styling
- 4 pages with sidebar navigation
- REST client (TanStack Query) + WebSocket clients
- Session state management
- Camera preview display
- Keyboard shortcuts for Record page
- Episode table with filtering

**Out of scope:**
- Time-series plots (deferred — placeholder only)
- Playwright E2E tests (deferred to after manual validation)
- Real hardware testing

## 3. Pages

### 3.1 Datasets
- List all datasets from `GET /api/datasets`
- Create new dataset (name, fps, joint_names, camera_names)
- Download button per row → `GET /api/datasets/{ds}/archive` (browser download)
- Click row → navigate to Episodes page for that dataset

### 3.2 Record (core page)
Four sub-states matching session machine:

**Pre-session (IDLE):** Config selection form — robot, teleop, mapper, cameras, dataset, task, fps. Dropdowns populated from `GET /api/configs/*`. "Start Session" button.

**READY:** Camera previews via `/ws/cameras/{cam}`. "Start Recording" button (or Space). Show robot joint state from `/ws/state`. "Replaying..." badge when `sub_state == "replaying"`.

**RECORDING:** Camera previews continue. Episode progress bar (num_frames, duration from `/ws/session` `episode_progress`). "Stop Recording" button (or Space).

**REVIEW:** "Save" (S), "Discard" (D), success label (1/2/3 for success/failure/skip). No camera preview during review.

Keyboard shortcuts: `Space` toggle recording, `S` save, `D` discard, `1` success, `2` failure, `3` skip.

### 3.3 Episodes
- Table of episodes from `GET /api/datasets/{ds}/episodes`
- Columns: index, task, duration, frames, success, mode, recorded_at
- Delete button per row (tombstone)
- Click row → navigate to Replay page

### 3.4 Replay
- Episode metadata panel
- Camera video playback from `GET /api/datasets/{ds}/episodes/{idx}/video/{cam}`
- "Replay on Robot" button → `POST /api/replay/start`
- "Stop" button → `POST /api/replay/stop`
- Replay progress from `/ws/session` `replay_progress`

## 4. Architecture

```
frontend/
  src/
    main.tsx                  # Entry point
    App.tsx                   # Router + layout (sidebar + content)
    api/
      client.ts              # Axios/fetch base config
      queries.ts              # TanStack Query hooks (useDatasets, useEpisodes, etc.)
      ws.ts                   # WebSocket connection managers
    state/
      session-store.ts        # Zustand store for session state (from /ws/session)
    pages/
      DatasetsPage.tsx
      RecordPage.tsx
      EpisodesPage.tsx
      ReplayPage.tsx
    components/
      Layout.tsx              # Sidebar + header shell
      CameraPreview.tsx       # Single camera JPEG stream display
      SessionConfigForm.tsx   # Pre-session config selection
      EpisodeTable.tsx        # Filterable episode list
      RecordingControls.tsx   # Start/stop/save/discard buttons + keyboard
      ReplayControls.tsx      # Replay on robot + stop
      SessionStatus.tsx       # Current state badge
```

## 5. State management

**Zustand store** for session state, updated from `/ws/session`:
```typescript
interface SessionStore {
  state: "idle" | "ready" | "recording" | "review";
  subState: string | null;
  mode: string | null;
  dataset: string | null;
  // ... other fields from SessionStatePayload
  episodeProgress: EpisodeProgress | null;
  replayProgress: ReplayProgress | null;
  lastError: { error: string; message: string } | null;
}
```

**TanStack Query** for REST data (datasets, episodes, configs) — cache + auto-refetch.

**WebSocket connections** managed per-page:
- `/ws/session` — always connected when session active
- `/ws/state` — connected on Record page
- `/ws/cameras/{cam}` — connected on Record page per camera

## 6. API client

Base URL from `VITE_API_URL` env var, defaulting to `http://localhost:8000`.

## 7. Tech stack

- React 19 + TypeScript
- Vite 6
- TailwindCSS 4 + shadcn/ui
- TanStack Query v5
- Zustand (state)
- pnpm

## 8. Exit criteria

1. `pnpm dev` starts without errors
2. Datasets page lists datasets and creates new ones
3. Record page shows config form, starts session, shows camera previews
4. Record page records an episode (start/stop/save with keyboard shortcuts)
5. Episodes page shows episode table with delete
6. Replay page shows episode metadata and triggers replay
7. Navigation between all 4 pages works
8. Session state badge updates in real-time from WebSocket
