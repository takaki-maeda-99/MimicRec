# UI Refresh — Mintlify Design System Adoption

**Date:** 2026-05-09
**Status:** Draft (awaiting user review)
**Source:** `.claude/DESIGN.md` (Mintlify Inspired Design System, alpha)

## Summary

Refresh the MimicRec frontend visual layer by adopting the Mintlify-inspired design tokens, primitives, and layout patterns described in `.claude/DESIGN.md`. The refresh applies the **system tokens only** — colors, typography, radius, spacing, components such as buttons / cards / inputs / tabs / sidebar nav. It does **not** import the marketing surfaces (hero gradients, cloud / rocket illustrations, testimonial-orange cards). The dashboard's information density and interaction model are preserved; only the visual language changes.

Delivery is a single sweep: token foundation, primitive refactor, layout shell, then all six pages and their thirteen domain components in one pass (`Layout.tsx` is treated separately as the shell).

## Goals

- Replace the current ad-hoc Tailwind palette (`text-blue-600`, `bg-purple-100`, `text-red-600`, `bg-gray-*`) with a strict, named token set sourced from `.claude/DESIGN.md`.
- Establish a typography pairing of **Inter** (UI prose) + **Geist Mono** (code, values, IDs) consistently across the app.
- Reduce per-page styling decisions: each page consumes primitives (`Button`, `Card`, `PillTab`, `CodeInline`, `PropertyRow`, `SidebarNavItem`) rather than authoring ad-hoc class strings.
- Reserve the brand mint (`brand-green`) for a single semantic role: **session-state and connection indicators** (sidebar connection dot, ready / replaying / streaming pills, annotation-complete confirmation). Mint is NOT used as a primary CTA color and NOT as the input focus signal.

## Non-Goals

- Marketing surfaces: hero atmospheric gradients, cloud / rocket illustrations, `testimonial-orange` cards.
- 3-column documentation layout (sidebar / prose / TOC). The dashboard uses a 2-zone shell (sidebar / main).
- Dark mode. The Mintlify spec itself flags dark tokens as unpublished. Tokens are named so dark mode can be added later without renaming.
- New product features. No changes to data flow, API surface, routes, state stores, or websocket protocols.
- Backend / Python changes. This refresh is frontend-only.
- Internationalization or RTL.

## Architecture

Three layers, each with a clear single responsibility:

### 1. Token layer — `frontend/src/index.css`

Tailwind v4 `@theme` declarations that re-export every Mintlify token consumed by the app as a Tailwind utility. Tokens originate here and only here. Every variable lives under one of v4's recognised theme namespaces so the corresponding utility is auto-generated:

| Mintlify category | v4 theme namespace | Resulting utilities |
|---|---|---|
| Colors | `--color-*` | `bg-*`, `text-*`, `border-*`, `ring-*`, `from-*` etc. |
| Font families | `--font-sans`, `--font-mono` | `font-sans`, `font-mono` (Inter and Geist Mono respectively) |
| Type scale | `--text-*` (with paired `--text-*--line-height` and `--text-*--letter-spacing`) | `text-<name>` |
| Radius | `--radius-*` | `rounded-<name>` |
| Spacing | `--spacing-*` | `p-<name>`, `px-<name>`, `m-<name>`, `gap-<name>`, `w-<name>`, `h-<name>` etc. |

Imports Inter + Geist Mono via Google Fonts CDN at the top of the file:

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap');
@import "tailwindcss";

@theme {
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'Geist Mono', 'SF Mono', Menlo, Consolas, monospace;
  /* --color-*, --text-*, --radius-*, --spacing-* declarations follow */
}
```

**Color tokens (24):** `primary`, `on-primary`, `brand-green`, `brand-green-deep`, `brand-green-soft`, `brand-tag`, `brand-warn`, `brand-error`, `canvas`, `canvas-dark`, `surface`, `surface-soft`, `surface-code`, `hairline`, `hairline-soft`, `hairline-dark`, `ink`, `charcoal`, `slate`, `steel`, `stone`, `muted`, `on-dark`, `on-dark-muted`. **Excluded:** `hero-sky-*`, `hero-dark-*`, `testimonial-orange` (pure marketing), `brand-annotate`, `brand-cursor` (twoslash docs annotation system, not used here). `brand-warn` is **kept** because the existing UI relies on amber warning states (e.g., `ExportDatasetModal.tsx:117,127,145`, `CameraConfigForm.tsx:144`, `Badge` `warning` variant).

**Typography tokens (16):** `display-lg`, `heading-1` through `heading-5`, `subtitle`, `body-md`, `body-md-medium`, `body-sm`, `body-sm-medium`, `caption`, `caption-bold`, `micro`, `micro-uppercase`, `button-md`, `code-md`, `code-sm`, `code-inline`. Each declared as a paired triplet — `--text-<name>` (size), `--text-<name>--line-height`, and `--text-<name>--letter-spacing` where the spec specifies negative tracking. **Excluded:** `hero-display` (72px) — pure marketing scale; the dashboard never renders headlines that large.

**Radius scale (7):** `xs` (4px), `sm` (6px), `md` (8px), `lg` (12px), `xl` (16px), `xxl` (24px), `full` (9999px). Declared as `--radius-xs` … `--radius-full`.

**Spacing scale (12):** `xxs` (4px), `xs` (8px), `sm` (12px), `md` (16px), `lg` (20px), `xl` (24px), `xxl` (32px), `xxxl` (40px), `section-sm` (48px), `section` (64px), `section-lg` (96px). Declared as `--spacing-xxs` … `--spacing-section-lg`. **Excluded:** `hero` (120px) — marketing only.

Throughout this spec, references like "padding `xl`" mean `p-xl` (or `px-xl`/`py-xl`) at the call site; never literal `padding-xl`.

### 2. Primitive layer — `frontend/src/components/ui/`

Refactor existing primitives and add five new ones. The current pattern — hand-rolled variant maps composed via `cn()` from `frontend/src/lib/utils.ts` (which uses `tailwind-merge`) — is preserved. The `class-variance-authority` package is in `frontend/package.json` but unused; this refresh does not introduce it.

**Existing primitives (refactored):**

| File | Change |
|---|---|
| `button.tsx` | Variants: `primary` (black pill), `secondary` (transparent + hairline border, pill), `link` (underlined text), `iconCircular` (32×32 round). The `ghost` variant alone is rectangular (`rounded-md`, padding `8px 12px`). Pill variants use padding `10px 20px`, `text-button-md`. The Mintlify `accent` (mint) button variant is intentionally **not** introduced — mint is reserved for state indicators per Goals. Pressed and disabled states per spec. |
| `badge.tsx` | New visual variants from spec: `discount` (mint bg), `required` (error red + micro-uppercase), `type` (surface bg + code-sm), `tag` (brand-tag at 15% alpha). The existing semantic names (`success`, `warning`, `destructive`, `outline`) are kept as the public API and re-mapped onto Mintlify visuals: `success` → mint pill, `warning` → amber pill via `brand-warn`, `destructive` → red pill via `brand-error`, `outline` → hairline outline. |
| `input.tsx` | Height 40px, `rounded-md`, `border-hairline`. Focus → `border-2 border-ink` (black) — the input focus signal does **not** use mint, keeping mint exclusive to state indicators. |
| `select.tsx` | Same height + focus rules as `input`. |
| `card.tsx` | Two variants: `base` (canvas + hairline + `rounded-lg` + `p-xl`) and `feature` (surface + `rounded-lg` + `p-xxl`). |

**New primitives:**

| File | Purpose |
|---|---|
| `pill-tab.tsx` | Pill-style tab nav (`pill-tab` + `pill-tab-active`). For future filter switches and the Recording state pill. |
| `segmented-tab.tsx` | Underline-style tab nav for Inference / Settings sub-screens. |
| `code-inline.tsx` | `<code>` wrapper. Surface bg + Geist Mono + `rounded-xs`. Used for values like robot name, mode, dataset name. |
| `property-row.tsx` | API-doc-style property row. Used in Settings. |
| `sidebar-nav-item.tsx` | Absorbs the NavLink styling out of `Layout.tsx`. Active state uses `bg-surface text-ink text-body-sm-medium`. |

### 3. Layout + page layer

`Layout.tsx` is rewritten to the shell spec below. Each of the six pages and thirteen domain components has its inline class strings replaced by primitives or token-based utilities. No new pages or routes.

## Layout Shell

**Sidebar** — width `240px`, `bg-canvas`, `border-r border-hairline-soft`. Contents top-to-bottom:
1. Brand row: `MimicRec` wordmark (`heading-5`) + session badge.
2. Nav list (flat, no section headers given only four items): `SidebarNavItem` for Datasets / Record / Inference / Settings.
3. Footer: connection status indicator — mint dot + "Connected" or `text-muted` + "Disconnected". Drives off API/WS health where available; if no signal yet, shows a static "Connected" pill that can wire up later.

**Main** — `bg-surface-soft`, scrollable, content `max-w-[1280px]` with `px-xl py-xl` gutters.

**Page header band** — every page renders a consistent header band at top: title (`heading-3`, 28px / 600), right-aligned action group, `border-b border-hairline-soft` divider underneath.

**Session badge mapping:**

| State | Treatment |
|---|---|
| `idle` | Outline pill, `text-steel`, no fill |
| `ready` | mint pill (`bg-brand-green text-primary`), `micro-uppercase` |
| `recording` | red pill (`bg-brand-error text-on-dark`), `micro-uppercase` |
| `review` | tag-blue pill (`bg-brand-tag/15 text-brand-tag`), `micro-uppercase` |

Robot name appears as `caption text-stone` underneath when state ≠ `idle`.

## Per-Page Mapping

### Datasets (`pages/DatasetsPage.tsx`)
- Page header band with title + "New Dataset" `button-primary` (black pill).
- Inline create-form (Name + FPS) **moves into a modal** opened by the New Dataset button.
- Table: header row in `text-steel text-micro-uppercase`; rows use `border-b border-hairline-soft py-md`.
- Action column color resolution:
  - Export (was gray) → `button-link` `text-ink`
  - Annotate (was purple) → `button-link` `text-ink` in rest, `text-brand-tag text-body-sm-medium` while running
  - Delete (was red) → `button-link text-brand-error`
- Annotation progress bar: track `bg-surface`, fill `bg-brand-tag` (purple → tag-blue), completed-text `text-brand-green-deep`.

### Record (`pages/RecordPage.tsx`)
- Page header band; right action: "End Session" `button-secondary` with `text-brand-error`.
- Session info bar (Robot / Mode / Teleop / Dataset / Episodes / Cameras): `card-base` container; each value rendered via `CodeInline` (Geist Mono); labels `caption text-stone`.
- Replaying indicator: replace inline purple pill with `PillTab` `active` mint variant labeled "Replaying".
- Camera previews: keep grid; inner frame is `card-base` (`rounded-lg` + `border-hairline`).
- Idle state: page header + `SessionConfigForm` placed inside a `card-feature`.

### Episodes / Replay
- Episodes table mirrors the Datasets table conventions (same header / row / action treatment).
- Replay screen: vertical stack of `VideoPlayer`, `JointPlot`, `EndEffectorPlot`, `SubtaskTimeline`, `SubtaskAnnotator`. Each block wrapped in `card-base` with `p-xl`. Section titles in `text-heading-5`.

### Settings (`pages/SettingsPage.tsx`)
- Sub-section headings in `text-micro-uppercase text-steel`.
- Each settings entry rendered as a `PropertyRow` (name + optional `badge-type` + description + control).

### Inference (`pages/InferencePage.tsx`)
- Stream / connection status: mint pill when active, `text-stone` when stopped.
- Numerical metrics rendered via `CodeInline` for monospace alignment.

## Color Resolution Table

| Current ad-hoc | New token | Use |
|---|---|---|
| `text-blue-600` (link) | `text-ink` + underline / `button-link` | Dataset name links |
| `bg-purple-100 text-purple-700` | mint pill (`bg-brand-green text-primary`) | Active session indicator |
| `text-purple-600` / `text-purple-800` | `text-brand-tag` (running) / `text-ink` (rest) | Annotate action |
| `text-red-600` / `text-red-800` | `text-brand-error` | Delete action |
| `bg-purple-600` (progress fill) | `bg-brand-tag` | Annotation progress fill |
| `text-green-600` (complete) | `text-brand-green-deep` | Annotation done |
| `bg-gray-50` | `bg-surface-soft` | Page background |
| `bg-gray-100` | `bg-surface` | Info bars / chip backgrounds |
| `bg-gray-200` (progress track) | `bg-surface` | Progress track |
| `border-gray-200` | `border-hairline` | Card / table outer borders |
| `border-gray-100` | `border-hairline-soft` | Row dividers |
| `text-gray-400` | `text-stone` | Captions / sub-labels |
| `text-gray-500` | `text-steel` | Table headers / empty states |
| `text-gray-600` | `text-slate` | Body (lighter) |
| `text-gray-700` | `text-charcoal` | Body |
| `text-gray-800` / `text-gray-900` | `text-ink` | Headings / primary body |
| `bg-blue-50 text-blue-700` (active nav) | `bg-surface text-ink text-body-sm-medium` | Layout active nav item |

## Components Affected

**ui/ (refactored or added):** `button.tsx`, `badge.tsx`, `input.tsx`, `select.tsx`, `card.tsx`, `pill-tab.tsx` (new), `segmented-tab.tsx` (new), `code-inline.tsx` (new), `property-row.tsx` (new), `sidebar-nav-item.tsx` (new).

**Layout:** `components/Layout.tsx` (rewrite).

**Pages (class-string replacement, no logic change):** `pages/DatasetsPage.tsx`, `pages/RecordPage.tsx`, `pages/EpisodesPage.tsx`, `pages/ReplayPage.tsx`, `pages/SettingsPage.tsx`, `pages/InferencePage.tsx`.

**Domain components (13 — class-string replacement, structure preserved):** `CameraConfigForm.tsx`, `CameraPreview.tsx`, `EEMonitor.tsx`, `EndEffectorPlot.tsx`, `EStopButton.tsx`, `ExportDatasetModal.tsx`, `JointPlot.tsx`, `KeyboardTeleop.tsx`, `RecordingControls.tsx`, `SessionConfigForm.tsx`, `SubtaskAnnotator.tsx`, `SubtaskTimeline.tsx`, `VideoPlayer.tsx`. **No prop / interface changes.**

## Verification

- `pnpm build` succeeds with the new `@theme` block.
- Every existing route renders without runtime errors after the refresh.
- A grep pass shows zero remaining occurrences of `text-(blue|purple|red|green|gray)-\d+`, `bg-(blue|purple|red|green|gray)-\d+`, and `border-gray-\d+` in `frontend/src/` outside of `index.css`.
- Manual smoke walk-through in the browser of all six pages: Datasets list + create modal, Record idle + active states, Episodes list, Replay screen, Settings, Inference. Confirm sidebar active state, session badge transitions, and Inter / Geist Mono are loaded.

## Risks & Open Questions

- **Existing semantic Badge variants used elsewhere.** The `Badge` rewrite preserves the `success / warning / destructive / outline` names as aliases of the new visual variants so callers do not break. Behaviour to be verified during implementation.
- **Connection status data source.** No dedicated WS health endpoint exists yet. Implementation will start with a static "Connected" footer pill; wiring to a real signal is a follow-up.
- **Modal infrastructure.** Dataset creation moves to a modal; the project already ships `ExportDatasetModal.tsx`, so we will reuse its modal scaffolding rather than introducing a new dialog primitive.
- **Recharts theming.** `JointPlot` and `EndEffectorPlot` use Recharts. Token application is limited to surrounding chrome; chart palettes will be set via inline color props pulled from CSS variables.
