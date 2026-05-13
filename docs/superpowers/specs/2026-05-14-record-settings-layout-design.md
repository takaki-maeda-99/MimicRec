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

- **Record idle** fits in 1280×800 with no scroll. Two columns: left = "what you're recording" (Mode / Dataset / Task / FPS / Params), right = "what you're recording with" (Robot / Teleop / Mapper / Cameras). Start button anchors the bottom so visual flow runs left-top → right-top → bottom.
- **Hardware-list scalability**: each of Robot / Teleop / Mapper now renders a single row showing the active choice + a `Change ▾` popover that lists all alternatives. Adding a 6th robot config does not grow the column height.
- **In-place editing on Record idle**: every config card (Robot / Teleop / Mapper / Cameras) exposes a `⚙ Edit` affordance that opens the existing config editor modal. Operator never has to leave `/record` to fix a wrong config.
- **Settings Hardware Status above the fold**: Devices (Serial + Cameras) and Calibration collapse into one 3-column unified status block at the top of §04, so calibration is visible at a glance — not buried below Configurations.
- **Settings Configurations as horizontal tabs**: replace the four stacked group sections (`robot` / `teleop` / `mapper` / `cameras`) with a single tab strip. The lone `gopros` group (currently shown only in `useConfigsWithContent`) becomes a fifth tab.
- **Camera assignments no longer rendered as native `<select>` elements**: replace with the same card-row primitive used in the rest of the Record idle screen.

## Non-Goals

- **No new tokens, no new primitives.** Reuse `SectionMark`, `PageHeader`, `ConfigCard`, `Badge`, `SegmentedTab`, `Button` exactly as they are. The only new pieces are (a) a `ConfigPickerRow` composition over `ConfigCard` and (b) extraction of the existing Settings modal into a shared `ConfigEditorModal` component so both pages mount it.
- **No backend changes beyond one new DELETE endpoint** for config-file removal (see Architecture → "Endpoint additions"). All other endpoints (`/api/settings/configs/*` GET/PUT, `/api/settings/devices/*`, `/api/settings/calibration`) stay as-is. No schema changes. No new fields on existing responses.
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
│ [icon] ● so101  _target_: mimicrec.adapters.lerobot…  [⚙] [Change ▾] │
└─────────────────────────────────────────────────────────────┘
                                   ↓ Change ▾ clicked
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

Implementation: a wrapper over `ConfigCard` rendered with `selected={true}` and a `rightSlot` containing the Edit button + Change button. The Change button toggles a positioned `<div role="menu">` (no `<select>`). The "+ new robot…" entry opens an empty `ConfigEditorModal` and uses the existing `PUT /api/settings/configs/<group>/<name>` endpoint with a new name. New-config UX is included because it's a single line cost: the menu already exists for switching, so adding one "+ new" row is essentially free and addresses the "cloned from scratch" flow that operators currently leave the app to do via the filesystem.

When the active group has 0 configs (e.g. the operator has no `mapper` yet), the row renders an empty state: `[no mapper selected] · + new mapper…` instead of the picker.

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

- `⚙ Edit` → opens shared `ConfigEditorModal` (same modal as today).
- `clone` → opens an empty `ConfigEditorModal` pre-filled with this config's content, name field empty, requires the operator to enter a new name. Submits via the existing `PUT /api/settings/configs/<group>/<name>` endpoint.
- `⌫` → confirm dialog → `DELETE /api/settings/configs/<group>/<name>`. **This endpoint does not exist yet.** See "Endpoint additions" below.

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

No new endpoints required for the layout work itself. Two existing endpoints are reused from both pages now instead of one:

- `GET /api/settings/configs/<group>` — already called from Settings and from `useConfigsWithContent` in `SessionConfigForm`. No change.
- `PUT /api/settings/configs/<group>/<name>` — already called from Settings on save. Now also called from `SessionConfigForm` via the shared modal. No change.

#### Endpoint additions (one)

- `DELETE /api/settings/configs/<group>/<name>` — required for the `⌫` action on the Configurations tabs. Returns 204 on success, 404 if not found, 409 if the config is currently selected by an active session (the backend already tracks session state and can refuse). Implementation: mirror the existing `PUT` handler's resolution logic, then `pathlib.Path.unlink()`.

  If this is too much for the layout pass, we can ship the rest of the spec without it and hide the `⌫` button behind a feature flag. Default plan: ship it.

### Modal lifecycle on Record idle

The shared `ConfigEditorModal` mounts at the page level (`RecordPage` idle branch), not inside `SessionConfigForm`. When a `ConfigPickerRow` or `CameraSlotRow` requests an edit, it calls a context-provided `openConfigEditor(group, name, mode)` function. This keeps the modal outside the form's render tree so opening it doesn't unmount the form.

On save, the form's React-Query cache for `useConfigsWithContent(group)` is invalidated so the picker rows pick up the new content. The current selection in the form is **preserved** even if the operator was editing the currently-selected config — the saved version replaces the selected version in the picker, the operator's prior form picks (Mode, Dataset, Task, FPS) stay intact.

## Behaviour in detail

### Record idle — two-column grid

```
┌────────────────────────────────────────────────────────────────────┐
│ §02 Configure session                                              │
├──────────────────────────────────┬─────────────────────────────────┤
│ §02.A RUN SHEET                  │ §02.B HARDWARE                  │
│                                  │                                 │
│ Mode  [Teleop | Hand Teach]      │ ROBOT                           │
│                                  │ [● so101  …  ⚙ Edit | Change ▾] │
│ Dataset  ___________             │                                 │
│ Task     ___________             │ TELEOP                          │
│                                  │ [● so_leader  ⚙ Edit | Change ▾]│
│ FPS  [30]                        │                                 │
│                                  │ MAPPER                          │
│ PARAMETERS                       │ [● so101_joint  ⚙ Edit | Chg ▾] │
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

This is a UI refactor with one schema-touching addition (the new DELETE endpoint). Phasing:

1. **Phase 1 — shared modal extraction.** Pull `ConfigEditorModal` out of `SettingsPage` and verify Settings still works identically. No layout changes. Risk gate: smallest possible diff, easy to back out.
2. **Phase 2 — `SessionConfigForm` rewrite.** Two-column layout, `ConfigPickerRow`, new Camera rows, mount the shared modal. Risk: form behaviour parity. Verified by manual session start + the auto-cycle keybinding path.
3. **Phase 3 — Settings rewrite.** `HardwareStatusBlock`, `ConfigurationsTabs`. Risk: low; mostly composition of existing list renderings.
4. **Phase 4 — DELETE endpoint + `⌫` action.** Backend handler + frontend wiring. Can be merged independently of Phase 3 if needed.

No data migration. No localStorage to clear. The form's `useRecordFormStore` persistence is unchanged.

## Open questions

None that block this spec from being approved as-is. Two flagged for the implementer:

- Whether the `+ new …` flow on Settings should pre-fill the JSON textarea with a minimal `{ "_target_": "..." }` skeleton for the active group, or open empty. Default: open empty. Pre-filled skeletons are a quality-of-life follow-up.
- Whether `ConfigPickerRow`'s popover should be keyboard-navigable (arrow keys + Enter) on day one or be a follow-up. Default: day-one mouse-only; arrow-key support is a polish task.
