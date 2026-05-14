# Pages Layout Redesign — Inference / Episodes / Replay + Sidebar Identity

**Date**: 2026-05-14
**Branch**: feat/record-settings-layout
**Status**: Design

## Goals

1. Use horizontal space on wide displays (current pages are 1100–1240 px centered with empty side margins).
2. Make screen identity ("どの画面にいるか") more immediately recognizable.
3. After the annotation feature removal (committed as `216d524`), restructure the Replay page so the remaining elements — video + joint plot + EE plot — are spatially coordinated and playback is synchronized across them.
4. Preserve the existing HTTP API surface so external apps can keep driving Inference programmatically.

Non-goals: changing the visual language / typography / spacing tokens (use existing tokens as-is); adding new pages; reworking Record or Settings pages.

## Cross-cutting changes

### Sidebar icons

The four nav items get monochrome line icons. No per-page color identity, no icon in the page header — sidebar only.

- `Datasets` — collection / grid icon (e.g. Lucide `LayoutGrid` or `Library`)
- `Record` — record / circle-dot icon (e.g. Lucide `Circle` filled, or `Disc`)
- `Inference` — play / forward triangle (e.g. Lucide `Play`)
- `Settings` — gear (e.g. Lucide `Settings`)

Implementation: extend `SidebarNavItem` to accept an `icon` prop; render before the label, with the existing `code` (§01…) and label unchanged. Icon strokes use `currentColor` so the active-state inversion works automatically.

### Color palette / typography

No new tokens. All work uses the existing `@theme` values in `frontend/src/index.css`:

- Surfaces: `canvas` / `surface` / `surface-soft` / `surface-code` (for video panes)
- Text: `ink` → `slate` → `steel` → `stone` → `muted`
- Hairlines: `hairline` / `hairline-soft`
- Accents: `brand-tag` (blue), `brand-green` (fresh/live indicator dots), `brand-green-deep` (success status text, start markers), `brand-error` (failure/end), `brand-warn` (amber, stale). Plot lines beyond these accents pick from `slate`/`steel`/`stone` for additional traces.
- Fonts: `Inter` for body, `Geist Mono` for numeric / IDs / timestamps

Mockups for each layout are persisted under `.superpowers/brainstorm/3086729-1778713931/content/` for reference (`icons-only.html`, `inference-layout.html`, `episodes-c-v3.html`, `replay-layout.html`).

### Page-shell rule (cross-page)

All three redesigned pages drop the existing `max-w-[…px] mx-auto` wrapper that today centers their content (`InferencePage.tsx:75`, `EpisodesPage.tsx:33`, `ReplayPage.tsx:39`). They use the full viewport width inside `<main>`; horizontal layout is determined by each page's internal column structure.

Vertical structure also unifies:

```
<PageHeader />        — height ~52 px, never scrolls
<ControlRow?> or <Toolbar?>  — page-specific, fixed height, never scrolls
<MetaStrip?>          — page-specific, fixed height, never scrolls
<Body flex-1>         — fills remaining viewport; only this scrolls if needed
<BottomBar?>          — Inference's PhaseActionBar / Replay's scrubber; never scrolls
```

The body region is the only scrollable area within a page. Today's pages wrap the whole content area in `overflow-auto`; we keep that wrapper but constrain it to the body region only so that the bottom bar / scrubber stays anchored.

### Shared frame-data cache (cross-page)

`JointPlot` and `EndEffectorPlot` today each issue their own fetch to the frames endpoint (`JointPlot.tsx:44`, `EndEffectorPlot.tsx:54`). With the Episodes preview pane *and* Replay both rendering both plots, naive reuse means up to 4 fetches per episode selection.

Lift frame fetching into a `useEpisodeFrames(ds, idx)` React Query hook with a stable query key `["episode-frames", ds, idx]`. Both `JointPlot` and `EndEffectorPlot` consume this hook instead of fetching directly. React Query's per-key dedup ensures one fetch per `(ds, idx)` regardless of how many consumers mount it. This refactor is in scope for the implementation plan — without it the Episodes preview pane's selection-change UX becomes laggy.

## Page 1 — Inference

Current shape: a single phase-based Card centered in a `max-w-[1100px]` column. Pre-start → Ready → Recording → Review render serially as different Card contents in the same narrow column. Cameras appear only as colored status dots.

### Target layout: 3-column (settings / cameras / telemetry)

```
┌───────────────────────────────────────────────────────────────────────────┐
│ Inference                                            ● LIVE   so101 · …   │ ← PageHeader (no icon in header)
├──────────────┬──────────────────────────────────┬─────────────────────────┤
│ Session      │ Cameras (live)                   │ Telemetry               │
│              │ ┌──────────────┐ ┌─────────────┐ │ ┌──────┐ ┌──────┐       │
│ Config       │ │   front      │ │   wrist     │ │ │buffer│ │latcy │       │
│ Instruction  │ │              │ │             │ │ ├──────┤ ├──────┤       │
│ Dataset      │ │              │ │             │ │ │chunks│ │errors│       │
│ Episode      │ └──────────────┘ └─────────────┘ │ │clamps│ │safety│       │
│              │                                  │ └──────┘ └──────┘       │
│ [Stop sess.] │                                  │ Next action             │
│              │                                  │ ΔEE [...] grip 0.42     │
├──────────────┴──────────────────────────────────┴─────────────────────────┤
│ ⏺ Recording — instruction locked              [⏹ Stop episode]            │ ← phase action bar
└───────────────────────────────────────────────────────────────────────────┘
```

Widths: left ~220 px fixed, right ~200 px fixed, center fills the rest. The page uses the full viewport width (no central `max-w-*` wrapper on this page).

### Column contents

**Left — Session (always visible, fields adapt per phase)**

| Phase     | Fields shown                                   | Editable?       |
|-----------|------------------------------------------------|-----------------|
| pre-start | Config (select), Instruction (input), Dataset  | yes             |
| ready     | Config, Instruction (live), Dataset            | instruction yes |
| recording | Config, Instruction (locked, read-only), Episode #N · elapsed | no |
| review    | Config, Instruction, Episode summary           | no              |

Bottom of the left column: secondary action — `Stop session` (outline). Primary phase action lives in the bottom bar.

**Center — Cameras (live)**

Reuses the existing `CameraPreview` component (which subscribes to `/ws/cameras/{cam_name}` from `backend/mimicrec/api/ws/camera_hub.py`). No new WS endpoint or backend work is needed; the same camera-manager preview stream that powers Record drives Inference.

The grid wraps to 2 columns by default; when the active session exposes more than two preview-enabled cameras, it spills to a 2×N layout — same logic as Replay's existing video grid. Each tile reuses the existing camera label and frame-age overlay from `CameraPreview`.

Per-camera overlay (top-left badge): `<name> · <ageMs>ms`. Color dot in top-right driven by the existing `dotColor(ageMs)` palette mapping (`brand-green` → `brand-warn` → `brand-error`).

Note: if the session was started with `previewEnabled = false`, the WS closes with `preview disabled this session` (existing behavior). The center column shows an inline notice — "Camera preview disabled for this session" — instead of empty tiles.

**Right — Telemetry + Next action**

The existing `TelemetryBlock` tiles (buffer, latency, chunks, errors, clamps, safety) rendered as 2-column grid of `tile` cards. Below that: `Next action` panel showing `ΔEE` and `gripper` values, rendered with `surface-code` background to differentiate the model-output area visually. The compact `CameraHealth` row is dropped because the per-camera dot is already on each video tile.

### Bottom action bar

Single-row bar (full width) that adapts to phase:

| Phase     | Left side                              | Right side                                    |
|-----------|----------------------------------------|-----------------------------------------------|
| pre-start | "Configure inference session" hint     | [Start session] (disabled if no config + instruction or session blocker active) |
| ready     | "Ready — start an episode"             | [Start episode]                                |
| recording | "⏺ REC <elapsed>s · instruction locked" | [⏹ Stop episode] (destructive)                |
| review    | "Episode <#N> ended (<duration>s)"     | [Save success] [Save failure] [Discard]       |

Session blockers (`no-session`, `recording`, `review`, `already-inference`) and the existing `s.error` banner render above the bar — same content as today, but the inline `<Link to="/record">` shortcut stays.

### Component decomposition

The current `InferencePage` swaps a full Card per phase (`PreStartPanel`, `ReadyPanel`, `RecordingPanel`, `ReviewPanel` at `frontend/src/pages/InferencePage.tsx:121`). After this redesign the *layout* is stable across all phases — only the *contents within fixed regions* changes. To prevent phase panels from regressing into layout owners, decompose into four region components mounted at all times:

- `SessionColumn` — left column. Reads `phase` and the session config/instruction state from `useInferenceStore` and renders fields per the table above. Owns the secondary `Stop session` action.
- `CameraColumn` — center column. Mounts one `CameraPreview` per active session camera. Phase-independent.
- `TelemetryColumn` — right column. Renders the existing `TelemetryBlock`-style tiles + `Next action` panel. Phase-independent (it's a passive readout that's only populated when the WS feeds data).
- `PhaseActionBar` — bottom bar. Pure function of `phase`; renders the appropriate primary action(s) (Start session / Start episode / Stop episode / Save success+failure+Discard).

Phase remains domain state in `useInferenceStore`. None of the regions unmount across phase transitions; they just re-render.

### Error handling

No new error modes. The existing dismissable error banner moves to the top of the page (above the 3-column area) and the existing session blocker warnings render in the same location. All existing 409 / WebSocket-disconnect / inference-error paths behave unchanged.

## Page 2 — Episodes

Current shape: a single 8-column text table in a `max-w-[1240px]` column. No thumbnails, no filters, no preview.

### Target layout: compact list + preview pane

```
┌───────────────────────────────────────────────────────────────────────────┐
│ Episodes · pick_v2                              42 ep · 38 ok / 4 failed  │
├───────────────────────────────────────────────────────────────────────────┤
│ [All (42)] [Success (38)] [Failure (4)] | [teleop] [inference]    🔍 ___  │ ← Filter toolbar
├───────────────────────────────────────┬───────────────────────────────────┤
│ #042  pick up the bottle  4.2s ✓ tele │  Preview · #042                   │
│ #041  pick up the bottle  3.8s ✗ infe │  ┌─────────────────────────────┐  │
│ #040  pick up the bottle  5.1s ✓ tele │  │   video thumbnail (▶ play)  │  │
│ #039  pick up the bottle  4.5s ✓ tele │  └─────────────────────────────┘  │
│ #038  pick up the bottle  3.2s — tele │  Task    pick up the bottle       │
│ #037  pick up the bottle  4.0s ✓ infe │  Dur     4.2s · 126 frames        │
│ #036  pick up the bottle  4.6s ✓ tele │  Status  Success                  │
│ #035  pick up the bottle  2.8s ✗ infe │  Mode    teleop · so101           │
│ ...                                   │  Recorded 2026-05-14 10:23        │
│                                       │  ┌──────── Joint trajectory ───┐  │
│                                       │  │ (mini sparkline)            │  │
│                                       │  └─────────────────────────────┘  │
│                                       │  ┌──────── EE · XY ───────────┐   │
│                                       │  │ (mini xy plot)             │   │
│                                       │  └────────────────────────────┘   │
│                                       │  [▶ Open replay]   [Delete]       │
└───────────────────────────────────────┴───────────────────────────────────┘
```

### Filter toolbar

A single-row toolbar above the split. Chips toggle filters; all are AND'd (success-status × mode × search).

- **Status group** (radio-style: exactly one active): `All (n)`, `Success (n)`, `Failure (n)`. The `(n)` counts reflect the *unfiltered* totals; chips don't update their own count when others are applied, so the user can always see the absolute distribution.
- **Mode group** (chips, each independently toggleable): `teleop`, `inference`. If neither is on, both are shown (= no mode filter). If one is on, only that mode is shown.
- **Search** input on the right: substring match against `task` (case-insensitive).

Status chips use a left border edge in `brand-green-deep` / `brand-error` to telegraph their meaning even when inactive.

Filter state is purely local (`useState`) — no URL persistence in v1. If we want sharable filtered links later, lift to query params.

### Left — compact list

Five-column grid row: `# | task | duration | status | mode`. Click anywhere → selects (right pane updates). Hover → `surface-soft` background. Selected → `surface` background + 1 px left accent in `ink`. Status uses `tag-ok` / `tag-fail` / `tag-none` (✓ / ✗ / —).

Row height ~28 px so ~16 rows fit on a 900-px-tall viewport. Scroll independently of the right pane.

### Right — preview pane

Fixed width 360 px. Stack (top to bottom):

1. **Section label** — `Preview · #<idx>`.
2. **Video thumbnail** — a poster-frame image (or first-frame fallback) from the primary camera, with a centered play affordance. Click → seeks to `/datasets/:ds/episodes/:idx/replay`. (The thumbnail itself is not an inline video player; see "Thumbnail source" below.)
3. **Facts block** — Task, Duration · Frames, Status, Mode · Robot, Recorded.
4. **Joint trajectory mini** — multi-trace sparkline (j1–j6 as solid lines, gripper as dashed `ink`). Uses the same dataset as the full Replay plot, downsampled if needed for the mini size. Height ~44 px.
5. **EE XY mini** — top-down trajectory with start (`brand-green-deep`) and end (`brand-error`) dots. Aspect ~1.5:1.
6. **Actions row** — `▶ Open replay` (primary) + `Delete` (destructive secondary).

Selection state lives in the page (`useState<number | null>`); default is the first episode in the filtered list. Pressing `↑` / `↓` while focus is in the list moves the selection (nice-to-have, can defer).

### Thumbnail source

The mini plots reuse the same `joints.parquet` / EE columns the Replay page already loads — no new endpoint needed.

For the video thumbnail, the existing video endpoint (`backend/mimicrec/api/routes/datasets.py:288`) is a `FileResponse` serving the full MP4 — there is no per-frame route, so a "request one frame" approach is not available without backend work. v1 takes a fully client-side approach:

1. Mount an *offscreen* (zero-sized, `position: absolute; opacity: 0`) `<video muted playsInline preload="metadata">` pointed at the master camera's MP4 URL.
2. On `loadedmetadata`, set `currentTime = 0.001` (some browsers won't decode the very first frame; the small offset forces a seek).
3. On `seeked`, draw the video element to a `<canvas>` via `drawImage`, export as data URL (or `canvas.transferControlToOffscreen` + blob URL for memory friendliness), and render that as the poster.
4. Cache the resulting URL keyed by `(ds, episode_idx)` in a `useRef`-backed Map for the page lifetime, so re-selecting the same episode is instant.
5. Discard the offscreen video element once the seek-and-draw completes.

This avoids server-side writes and works consistently across Chromium / Firefox / Safari. If memory pressure becomes a concern on large datasets we add an LRU bound (default 50 entries) and/or move to a server-side `poster.jpg` written at episode-save time as a follow-up.

### Empty / loading / single-episode states

- Loading episodes list → existing "Loading…" text, left pane only.
- No episodes → existing "No episodes recorded yet." text, no right pane.
- No selection (transient between filter changes) → right pane shows "Select an episode" placeholder.
- Episode in left list but mini plot data fails to load → mini plot card shows "—" placeholder; rest of pane renders normally.

## Page 3 — Replay

Current shape after annotation removal: PageHeader + replay controls row + metadata strip + Video Card + Joint Card + EE Card stacked vertically, all in `max-w-[1100px]`. The video grid is constrained further (`max-w-4xl`) so on wide displays it's smaller than necessary.

### Target layout: split view with synchronized playback

```
┌───────────────────────────────────────────────────────────────────────────┐
│ Replay · pick_v2 / ep 042                          12.3s · 126 frames     │
├───────────────────────────────────────────────────────────────────────────┤
│ ← Episodes | Frame 48 / 126                          [▶ Replay on robot]  │ ← control row (HW replay only)
├───────────────────────────────────────────────────────────────────────────┤
│ Task pick up the bottle · Dur 4.2s · Frames 126 · ✓ Success · teleop · so101 │ ← meta strip
├──────────────────────────────────┬────────────────────────────────────────┤
│                                  │ ┌──────── Joint trajectory ─────────┐  │
│   ┌──────────┐ ┌──────────┐      │ │           ┊ cursor                │  │
│   │  front   │ │  wrist   │      │ │ ─────────┊─────────────           │  │
│   │          │ │          │      │ └───────────────────────────────────┘  │
│   └──────────┘ └──────────┘      │ ┌──────── End-Effector · XY ────────┐  │
│   (video grid, 1.5fr)            │ │              ●  ← cursor          │  │
│                                  │ │   start ●╲                        │  │
│                                  │ │           ╲___end ●               │  │
│                                  │ └───────────────────────────────────┘  │
├──────────────────────────────────┴────────────────────────────────────────┤
│ 00:00  ━━━━━━━●─────────────────────────  00:01.6 / 00:04.2               │ ← master scrubber
└───────────────────────────────────────────────────────────────────────────┘
```

Widths: full viewport; left video column 1.5fr, right plots column 1fr. Plots stacked equally. Bottom scrubber spans the full width.

### Synchronized playback ("master timeline")

**Single source of truth**: a `currentTimeSec` state on the page (with `currentFrameIdx = round(currentTimeSec * fps)` derived). All UI surfaces — video element, joint plot cursor, EE XY plot indicator, scrubber — read from this state.

**Clock**: the master `<video>` element's playback drives `currentTimeSec`. The `timeupdate` DOM event is browser-throttled (often 4–15 Hz) which makes the cursor visibly chunky. Wire two paths:

- **Primary (when supported)**: `HTMLVideoElement.requestVideoFrameCallback(cb)` for per-rendered-frame updates. Each callback writes `cb_metadata.mediaTime` to `currentTimeSec`.
- **Fallback**: `timeupdate` listener for browsers without rVFC (Firefox prior to 124, some Safari versions). This is the v1 ceiling we accept.

Either way, *write to the same setter* — the rest of the UI doesn't care which path produced the update.

**Mutations** come from three places:

1. **Video playback** — rVFC / `timeupdate` callback writes `currentTimeSec` (read-only push from the master).
2. **Scrubber drag / click** — calls `master.currentTime = t`. Do NOT write `currentTimeSec` directly from the handler; let the rVFC/`timeupdate` path pick it up, so there's exactly one writer.
3. **Click on joint plot** — same: maps click position to time `t`, calls `master.currentTime = t`.

This one-writer rule eliminates the feedback loop between scrubber-write → state-change → seek → timeupdate → state-change again.

**Master / secondary cameras**: the *first* element of `episode.cameras` is the master. Secondary `<video>` elements:

- Render with `controls={false}` and a pointer-event overlay so the user cannot independently play/pause/seek them.
- Mirror master `play()` / `pause()` / `playbackRate` and `ended` through `useEffect` hooks listening to the master's events.
- Mirror seeks: when `currentTimeSec` changes, call `secondary.currentTime = t` ONLY if `secondary.readyState >= HAVE_METADATA`, `!secondary.seeking`, AND `Math.abs(secondary.currentTime - t) > 1 / fps`. This prevents seek-storms on per-frame updates.

Sync drift up to 1 frame is acceptable; we don't try to lock secondaries frame-perfect.

**Cursor rendering**:

- *Joint plot* — Recharts `<ReferenceLine x={currentTimeSec} stroke="var(--color-ink)" strokeOpacity={0.7} />` inside the existing `<LineChart>`. ReferenceLine is data-domain, so it positions itself correctly without manual pixel math.
- *EE XY plot* — a small dot at the EE position for the current frame, color `ink`, drawn on top of the existing start/end dots. The existing path stays as-is (no progressive reveal).
- *Scrubber* — controlled `<input type="range" min={0} max={duration} step={1/fps}>` styled with project tokens, OR a custom DOM-and-pointerevent implementation if `<input type="range">` doesn't accept the styling needed. Decision deferred to implementation.

**Hover vs click semantics**:

- Hover on joint plot: existing Recharts tooltip showing values at hovered x. Does NOT change `currentTimeSec`.
- Click on joint plot: seeks. Recharts `<LineChart onClick={(state) => …}>` exposes `state.chartX` (pixel) and `state.activeLabel` (nearest data point's x value). For arbitrary click-anywhere seek, use `state.chartX` plus the chart's left margin + plot-width to map pixel → time; do not assume `activeLabel` covers continuous positions (it snaps to data points). Confirm the exact prop names against the installed Recharts version during implementation.
- Hover on EE XY plot: no tooltip in v1 (XY is a path, not a time series).
- Scrubber: click seeks, drag scrubs.

**Play / pause**: the master video's native controls are sufficient. Click anywhere on the master video toggles. The "▶ Replay on robot" button is a *separate concern*: it triggers HW replay of the recorded trajectory through the robot adapter, not video playback. Same label and behavior as today, just relocated into the control row.

### Component decomposition

- `useEpisodeTimeline(masterVideoRef, fps, duration)` hook — owns `currentTimeSec` state, exposes `seek(t)`. Internally wires rVFC / `timeupdate` from the master video, and exposes a single `seek` function that callers (scrubber, joint plot click) call to mutate. The hook ensures the one-writer invariant by only writing state from the rVFC/`timeupdate` callbacks, not from `seek`.
- `VideoPlayer` (existing) — accept `videoRef`, plus `isMaster` flag. Master renders default controls; secondaries render `controls={false}` + a pointer-event overlay that swallows clicks (preventing the user from desyncing the secondary's clock).
- `useSecondaryVideoSync(secondaryVideoRef, masterVideoRef, currentTimeSec, fps)` hook — mirrors play/pause/rate (via master event listeners) and guarded `currentTime` writes (readyState + !seeking + > 1/fps threshold).
- `JointPlot` (existing) — accept `cursorTimeSec` prop + `onSeek(t)` callback. Render `<ReferenceLine x={cursorTimeSec} />` inside the existing `<LineChart>`. Wire `onClick={state => onSeek(chartXToTime(state.chartX))}`. Tooltip behavior unchanged.
- `EndEffectorPlot` (existing) — accept `cursorFrameIdx` prop; render current-position dot on top of path.
- `Scrubber` (new, simple) — controlled by `currentTimeSec`, calls `onSeek` on click/drag.

### Constraint: HW replay safety

When the robot is performing HW replay (`subState === "replaying"`), scrubbing the video timeline must not affect the robot. That's automatic — scrubber only sets video state, not robot state. The HW-replay progress (`replayProgress.frame_index / total_frames`) keeps showing in the control row as today; visually distinct from the video scrubber.

## Inference HTTP API

No new endpoints. Existing surface (already callable by external apps):

- Session: `POST /session/start`, `POST /session/end`, `GET /session/state`
- Inference session: `POST /session/inference/start` (config + instruction), `POST /session/inference/stop`, `PUT /session/inference/instruction`, `GET /session/inference/state`, `GET /configs/inference`, `GET /configs/inference/{name}`
- Episode lifecycle: `POST /api/episode/start`, `POST /api/episode/stop`, `POST /api/episode/save` (success flag), `POST /api/episode/discard`
- Telemetry stream: `WS /ws/inference`

The layout work explicitly does not change these routes, request bodies, or response shapes. The implementation plan must call out at the merge gate that we re-ran an external HTTP-driven smoke run end-to-end (session start → episode start/stop/save → session stop) and confirmed all 200/2xx responses.

## Annotation removal

Already completed in commit `216d524` (B1 scope: feature code removed, dataset `subtask` column persistence layer untouched for schema compatibility). The Replay layout in this design reflects the post-removal state. No further annotation work in scope.

## Risks and open questions

- **Recharts API confirmation**: the click-to-seek implementation assumes `LineChart onClick` exposes `state.chartX` (pixel) plus enough chart-bounds info to map pixel → time without snapping to data points. Verify against the installed Recharts version during implementation; if not, fall back to an absolutely-positioned overlay `<div>` over the plot area that captures clicks and computes the time using its own bounds.
- **3-column Inference on smaller displays**: at < 1280 px width the 3-column layout becomes cramped. v1 keeps the layout fixed (matching Record's existing approach which already has a `useFitsRecordViewport()` fallback). The Inference page can adopt the same pattern if needed: detect viewport, collapse to a single column with stacked sections.
- **Scrubber state during HW replay**: if a user scrubs the video while HW replay is running, the visual scrubber (video) and the HW progress indicator (replay) diverge. Acceptable in v1 — the page just shows both states. Document this in the implementation.
- **rVFC fallback ceiling**: in browsers without `requestVideoFrameCallback`, cursor updates fall back to `timeupdate` (4–15 Hz). Visually chunky on those browsers, but acceptable for v1.
- **JointPlot uses a custom color palette** (`#2563eb`, `#dc2626`, …) that does not match the project brand tokens. Out of scope for this design — flag for a follow-up to bring it in line with `brand-tag` / `brand-error` / `brand-green-deep` / `brand-warn` / `steel` / `stone` (and dashed `ink` for gripper).

## Out of scope for this design

- Record page (already redesigned recently on this branch).
- Settings page.
- DatasetsPage layout (only the annotation-strip change has landed).
- Backend API additions beyond what already exists.
- URL-state persistence of Episodes filters.
- Keyboard shortcuts beyond optional ↑/↓ in Episodes list.
- New design tokens.
