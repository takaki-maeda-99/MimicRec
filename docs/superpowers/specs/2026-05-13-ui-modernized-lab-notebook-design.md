# UI Modernization — Modernized Lab Notebook

**Date:** 2026-05-13
**Status:** Draft (awaiting user review)
**Builds on:** `docs/superpowers/specs/2026-05-09-ui-mintlify-refresh-design.md`

## Summary

Apply a new visual *language* on top of the existing Mintlify token set, rather than re-tokenising. The language is what the brainstorm session validated as "modernized Lab Notebook": clean light surfaces, **Inter throughout** (no serif/italic flair), **§-numbered sections**, **fact-row tables with mono numerals**, **subtle corner ticks** as structural decoration, and **dark "instrument wells"** for live data (cameras, plots). Two pages — `RecordPage` and `DatasetsPage` — have been mocked and approved at high fidelity (see `.superpowers/brainstorm/211843-1778620183/record-c-v3.html` and `datasets-c-v3.html`). This spec codifies the language and rewrites the four pages that are styling work (Shell + Datasets + Record + Episodes + Settings). The two pages that are phase-driven workflow surfaces (`ReplayPage`, `InferencePage`) receive only the token/primitive uplift in this pass — their layouts are deferred to follow-up specs.

The refresh is built **on top of** the existing Mintlify token foundation in `frontend/src/index.css` — colors, type scale, radius, spacing all carry over. New work is two new tokens (`on-dark-dim`, `on-dark-mark`), four new primitives (`SectionMark`, `InstrumentWell`, `Sparkline`, `CornerTicks`, plus `PageHeader`), refactored `PropertyRow`/`Badge`/`Button`/`SidebarNavItem`/`Layout`/`EStopButton`, and rewrites of `RecordPage` + `DatasetsPage` + `EpisodesPage` + `SettingsPage`. The proposed `FactRow`/`FactTable`/`Badge variant="status"` from earlier drafts collapse into the existing primitives — they are **not** new files.

## Goals

- Land a single, internally consistent visual language across all six pages (`Datasets`, `Record`, `Episodes`, `Replay`, `Inference`, `Settings`) — no per-page styling improvisation. For `Replay` and `Inference`, consistency means the shell, tokens, and primitives are unified; their page-internal *layouts* are deferred and remain as-is in this pass (see Non-Goals).
- Make the **operator screen (`Record`) fit a single browser viewport** with no scroll. (Hard requirement from the brainstorm — recording is the screen the user stares at for minutes at a time.)
- Make the **primary action of every page unambiguous**: exactly one button per page region is filled-ink (primary); everything else is secondary or tertiary. Resolves the current `DatasetsPage` "six co-equal buttons" problem.
- **Promote `E-Stop` to the global Layout** as an always-visible affordance when a robot is connected, and remove it from `Record`'s controls bar (current proximity to `End Session` is a misclick risk).
- Reuse the existing Mintlify token set verbatim where it fits; add **at most two new color tokens** (an instrument-well dim text shade, and an instrument-well accent for corner ticks on dark surfaces). Do not invent a parallel palette.

## Non-Goals

- New product features. No changes to APIs, routes, websocket protocols, state stores, recording semantics, or hub-push behaviour.
- Backend / Python changes.
- Dark mode.
- Mobile / responsive layouts.
- Internationalisation. Existing Japanese strings in `RecordPage` stay as-is.
- Modal rewrites (`CreateDatasetModal`, `ExportDatasetModal`). They inherit the new primitives but their structure is preserved.
- The subtask annotation flow (`SubtaskAnnotator`, `SubtaskTimeline`). Out of scope; follow-up spec.
- **`ReplayPage` and `InferencePage` redesigns.** Both are phase-driven workflows (multi-camera `VideoPlayer` ownership, instruction lifecycle, model-done/action-preview, safety events) — restyling them is a workflow redesign disguised as a paint job, and that is not what this spec is for. They will receive token+primitive benefits passively (new `Badge`, `Button`, `Card` look) but their layouts are out of scope. Both get their own follow-up specs.
- The `MockMissionControl` / `MockEditorial` / `MockNotebook` exploration pages at `/mocks/*`. **Deleted together with the shell refactor**, not as a late phase, so the app never ships in a state where the mocks reference the old design language.

## Background

The brainstorm session at `.superpowers/brainstorm/211843-1778620183/` walked through:

1. Three full-screen mocks already in the repo (`MockMissionControl`, `MockEditorial`, `MockNotebook` under `frontend/src/pages/mocks/`).
2. Per-use-case scoring of each mock against MimicRec's real demands (live recording, dataset curation, replay).
3. User selected **Lab Notebook** as the single direction, but with the **cream paper background and the Fraunces / Instrument Serif italic accents removed** — preserving only the *structural* elements of the journal aesthetic.
4. Iterated on `RecordPage` (v1 → v2 → v3) to validate single-viewport layout. v3 approved with one change: `E-Stop` moves out of `Record`'s controls bar.
5. Iterated on `DatasetsPage` (v3) for the catalogue surface. Approved.

The resulting "modernized Lab Notebook" is: **structural rigor of a research journal × surface aesthetic of a contemporary product tool** (Linear / Vercel direction). No serif, no cursive, no aged paper — but §-numbered sections, fact-row tables, mono numerals, corner ticks, and dark instrument wells stay.

## Visual Language

### 1. Tokens — reuse + two additions

The brainstorm-fidelity mock used ad-hoc hex values. The implementation maps each one onto the existing Mintlify token in `frontend/src/index.css`:

| Mock value | Mintlify token | Notes |
|---|---|---|
| `#f7f7f5` (page bg) | `surface` | use as `bg-surface` for page background |
| `#ffffff` (cards, sidebar) | `canvas` | |
| `#fafaf9` (hover / secondary surface) | `surface-soft` | |
| `#e7e5e0` (rule) | `hairline` | |
| `#efedea` (rule-soft) | `hairline-soft` | |
| `#18181b` → `#0a0a0a` | `ink` | mock was zinc-900, system uses true black; use `ink` |
| `#27272a` | `charcoal` | |
| `#3f3f46` | `slate` | |
| `#6b6b67` | `steel` | |
| `#a1a1a0` | `stone` | |
| `#d97706` (amber-600, §-markers + warning) | `brand-warn` (#c37d0d) | dual-role: §-markers AND warning state. See note below. |
| `#15803d` (forest green ok) | `brand-green-deep` (#00b48a) | system mint replaces forest — the brand is already mint, the mock briefly diverged. Sparklines and "Synced" pills use the system mint. |
| `#b91c1c` (danger) | `brand-error` (#d45656) | |
| `#4338ca` (indigo, "Pushing") | `brand-tag` (#3772cf) | existing system blue, good fit |
| `#09090b` (instrument well bg) | `canvas-dark` | |
| `#27272a` (instrument well rule) | `hairline-dark` | |
| `#fafafa` (instrument well ink) | `on-dark` | |
| `#71717a` (instrument well dim) | **new: `on-dark-dim`** | system has `on-dark-muted` (#b3b3b3) which is too light for secondary text on a near-black panel; need a darker grey. Value: `#71717a` (zinc-500). |
| `#fbbf24` (instrument well corner ticks, plot lines) | **new: `on-dark-mark`** | a brighter amber than `brand-warn` reads better against `canvas-dark`. Value: `#fbbf24` (amber-400). |

**Two new tokens to add to `index.css`:**

```css
--color-on-dark-dim:  #71717a;   /* secondary text on canvas-dark wells */
--color-on-dark-mark: #fbbf24;   /* corner ticks, plot lines, accent on canvas-dark */
```

**On `brand-warn` doing double duty:** §-markers (page headings, in-block section labels) and warning states (Stale pill, J6 sparkline going off-baseline, FPS-actual-below-target) both use `brand-warn`. This is deliberate, but to keep warnings legible against the decorative use, the two roles must be visually disambiguated by shape, weight, and density — not just color:

| Role | Visual rule |
|---|---|
| §-marker (decorative / structural) | Always: `micro` size (10–12px), `font-mono`, uppercase, letter-spacing `0.16em`, no border or fill. Used inline in headers. |
| Warning state (functional / alert) | Always: ≥13px, sans-serif, OR a solid `brand-warn / 15%` pill background, OR paired with a leading icon, OR enclosed in a bordered container. Never bare inline text. |

If an operator habituates to amber-as-decoration, warning states still differ at first glance because they're larger, filled, iconned, or contained. The Pushing pill uses `brand-tag` (blue), the Synced pill uses `brand-green`, and `brand-error` is reserved strictly for failures — so the colour vocabulary stays semantically clear at the pill level.

### 2. Typography

All text in `font-sans` (Inter). All numerals — joint positions, EE pose, frame counts, episode counts, page numbers, repo IDs, timestamps, error codes — in `font-mono` (Geist Mono). **No serif anywhere.** No italic anywhere.

Mintlify type tokens map directly:

| Role | Token | Used for |
|---|---|---|
| Page title | `heading-5` (18px / 600) | Top bar title (e.g. "Live capture — pick & place, blue cube") |
| Big numeral | `heading-2` (36px / 600) | Episode elapsed time, dataset count summary |
| Block label | `caption-bold` uppercased, letter-spacing 0.18em | `JOINT POSITIONS`, `END-EFFECTOR POSE`, `EPISODE PROGRESS` |
| Section mark | `micro` mono, letter-spacing 0.16em, `brand-warn` | `§02 · Record`, `§01 · Datasets`, `§02.B · telemetry` |
| Fact-row key | 9px / 600 / uppercase / 0.18em letter-spacing / `stone` | Inside fact-row tables — `ROBOT`, `CAMERAS`, `EPISODES` etc. |
| Fact-row value | `caption` (13px) or `code-sm` mono (13px) | Plain text for prose values, mono for numerals |
| Body | `caption` (13px) | Default body text in cards |

`heading-1` and `display-lg` are not used by this design. Page headings use a smaller scale because the top bar carries identity (sidebar logo + §-mark).

### 3. Structural patterns

These are the load-bearing visual idioms. New primitives (next section) implement them.

**§-numbering.** Every top-level *sidebar nav* item has a stable section number: `§01 · Datasets`, `§02 · Record`, `§03 · Inference`, `§04 · Settings`. **Nested routes under a top-level page extend the code with a trailing letter**: `/datasets/:ds/episodes` is `§01.B · Episodes`, `/datasets/:ds/episodes/:idx/replay` is `§01.C · Replay`. The Datasets list itself is `§01.A` implicitly (the unmarked default). Sub-sections inside a single page use a second segment too: `§02.A · Specimens — live cameras`, `§02.B · Episode progress`, `§02.C · Controls`. So `§NN.X` means "child route of §NN" when X follows a route boundary, and "in-page sub-section of §NN" when X follows a page-internal divider — context disambiguates and the sidebar only ever highlights the §NN parent.

**Fact rows.** Whenever we display key/value metadata (camera resolution, joint position, dataset stats, hub config), use a fact-row table: small uppercase key, mono numeral or sans-serif value. Dashed `hairline-soft` row separators in dense blocks; solid `hairline` boundaries when the table is the whole block.

**Corner ticks.** Cards that contain *captured / observational* content (camera wells, dataset cards) get a 4-tick decoration: an 8×8 amber L-bracket inset at each corner. This is the single most distinctive visual signature of the language — it ties everything to the "research specimen" frame without writing any cursive. On `canvas-dark` surfaces the ticks use `on-dark-mark`; on `canvas` surfaces they use `brand-warn`.

**Instrument wells.** Live data (camera feeds, XY-trajectory plots, anything that streams) goes inside a dark panel: `bg-canvas-dark`, `rounded-md`, internal `on-dark` foreground. Header (`text-on-dark-dim`, mono, uppercase) and a small `brand-green` LIVE indicator with cyan pulse. Corner ticks in `on-dark-mark`. This is the only place dark surfaces appear in the app.

**Sparklines.** Small inline SVG line plots, 160×14 px, stroked in `brand-green-deep` for nominal and `brand-warn` for anomalous values. Drawn beside each joint position. They turn a 7-row fact-table into a calm, glanceable health indicator.

**Status pills.** Six discrete states for hub sync, recording state, and inference health: `synced` (mint), `pushing` (blue, pulsing dot), `stale` (amber), `pending` (dashed, stone), `unconfigured` (dashed, no dot), `error` (red). Used in `Datasets`, `Inference`, and `Replay`.

### 4. Spacing & layout

Use the existing Mintlify spacing scale (`xxs`..`section-lg`). Two layout primitives:

- **App shell**: `flex h-screen` with a 220px sidebar and a flex-1 main. Both `overflow-hidden` at the top level; pages decide their own internal scroll behaviour.
- **Page top bar**: 52px tall, `bg-canvas`, `border-b border-hairline`, single row. Carries §-mark + page title + state badges (e.g. REC) + page number.

`RecordPage` overrides default behaviour: `main` is `overflow-hidden` and its body uses a viewport-locked grid (`100vh` minus top bar minus brief strip minus controls bar) so nothing scrolls. Other pages let `main` scroll normally.

## Components

### New primitives (`frontend/src/components/ui/`)

Four new files. Everything else extends or refactors what already exists.

| Component | Props | Notes |
|---|---|---|
| `SectionMark` | `code` (e.g. `"§02"`), `name` (e.g. `"Record"`) | Mono caps with `brand-warn`; used in top bars and as in-page sub-section labels |
| `InstrumentWell` | `header`, `live?`, children, `ticks?` (default true) | Dark surface (`bg-canvas-dark`) with header strip + optional LIVE indicator + corner ticks |
| `Sparkline` | `data` (number[]), `tone?` (`"ok"` \| `"warn"`), `width?`, `height?` | Tiny SVG line plot. No axes. |
| `CornerTicks` | `tone?` (`"light"` for canvas, `"dark"` for canvas-dark) | Absolute-positioned 4-tick decoration; expects a `position: relative` parent |
| `PageHeader` | `code`, `name`, `title`, `meta?`, `actions?`, `state?` | The 52px top bar. `state` slot for the REC badge or other live indicators |

### Refactored primitives (no new files)

| File | Change |
|---|---|
| `components/ui/property-row.tsx` | **Already exists** and is the row primitive for key/value pairs. Refactor: add a `density?: "comfortable" \| "compact"` prop and a `divider?: "solid" \| "dashed"` prop so it can serve both the dense joint-position table (compact + dashed) and the dataset card facts strip (comfortable + solid). The brainstorm-fidelity mock's `FactRow` design is implemented inside `PropertyRow`, not as a new component. |
| `components/ui/badge.tsx` | Add a new `status` variant family with the six hub-sync / recording / inference states: `synced`, `pushing`, `stale`, `pending`, `unconfigured`, `error`. `pushing` carries an animated pulse dot via a sub-element; the others have a static dot. Existing semantic variants (`success`, `warning`, `destructive`, `outline`, `tag`) are kept untouched for back-compat. The proposed `Badge variant="status"` from earlier drafts is **not** a new component — it's `Badge variant="status" state="..."`. |
| `components/ui/button.tsx` | Add `size="xs"` (28 px tall, padding `4px 10px`, `text-micro`) for the dense toolbars on `DatasetsPage` and the `RecordPage` controls bar. This is a real API change — existing variants stay. |
| `components/ui/sidebar-nav-item.tsx` | Add `code` prop for the §-prefix. Active state: black background with `on-primary` text and `on-dark-mark` colour for the code numeral. |
| `components/Layout.tsx` | Switch sidebar nav items to use `§NN` prefix. Move `SessionBadge` and `GoProPendingBadge` from the header into a "Status" group in the sidebar's lower half (mirrors the v3 mock's `Hub / Robot / Session / Queue` grid). Add a global `EStopButton` slot above the version footer that becomes visible whenever `robot === "rebotarm"` and the session is active. |
| `components/EStopButton.tsx` | Move out of `RecordPage` and out of `InferencePage` (the per-page render at `InferencePage.tsx:68-70` is also removed — global E-stop replaces both). Rendered by `Layout.tsx`. Visual: **64 px tall**, full-width inside the sidebar, double-red border kept as the safety affordance; "EMERGENCY / E-STOP" two-line label set at body-md-medium so it's actually a panic target, not a footer button. Keyboard binding preserved unchanged. |

### Components deleted

- The three `MockMissionControl` / `MockEditorial` / `MockNotebook` pages and their `/mocks` routes — deleted in the same commit that removes them. `sample-data.ts` is also removed.

## Per-page applications

### App shell — `Layout.tsx`

- Sidebar 220 px, `bg-canvas`, `border-r border-hairline`.
  - Top: brand glyph (18×18 `ink` square with a 7×7 `brand-warn` notch in the bottom-right corner) + "MimicRec" name in 16px / 700 / `ink`. Date and `@username` below in mono `steel`.
  - Index nav: four `SidebarNavItem`s with `§01..§04` codes.
  - Status block: `Hub`, `Robot`, `Session`, `Queue` as a mono fact-row strip. Replaces the current `SessionBadge` + `GoProPendingBadge` in the header.
  - Footer: version + build SHA in mono `stone`.
  - **E-stop slot** sits between the status block and the footer. Visible when `robot === "rebotarm"` and `state !== "idle"`.
- Main: `flex-1`, defaults to scroll. `RecordPage` overrides to `overflow-hidden` + viewport grid.

### `DatasetsPage` (mocked & approved)

Top bar: `§01 · Datasets` + "Catalogue" + count chip; right side carries the HF auth pill (existing logic) and the `+ New dataset` button (primary).

Page heading row: an `h2` ("Recorded data, sorted by recency."), a one-line lede, and a four-stat summary (datasets / episodes / frames / total time) right-aligned.

Toolbar: SORT / FILTER / ROBOT dropdowns plus a search input. **New behavior**: dropdowns are wired to in-memory client-side filtering of the existing `useDatasets` result. No backend changes.

List: one `DatasetCard` per row, no grid. Each card:

- `CornerTicks` light tone.
- Header row: `01` index (mono `stone`), dataset name (17px / 700), task hint (`steel`), `Badge variant="status"` on the right.
- Fact strip: Robot, Cameras, Episodes (mono), Frames (mono), Duration (mono), Touched. Solid hairline top/bottom.
- Hub row: repo (mono), `private` / `public` tag, `auto-push` tag, last-pushed timestamp (or error message when state is `error`).
- Actions: `Open episodes →` is the lone primary; `Push`, `Edit Hub`, `Export`, `Annotate` are secondary; `Delete` (danger variant) is pushed to the right by `flex-1`.

Annotation progress footer: shown when `annotating !== null`. A `caption-bold` label "Annotation progress" (no `§` — this is a transient operational indicator, not a navigable section) + dataset name + progress bar + percent.

### `RecordPage` (mocked & approved)

Top bar: `§02 · Record` + title (`Live capture — <current task>` during active recording; `Configure session` while idle); REC badge when recording.

Body grid (viewport-locked): two camera `InstrumentWell`s on the top row (cols 1–2), a telemetry rail spanning both rows on col 3, episode-progress block on the bottom row col 1, XY-trajectory `InstrumentWell` on the bottom row col 2. See the v3 mock for exact proportions (`1fr 1fr 380px` columns, `1.35fr 1fr` rows).

**Target viewport:** the single-no-scroll layout is engineered for **1440×900** and above. The defended floor is `viewport_width >= 1280 AND viewport_height >= 900`: at and above that floor, the no-scroll layout is required to fit. Below the floor (either dimension), the grid degrades:

1. Collapsing the right telemetry rail into a single full-width row underneath the cameras (telemetry blocks side-by-side), giving the cameras full main-area width.
2. Stacking the bottom row (`Episode progress` and `XY trajectory`) underneath telemetry instead of beside the cameras.

Under that degraded layout, `main` is allowed to scroll. The breakpoint is exclusive (`width < 1280 OR height < 900` ⇒ degraded). Verification covers both sides explicitly.

`EEMonitor`, `KeyboardTeleop` (web_keyboard mode), and GoPro-pending state are folded into the telemetry rail as additional blocks rather than scattered through the page as today. `RecordingControls` is reshaped into the single bottom controls bar described below.

Controls bar: `Stop & review` (primary, pulsing red dot when recording) + `Save episode` + `Discard` + separator + `Idle pose` + `Pause stream` + flex spacer + `End session` (danger). **No `E-Stop` here — it lives in the sidebar.**

Idle state (no session): top bar shows `§02 · Record · Configure session`. Body is replaced by the existing `SessionConfigForm` wrapped in a `feature`-variant card.

### `EpisodesPage` — `§01.B`

Top bar: `§01.B · Episodes` + `<dataset_name>` (mono) + a back-link to Datasets.

Body: a `PropertyRow`-styled `<table>` instead of the current plain rows. Columns: `#` (mono `stone`), `Task`, `Duration` (mono), `Frames` (mono), `Success` (`brand-green-deep` for true, `brand-error` for false, `stone` "—" for null), `Mode`, `Recorded`, action cell. Row hover: `surface-soft`. Click row → navigate to replay. Delete button stays in the rightmost cell with `danger` variant.

No corner ticks here — the table grid already provides the structure.

### `SettingsPage` — `§04`

Sections are §-numbered: `§04.A · Robot`, `§04.B · Cameras`, `§04.C · Inference`, `§04.D · Hub`. Each section is a `feature` card with a `SectionMark` header, a one-line description, and the existing `ConfigCard` / `CameraConfigForm` machinery inside. No layout reshuffle — the page already lists configuration cards; this is a header/spacing pass.

### `ReplayPage` — `§01.C` (deferred — token & primitive pass only)

`ReplayPage` is a phase-driven workflow page: multi-camera `VideoPlayer` instances (each owns native playback controls), `JointPlot` + `EndEffectorPlot` Recharts components, and the `SubtaskTimeline` / `SubtaskAnnotator` labelling flow. A real visual rewrite requires deciding whether to introduce a shared scrubber, how subtask annotation fits into the new language, and how the multi-video synchronisation model should work — none of which is in scope for this pass.

In-scope changes:

- Page header uses `PageHeader` with code `§01.C` and dataset/episode in mono.
- Buttons swap to the refactored `Button` variants automatically. The "Save labels" / "Discard" / "Back" buttons inherit the new look without restructuring.
- `Badge` instances on the page pick up the new `status` variant where they reflect a hub-sync or recording state.

Layout, video player arrangement, and `SubtaskTimeline` are untouched here. See follow-up spec.

### `InferencePage` — `§03` (deferred — token & primitive pass only)

`InferencePage` is also phase-driven (`pre-start` / `ready` / `recording` / `review`), with model-config loading, instruction lifecycle (lock/unlock during inference), model-done events, action-preview, and safety-event handling. Restyling without addressing the workflow is shallow and risks misleading the operator.

In-scope changes (mirroring Replay):

- Page header uses `PageHeader` with code `§03`.
- `Button`/`Badge`/`Card` variant uplift through the new tokens and primitives.
- The page-level `EStopButton` render at `InferencePage.tsx:68-70` is **removed** as part of the E-Stop globalisation (the sidebar E-Stop covers Inference too).

Layout, model-config picker, instruction lifecycle, and review controls are untouched. See follow-up spec.

## E-Stop placement decision

E-Stop is a **safety affordance**, not a workflow action. The brainstorm flagged its current position next to `End Session` in `RecordPage` as a misclick risk (one freezes the arm, the other tears down the data-collection session — costs are not symmetric).

New placement: **`Layout.tsx` sidebar**, in a dedicated slot above the version footer. Shown whenever a robot capable of E-stop is present (`robot === "rebotarm"`) and the session is active (`state !== "idle"`). Hidden otherwise.

Sizing matters here. A typical operator is visually locked onto the camera wells in the centre of the screen; the E-Stop has to be a *panic target*, not a tidy footer button. The button is:

- **64 px tall**, full width inside the 220 px sidebar (i.e. roughly 200 px × 64 px clickable area).
- Double red border, solid `brand-error` text, "EMERGENCY" micro-uppercase eyebrow + "E-STOP" body-md-medium body, plus the existing keyboard hint.
- Always rendered at the same y-position when present, so muscle memory works.

Keyboard binding (existing) is preserved unchanged — it's the actual panic mechanism; the visual is the secondary affordance.

Consequences:

1. `RecordPage` no longer renders `<EStopButton />` — the conditional render block at `RecordPage.tsx:148-151` is deleted.
2. `InferencePage`'s header-level `<EStopButton />` at `InferencePage.tsx:68-70` is also deleted. Global E-Stop is the single source.
3. The underlying handler (`useEstop` / WS call) is unchanged. This is a render relocation only.

## Token migration

Concrete changes to `frontend/src/index.css`:

```css
@theme {
  /* … existing tokens … */
  --color-on-dark-dim:  #71717a;
  --color-on-dark-mark: #fbbf24;
}
```

No other token changes. Existing tokens are reused as mapped in the "Tokens" table above.

## Phasing / Order of work

The implementation plan (separate doc, written next) will sequence as:

1. **Tokens + primitives.** Add `--color-on-dark-dim` and `--color-on-dark-mark`. Build the four new primitives (`SectionMark`, `InstrumentWell`, `Sparkline`, `CornerTicks`, plus `PageHeader`). Refactor `PropertyRow` (density + divider props), `Badge` (`status` variant family with six states), `Button` (`size="xs"`), `SidebarNavItem` (`code` prop). Tests for `Sparkline` (data → SVG points) and `Badge status` (state → class). No page changes yet — full app still uses old layouts. The new primitives are dead code at the end of this phase, by design.

2. **Shell + global E-Stop + per-page E-Stop removal + mocks teardown** — safety-impacting changes in their own reviewable PR. Apply `PageHeader` and the sidebar refactor in `Layout.tsx`. Add the global `EStopButton` slot. Delete `<EStopButton />` from `RecordPage` (`RecordPage.tsx:148-151`) and `InferencePage` (`InferencePage.tsx:68-70`) in the same change. Delete `frontend/src/pages/mocks/*` and the `/mocks/*` routes in `App.tsx`. After this phase every page renders the new shell. The page bodies are still old, which is transitional but the visual mix is intentional and limited to one PR's lifespan. **Briefly, `RecordPage` is missing its in-page E-Stop while keeping its old body** — the sidebar E-Stop is the replacement and is verified working in this PR; the keyboard binding is the actual panic mechanism throughout.

3. **`RecordPage` rewrite.** Apply the single-viewport grid: `InstrumentWell` cameras + telemetry rail + episode progress + XY plot + new controls bar. Idle state preserved (config form). This is the largest visual change but its safety-critical pieces (E-Stop relocation) already shipped in step 2, so review can focus purely on layout.

4. **`DatasetsPage` rewrite.** New `DatasetCard` body using `PropertyRow` for facts, `Badge variant="status"` for hub state, `CornerTicks` for the card frame. Toolbar with SORT / FILTER / ROBOT (client-side) and search. HF auth pill moves into the top bar via `PageHeader actions`.

5. **`EpisodesPage` rewrite.** Table polish only — no structural changes.

6. **`SettingsPage` rewrite.** §-numbered sections with `SectionMark` headers wrapping the existing `ConfigCard` machinery. Lowest risk, lowest-payoff page.

**Out of scope for this plan:** `ReplayPage` and `InferencePage` full layout redesigns. They receive the shell, the new primitives passively, and have their per-page `EStopButton` removed (step 2). Their workflow redesigns are separate follow-up specs.

Steps 1 → 2 → 3 must land in order. Steps 4–6 are independent and can land in any order after step 3.

## Open decisions deferred to implementation plan

- Exact dropdown menu component for the `DatasetsPage` toolbar — reuse an existing pattern or pull a small headless library.
- Sparkline data source for live joint values — the WebSocket currently streams positions but the frontend doesn't retain a rolling buffer; need a small `useRollingBuffer(seconds)` hook. Affects `RecordPage` step 2.

## Verification

A change ships only when:

- Each rewritten page passes manual verification at the standard viewport (1440×900) and the degraded viewport (1200×800).
- `RecordPage` shows **no scroll** in the active-session state at any viewport satisfying `width ≥ 1280 AND height ≥ 900` (test at 1280×900 exactly and at 1440×900).
- Below the floor (test at 1200×800), `RecordPage` shows the degraded layout (telemetry rail wrapped under cameras, scroll allowed). Both modes look intentional — nothing overlapping, nothing truncated.
- Sidebar at 900 px tall fits its full inventory without overflow: brand header (~70 px) + Index nav (~160 px) + Status block (~140 px) + global E-Stop slot when active (~80 px including padding) + version footer (~40 px) ≈ 490 px — well under budget; verify with E-Stop visible.
- The single primary action per page is verifiable by inspection (one black `bg-ink` button per page region).
- E-Stop appears in the sidebar only when `robot === "rebotarm"` and `state !== "idle"`; clicking still routes through the existing handler. `RecordPage` and `InferencePage` no longer render their own `<EStopButton />`.
- `pnpm build` succeeds with no new type errors.
- The visual matches the approved v3 mocks (`record-c-v3.html`, `datasets-c-v3.html`) within reason (allowing for real-data variations).
- §-numbering: sidebar nav highlights the parent §NN when on a child route (e.g. `/datasets/:ds/episodes` keeps `§01 · Datasets` active in the sidebar, with the page header reading `§01.B · Episodes`).
