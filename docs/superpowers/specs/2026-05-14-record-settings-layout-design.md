# Record idle & Settings — Layout Refresh

**Date:** 2026-05-14
**Status:** Draft (awaiting user review)
**Builds on:** `docs/superpowers/specs/2026-05-13-ui-modernized-lab-notebook-design.md` — preserves the §-numbered Lab Notebook language verbatim; this spec only re-arranges layout.

## Summary

Two screens — the Record idle form (`RecordPage` in `sessionState === "idle"`) and the `SettingsPage` — currently render as 1-column vertical scrolls that cause two recurring frictions:

1. **Operators have to scroll** to reach the Start button on Record, and Configurations/Calibration on Settings.
2. **Operators have to context-switch to Settings** to edit a robot/camera config that turned out to be wrong, then come back.

This spec rearranges both screens to (a) fit in a single viewport at 1280×800, (b) put Hardware status / Calibration above the fold, and (c) let robot, teleop, mapper, and camera configs be edited **in place** from the Record idle screen by reusing the existing Settings modal. No new product features, no API changes, no token changes — purely a layout + a small affordance addition on existing primitives.

## Goals

- **Record idle** fits in 1280×900 with no scroll (matches the existing `useFitsRecordViewport` threshold for the live-capture branch at `RecordPage.tsx:35-48`). 1280×800 is a stretch target only — fall back to the 1-column scroll layout below either dimension. Two columns: left = "what you're recording" (Mode / Dataset / Task / FPS / Params), right = "what you're recording with" (Robot / Teleop / Mapper / Cameras). Start button anchors the bottom so visual flow runs left-top → right-top → bottom. The form root is `h-full min-h-0` with a sticky footer so the Start button never shifts when the conditional Teleop/Mapper rows appear/disappear, and column contents use `truncate` (not wrap) for long dataset / task / config names so a single overflow doesn't push the viewport.
- **Hardware-list scalability with discoverability**: each of Robot / Teleop / Mapper renders a single row showing the active choice + a count chip (`so101 · 3 options`) + a `Change ▾` affordance. The whole row is clickable to open the picker (not just the chevron) so the option list is more discoverable than a tiny menu button. When the group has 0 configs the row inlines a stronger "+ new robot…" affordance instead of a count chip. When the currently-selected config no longer exists (e.g. file deleted between sessions), the row renders an inline error state (`⚠ so101 — missing`) and forces the picker open. Adding a 6th robot config does not grow the column height.
- **In-place editing on Record idle**: every config card (Robot / Teleop / Mapper / Cameras) exposes a `⚙ Edit` affordance that opens the existing config editor modal. Operator never has to leave `/record` to fix a wrong config.
- **Settings Hardware Status above the fold**: Devices (Serial + Cameras) and Calibration collapse into one 3-column unified status block at the top of §04, so calibration is visible at a glance — not buried below Configurations.
- **Settings Configurations as horizontal tabs**: replace the four stacked group sections (`robot` / `teleop` / `mapper` / `cameras`) with a single tab strip. The lone `gopros` group (currently shown only in `useConfigsWithContent`) becomes a fifth tab.
- **Camera assignments no longer rendered as native `<select>` elements**: replace with the same card-row primitive used in the rest of the Record idle screen.

## Non-Goals

- **No new tokens, no new primitives.** Reuse `SectionMark`, `PageHeader`, `ConfigCard`, `Badge`, `SegmentedTab`, `Button` exactly as they are. The only new pieces are (a) a `ConfigPickerRow` composition over `ConfigCard` and (b) extraction of the existing Settings modal into a shared `ConfigEditorModal` component so both pages mount it.
- **No new backend endpoints.** All wired routes already exist in `backend/mimicrec/api/routes/settings.py` — `GET/PUT/POST/DELETE /settings/configs/{group}/{name}`, `/settings/devices/*`, `/settings/calibration`. The DELETE handler is currently a thin file-removal; this spec adds **one behavioural hardening** (409 if the config is currently bound to an active session) but no new route. No schema changes. No new fields on existing responses.
- **No changes to the live-capture `Record` screen** (the `sessionState !== "idle"` branch starting at `frontend/src/pages/RecordPage.tsx:128`). Only the idle branch is rewritten.
- **No responsive / mobile layout.** Both pages assume desktop ≥ 1280px wide. Below that they fall back to a single column (current behavior).
- **No dark mode, no new color tokens, no font changes.**
- **No changes to `gopros` semantics.** It already exists as a group in `useConfigsWithContent` and `SessionConfigForm:34`. The only new exposure is a tab on the Settings Configurations strip.
- **`SessionConfigForm` is rewritten, not refactored in place.** The current file is 360 lines of section-by-section JSX with no clean seams; the two-column rearrangement is dense enough that rewriting reads better than diff-patching. The old file is deleted in the same commit.

## Background

The Lab Notebook refresh (2026-05-13 spec) established a strong visual language but, by design, kept `RecordPage` idle and `SettingsPage` as 1-column vertical stacks. Operating the system for a few weeks since that landing surfaced three concrete frictions, captured in the brainstorm under `.superpowers/brainstorm/2757821-1778703807/`:

- **Friction A (Record scroll)**: at 1280×800 the operator sees Mode + Dataset + Task + the top of Robot. Start is two scrolls down. Validated by the user as item ① in the brainstorm diagnosis.
- **Friction B (Camera assignments visually broken)**: the only place in the app where native browser `<select>` elements are rendered. Inconsistent with the SegmentedTab / ConfigCard idiom used everywhere else. Validated as item ② .
- **Friction C (Round-trip to Settings to fix a config)**: when an operator notices mid-setup that, e.g., the `wrist.yaml` camera has the wrong `device_id`, they have to (1) leave Record, (2) navigate to Settings, (3) scroll past Devices, (4) scroll past Configurations to find the `cameras` group, (5) click Edit, (6) save, (7) navigate back to Record, (8) re-select all their choices because the form may have reset. Validated by the user verbatim: 「レコードスタートのタイミングでロボットやカメラのConfigをEditできるようにもしといてほしい」.
- **Friction D (Settings whitespace + buried Calibration)**: the Devices section is a 2-column grid containing two short bulleted lists in a large bordered box; below it Configurations grows to four nested group sections, and Calibration — arguably the most operationally critical block ("can I even start a session right now?") — is the third and last section, off the bottom of the viewport. Validated as items ④ / ⑤ / ⑥ .

The mockup iteration in the brainstorm (`02-record-layouts.html` → `03-record-A-refined.html` → `04-scaling.html` → `05-settings.html`) walked through two layout decisions and arrived at: **two-column Record idle with a Pop-style hardware picker, three-column Hardware Status at the top of Settings, and tabbed Configurations**.

## Architecture

### Component map

```
RecordPage (idle branch)                  SettingsPage
│                                         │
└─ SessionConfigForm (REWRITE)            ├─ HardwareStatusBlock (NEW composition)
   ├─ RunSheetColumn (NEW section)        │  ├─ SerialList   (extracted)
   │  ├─ ModeField                        │  ├─ CameraList   (extracted)
   │  ├─ DatasetField + TaskField         │  └─ CalibrationList (extracted)
   │  ├─ FpsField                         │
   │  └─ ParametersBlock                  ├─ ConfigurationsTabs (NEW)
   │                                      │  └─ tabs: robot|teleop|mapper|cameras|gopros
   └─ HardwareColumn (NEW section)        │     └─ ConfigRow[] (rightSlot = Edit | Clone | Delete)
      ├─ ConfigPickerRow group="robot"    │
      ├─ ConfigPickerRow group="teleop"   └─ ConfigEditorModal (SHARED — extracted from current
      ├─ ConfigPickerRow group="mapper"      inline modal at SettingsPage:260-305)
      └─ CameraAssignmentsBlock
         └─ CameraSlotRow[] (no native <select>)

ConfigEditorModal (SHARED, in frontend/src/components/)
  Triggered from: RecordPage (any ConfigPickerRow ⚙), CameraSlotRow ⚙, SettingsPage row ⚙
  Mode-switches on group (cameras → CameraConfigForm, else → JSON textarea)
```

### Reused primitives (unchanged)

- `ConfigCard` — already supports `rightSlot`. The `⚙ Edit` button slots in here. The existing `ICON_BY_GROUP` / `ICON_THEME_BY_GROUP` / `getMeta` keep working.
- `SectionMark`, `PageHeader`, `SegmentedTab`/`SegmentedTabBar`, `Button`, `Badge`, `Input` — used verbatim.
- `CameraConfigForm` — already exists at `frontend/src/components/CameraConfigForm.tsx`, currently rendered inline in `SettingsPage`'s modal. Moves into the shared `ConfigEditorModal` without changes.

### New compositions

#### `ConfigPickerRow` (Record idle Hardware column)

One row representing the currently-selected config in a group, plus a `Change ▾` button that opens a popover listing all configs in that group. Each popover row exposes its own `⚙ Edit`.

```
┌─────────────────────────────────────────────────────────────┐
│ ROBOT                                                       │
├─────────────────────────────────────────────────────────────┤
│ [icon] ● so101  _target_: mimicrec.adapters.lerobot…  3 options  [⚙] [▾] │
└─────────────────────────────────────────────────────────────┘
                                   ↓ row clicked (or ▾)
                              ┌──────────────────┐
                              │ SWITCH ROBOT     │
                              ├──────────────────┤
                              │ ● so101      [⚙] │
                              │ ○ rebotarm   [⚙] │
                              │ ○ ur5e       [⚙] │
                              ├──────────────────┤
                              │ + new robot…    │
                              └──────────────────┘
```

Implementation: a wrapper over `ConfigCard` rendered with `selected={true}` and a `rightSlot` carrying both the `⚙ Edit` button and the count chip / `Change ▾` affordance. The whole row's primary click target opens the picker; the `⚙` button is a nested button with `stopPropagation` so it doesn't bubble. The picker is a positioned `<div role="menu">` (no `<select>`), keyboard-navigable from day one (arrow keys move highlight, Enter selects, Esc closes, focus returns to the trigger row). The "+ new robot…" entry at the bottom of the picker opens an empty `ConfigEditorModal` in `mode="new"`, which submits via `POST /api/settings/configs/<group>/<name>` — **not PUT**, so an accidental name collision returns a 409 rather than silently overwriting.

When the active group has 0 configs (e.g. the operator has no `mapper` yet), the row renders a stronger empty state instead of a tiny chevron: `[+ new mapper…]` as a full-width dashed-border button that opens the new-config modal directly. No popover step.

When the currently-selected config name no longer resolves to a file in `useConfigsWithContent(group).data`, the row renders `⚠ <name> — missing · Change ▾` in the error-tone and forces the picker open on mount. The form's start button stays disabled (the existing `!robot || !dataset || !task` guard already covers this, since the resolved config payload becomes `undefined`).

#### `HardwareStatusBlock` (Settings §04.A)

Replaces the current two sections `§04.A Devices` (`SettingsPage:115-171`) and `§04.C Calibration` (`SettingsPage:215-254`) with a single 3-column block:

```
§04.A ─ HARDWARE STATUS ───────────────────────[refresh]──
┌─────────────────┬─────────────────┬─────────────────┐
│ SERIAL · 2      │ CAMERAS · 2     │ CALIBRATION     │
│ ● /dev/ttyACM0  │ ● /dev/video0   │ follower so101  │
│   leader        │   640×480       │   my_arm        │
│ ● /dev/ttyACM1  │ ● /dev/video2   │ leader so101    │
│   follower      │   1920×1080     │   —             │
└─────────────────┴─────────────────┴─────────────────┘
run: python scripts/calibrate_so101.py …
```

- Serial column gets a one-line role annotation per port (`leader` / `follower` / `—`), derived by joining `/api/settings/devices/serial` with the active robot config's `port` field if available. If we can't determine the role, the annotation is omitted — no guess.
- Calibration column lists categories (follower / leader) with the calibrated ID or `—`. The verbatim calibrate command line stays below, but moves from §04.C to under this block.
- Single `[refresh]` button in the section header refreshes all three (Serial + Cameras + Calibration) at once. The three independent `[Refresh]` buttons are removed.

#### `ConfigurationsTabs` (Settings §04.B)

Replaces the current four stacked group sections (`SettingsPage:182-212`). One `SegmentedTabBar` across the top with `robot · 2`, `teleop · 1`, `mapper · 1`, `cameras · 2`, `gopros · 0`. The count chip is `<config[group]>.length` from the existing state.

Active-tab content is a vertical list of `ConfigCard` rows with a 3-action `rightSlot`:

```
[ConfigCard for so101.yaml]                  ⚙ Edit | clone | ⌫
```

- `⚙ Edit` → opens shared `ConfigEditorModal` in `mode="edit"` (same modal as today, name locked).
- `clone` → opens `ConfigEditorModal` in `mode="clone"` pre-filled with this config's content, name field empty, requires the operator to enter a new name. Submits via the existing `POST /api/settings/configs/<group>/<name>` endpoint at `backend/mimicrec/api/routes/settings.py:196` (which returns 409 on collision, the right semantics for "new config").
- `⌫` → confirm dialog → `DELETE /api/settings/configs/<group>/<name>` (already implemented at `backend/mimicrec/api/routes/settings.py:209`). This spec adds a 409 guard to that handler when the config is currently in use by an active session (see "Backend hardening" below). The `⌫` button is **hidden** until that guard ships.

#### `ConfigEditorModal` (shared)

Extracted verbatim from `SettingsPage:260-305`. Same modal shell, same branching on `group === "cameras"` vs JSON textarea. Now lives at `frontend/src/components/ConfigEditorModal.tsx` and is mounted from both `SettingsPage` and `SessionConfigForm`. Props:

```ts
interface ConfigEditorModalProps {
  config: ConfigEntry | null;        // null = closed; non-null = open
  group: ConfigGroup;
  mode: "edit" | "new" | "clone";    // affects whether name is editable
  onClose: () => void;
  onSaved: (saved: ConfigEntry) => void;
}
```

`mode="edit"` keeps current behaviour (name locked, content editable, validation-skipped flash for cameras). `mode="new"` and `mode="clone"` add an editable name field, otherwise identical save path.

### Data flow

All four endpoints already exist in `backend/mimicrec/api/routes/settings.py`:

- `GET /api/settings/configs/<group>` (`:85`) — called from Settings and from `useConfigsWithContent` in `SessionConfigForm`. No change.
- `PUT /api/settings/configs/<group>/<name>` (`:116`) — used by the shared modal in `mode="edit"`. Already handles the camera-validation 409 / busy-skip path; that behaviour is preserved verbatim.
- `POST /api/settings/configs/<group>/<name>` (`:196`) — used by the shared modal in `mode="new"` and `mode="clone"`. Returns 409 on name collision (the file already exists). No change.
- `DELETE /api/settings/configs/<group>/<name>` (`:209`) — used by `⌫` on the Configurations tab rows. **See "Backend hardening" below.**

#### Backend hardening (one change, no new route)

The existing `DELETE` handler at `settings.py:209-217` is a thin file-removal. It needs to learn one new refusal case before the `⌫` button can ship:

- **409 if active session uses it.** The backend already exposes session state (`SessionStateView` / `/api/session/state`). The match check depends on `group`:
  - `group ∈ {robot, teleop, mapper}` → compare `name` directly against `session.<group>`.
  - `group == "cameras"` → match against `image_sources[i].device` where `image_sources[i].kind == "camera"`. The session's `cameras` field is the **slot names**, not the device config names — using it would falsely refuse for the wrong reason. See `backend/mimicrec/api/schemas.py:32-35` for the `ImageSource` shape.
  - `group == "gopros"` → same as cameras but with `kind == "gopro"`.

  When there's a match, refuse with `409 active session uses this config`. Without this guard, deleting a config bound to a live session would leave the writer holding a path that no longer exists on disk, which is a foot-gun the operator does not deserve.

Frontend wiring also has to update the **demo handlers** at `frontend/src/demo/` so the UI keeps working in the browser-only demo build. Otherwise the demo will throw 404s the moment a user clicks `⌫`.

### Modal lifecycle on Record idle

The shared `ConfigEditorModal` mounts at the page level (`RecordPage` idle branch), not inside `SessionConfigForm`. `SessionConfigForm` takes a single `onEditConfig(group, name, mode)` callback prop — no React context. The callback is wired to `useState` in `RecordPage` that toggles the modal's `config` prop. Page-level mounting keeps the modal outside the form's render tree so opening it doesn't unmount the form, but the lift is via plain prop drilling.

On save, the form's React-Query cache for `useConfigsWithContent(group)` is invalidated so the picker rows pick up the new content. The current selection in the form is **preserved** even if the operator was editing the currently-selected config — the saved version replaces the selected version in the picker, the operator's prior form picks (Mode, Dataset, Task, FPS) stay intact.

### Editing during a live session

Settings remains fully editable while a recording session is running — operators sometimes want to prepare the *next* session's config while the current one is mid-flight, and Settings has always allowed this. **However**, every config save / clone / delete in Settings that *would* affect the active session's bound config is annotated inline with `affects next session` (a `Badge variant="warn"` next to the save button). The `⌫` delete path is the only one that hard-refuses (the new 409 guard above). Save / clone on a config currently bound to a live session warns but proceeds — the new content lands on disk and is picked up at the next `start_session`.

The Record idle screen does not show `ConfigPickerRow` or `⚙ Edit` at all while `sessionState !== "idle"` — that whole branch is replaced by the live-capture layout — so the "edit during recording" interaction only happens from Settings.

## Behaviour in detail

### Record idle — two-column grid

```
┌────────────────────────────────────────────────────────────────────┐
│ §02 Configure session                                              │
├──────────────────────────────────┬─────────────────────────────────┤
│ §02.A RUN SHEET                  │ §02.B HARDWARE                  │
│                                  │                                 │
│ Mode  [Teleop | Hand Teach]      │ ROBOT                           │
│                                  │ [● so101 · 3 options       ⚙ ▾] │
│ Dataset  ___________             │                                 │
│ Task     ___________             │ TELEOP                          │
│                                  │ [● so_leader · 1 option    ⚙ ▾] │
│ FPS  [30]                        │                                 │
│                                  │ MAPPER                          │
│ PARAMETERS                       │ [● so101_joint · 1 option  ⚙ ▾] │
│ ☑ Auto cycle                     │                                 │
│   duration 8s · review 3s        │ CAMERAS · 2/2 slots             │
│   F=fail · D=discard · Esc=stop  │ [front  front.yaml   640×480 ⚙] │
│ ☑ Live preview                   │ [wrist  wrist.yaml  1920×1080 ⚙]│
│   turn off to free USB / CPU     │ + add slot…                     │
├──────────────────────────────────┴─────────────────────────────────┤
│ [hint when missing fields]                       [Start session →] │
└────────────────────────────────────────────────────────────────────┘
```

- The grid is `grid-cols-[1fr_1fr]` at ≥1280px, falls back to `grid-cols-1` below.
- The two columns are visually equal width, not weighted. The two-column rule extends only to direct children of the form — the Cameras list inside the Hardware column flows vertically.
- The Teleop and Mapper rows are conditionally rendered only when `mode === "teleop"`, identical to today.
- The footer Start button + missing-field hint replace the current top-of-form footer at `SessionConfigForm:317-332`.

### Camera assignments (no more native `<select>`)

Replaces `SessionConfigForm:184-240`. Each row uses the same row primitive as the Hardware Robot/Teleop/Mapper rows. The slot label (e.g. `observation.images.front`) is a `Badge variant="type"` on the left; the device card occupies the middle; the right slot carries `⚙ Edit` (opens the camera config) and `Change ▾` (switches device). New-slot UX: a single `+ add slot…` row that opens a popover listing unassigned roles, identical pattern to "+ new robot…".

For datasets that have a schema (`useDatasetSchema(...).data?.image_keys`), the slot list is locked to the schema (today's behaviour at `SessionConfigForm:42-47`). For a fresh dataset name, the user can add/remove slots freely. The legacy-slot annotation (`SessionConfigForm:195`) is preserved.

### Settings — three-column status + tabbed configurations

```
┌────────────────────────────────────────────────────────────────────┐
│ §04 Settings                                          [refresh all]│
├────────────────────────────────────────────────────────────────────┤
│ §04.A HARDWARE STATUS                                              │
│ ┌─────────────┬─────────────┬───────────────────────────────────┐  │
│ │ SERIAL · 2  │ CAMERAS · 2 │ CALIBRATION                       │  │
│ │ /dev/ttyAC… │ /dev/video0 │ follower so101 → my_arm           │  │
│ │ /dev/ttyAC… │ /dev/video2 │ leader so101 → —                  │  │
│ └─────────────┴─────────────┴───────────────────────────────────┘  │
│ run: python scripts/calibrate_so101.py …                           │
├────────────────────────────────────────────────────────────────────┤
│ §04.B CONFIGURATIONS                                               │
│ [ robot·2 │ teleop·1 │ mapper·1 │ cameras·2 │ gopros·0 ]  + new … │
│ ┌────────────────────────────────────────────────────────────────┐ │
│ │ [Bot] so101.yaml  _target_: mimicrec.adapters…  ⚙ | clone | ⌫ │ │
│ │ [Bot] rebotarm.yaml  _target_: mimicrec.adapters…  ⚙ | clone …│ │
│ └────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘
```

- Section §04.C `Calibration` is **removed** as a standalone section. Its content moves into the Hardware Status block. The calibrate command snippet stays directly below the status block.
- Section codes after the refactor: §04.A = Hardware Status (replaces today's §04.A Devices), §04.B = Configurations (was §04.B, unchanged code). §04.C is retired.
- `+ new …` button in the tab strip's right slot opens an empty `ConfigEditorModal` for the active group. Group is the active tab.

## Testing

Layout work is hard to assert in unit tests, so testing splits into two:

1. **Component-level tests** for `ConfigPickerRow`, `CameraSlotRow`, `HardwareStatusBlock`, `ConfigurationsTabs`, and `ConfigEditorModal`. Mainly: renders the right rows from given data, fires the right callbacks on click, opens the popover on `Change ▾`, opens the modal on `⚙`. These use the existing React Testing Library setup.

2. **Manual viewport checks** at 1280×800 and 1440×900 for both screens. Acceptance: Record idle's Start button is visible without scroll for both modes (teleop / hand_teach) with up to 4 robot configs and 2 cameras. Settings has Hardware Status fully visible above the fold at 1280×800.

The shared `ConfigEditorModal` extraction is the riskiest change because it touches behaviour. Two specific regression cases to guard:

- **Cameras config save with busy camera** (the validation-skipped path at `SettingsPage:275-283`): the user-facing toast/alert must still fire when `CameraConfigForm` reports `validationSkipped: true`. Test by mocking the form's `onSave` callback.
- **JSON parse error on textarea save** (`SettingsPage:96-106`): the modal must show the error and not close. Test the failure path explicitly.

## Migration

Five phases, each landable independently so regressions can be bisected:

1. **Phase 1 — shared modal extraction.** Pull `ConfigEditorModal` out of `SettingsPage` and verify Settings still works identically. No layout changes. Risk gate: smallest possible diff, easy to back out.
2. **Phase 2a — `SessionConfigForm` layout rewrite, behaviour-preserving.** Two-column grid (Run Sheet | Hardware), Start button moved to bottom footer, English-only labels. Robot/Teleop/Mapper still render as the current grid of `ConfigCard`s inside the right column (no popover yet). Camera assignments rewritten as row primitives (no native `<select>`) but still expose every device statically in a sibling chooser (no popover yet). Goal: prove the no-scroll 1280×900 fit and ship the visual improvement without coupling it to the popover or in-place editing work.
3. **Phase 2b — Popovers + in-place editing.** Replace the Hardware-column grids with `ConfigPickerRow` (selected + count + popover, keyboard-nav). Add `⚙ Edit` buttons on all cards. Wire to the shared `ConfigEditorModal` via the `onEditConfig` prop. This is where the discoverability / scale wins land. Risk: focus management, keyboard handling, the "missing config" state.
4. **Phase 3 — Settings rewrite.** `HardwareStatusBlock` (3-col Devices + Calibration unified), `ConfigurationsTabs` (tab strip + per-tab row list). Add `⚙ Edit` and `clone` actions; do NOT yet show `⌫`. Risk: low; mostly composition of existing list renderings.
5. **Phase 4 — DELETE hardening + `⌫` action.** Backend 409 guard for in-use configs, frontend wiring of the `⌫` button (Settings only — not on Record idle), demo handler update for browser-only demo builds. Independent of Phase 3 — can ship later without blocking earlier phases.

No data migration. No localStorage to clear. The form's `useRecordFormStore` persistence is unchanged.

## Known smaller risks (not blockers)

- **Save / delete error rendering.** Today's `SettingsPage` uses native `window.alert(...)` for failures (lines 51, 67, 81, 105). If config save / delete is becoming a core operational flow, these should switch to an inline error banner or toast in `ConfigEditorModal`. **Default in this spec: keep `alert` for save errors (parity with today), but inline-render the new 409 cases (active-session refusal, name-collision on clone)** because those have actionable next steps the operator can read.
- **Camera vs. gopro name collisions.** The current `slot_assignments` shape (`{slot, device}`) uses only the device name string, so a `cameras/front.yaml` and a `gopros/front.yaml` are indistinguishable. This is a pre-existing latent bug — not introduced by this spec — and is out of scope. Mention to track separately.

## Open questions

None that block this spec. One flagged for the implementer:

- Whether the `+ new …` flow on Settings should pre-fill the JSON textarea with a minimal `{ "_target_": "..." }` skeleton for the active group, or open empty. Default: open empty. Pre-filled skeletons are a quality-of-life follow-up.
