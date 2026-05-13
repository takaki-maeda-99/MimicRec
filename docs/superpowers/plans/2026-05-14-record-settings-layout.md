# Record idle & Settings — Layout Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-arrange the Record idle form and the Settings page into single-viewport layouts, surface in-place config editing on Record idle (no round-trip to Settings), and unify Devices + Calibration into a single Hardware Status block.

**Architecture:** Five phases land independently. Phase 1 extracts the existing inline modal into a shared `ConfigEditorModal` so both pages can mount it. Phase 2a is a behaviour-preserving two-column layout rewrite of `SessionConfigForm`. Phase 2b adds the `ConfigPickerRow` popover primitive plus `⚙ Edit` buttons wired to the shared modal. Phase 3 rewrites `SettingsPage` with a unified Hardware Status block and a tabbed Configurations strip. Phase 4 hardens the existing `DELETE /settings/configs/{group}/{name}` handler with a 409 active-session guard and surfaces the `⌫` button. All backend endpoints already exist (`backend/mimicrec/api/routes/settings.py:85,116,196,209`) — only one new behaviour on DELETE.

**Tech Stack:** React 19 + Vite + Tailwind 4 + react-query (frontend); FastAPI + pytest + httpx (backend). Frontend tests use TypeScript compile (`npm run build`) plus manual viewport checks; backend tests use the existing pytest + `app` fixture pattern at `tests/api/conftest.py:9`. No new frontend test infrastructure is added.

**Spec:** `docs/superpowers/specs/2026-05-14-record-settings-layout-design.md` (commits `0cd1891` → `3a9656b` → `e830bce`).

---

## Files

**Created:**
- `frontend/src/components/ConfigEditorModal.tsx` — extracted shared modal (Phase 1)
- `frontend/src/components/ConfigPickerRow.tsx` — selected-row + popover primitive (Phase 2b)
- `frontend/src/components/CameraSlotRow.tsx` — per-slot row replacing native `<select>` (Phase 2a)
- `frontend/src/components/HardwareStatusBlock.tsx` — Settings §04.A (Phase 3)
- `frontend/src/components/ConfigurationsTabs.tsx` — Settings §04.B (Phase 3)

**Modified:**
- `frontend/src/components/SessionConfigForm.tsx` — full rewrite (Phase 2a, then Phase 2b additions)
- `frontend/src/pages/RecordPage.tsx` — wire `onEditConfig` callback + page-level modal mount (Phase 2b)
- `frontend/src/pages/SettingsPage.tsx` — full rewrite (Phase 3)
- `frontend/src/demo/rest-handlers.ts` — add POST/DELETE handlers (Phase 1, Phase 4)
- `backend/mimicrec/api/routes/settings.py:209-217` — DELETE 409 guard (Phase 4)

**Tests:**
- `tests/api/test_settings_routes.py` — add DELETE 409 active-session tests (Phase 4)

---

## Testing strategy

**Backend:** new tests in `tests/api/test_settings_routes.py` using the existing `app` fixture. Command: `uv run pytest tests/api/test_settings_routes.py -v` from repo root.

**Frontend:** no unit-test infrastructure exists in this repo (`frontend/package.json` has no `test` script and no vitest/RTL deps). Verification is TypeScript compile + manual viewport checks. Each frontend phase ends with:

```bash
cd frontend && npm run build
```

This must complete with **zero TS errors and zero new warnings**. Then manual viewport checks per phase (documented in each phase's final step).

**Demo build:** changes that touch endpoints used by `frontend/src/demo/rest-handlers.ts` must also keep the demo build working:

```bash
cd frontend && npm run build:demo && npm run preview:demo
```

Manually click through the Settings page in the demo to confirm no 404s in DevTools.

---

## Phase 1 — Shared Modal Extraction

Pull the inline modal from `SettingsPage:260-305` into a shared component. Pure refactor — Settings behaviour stays identical. Other phases depend on this.

### Task 1.1: Create `ConfigEditorModal` component

**Files:**
- Create: `frontend/src/components/ConfigEditorModal.tsx`

**Reference:** the current inline implementation lives at `frontend/src/pages/SettingsPage.tsx:260-305`. Copy its behaviour verbatim, then expose it as a component with explicit props.

- [ ] **Step 1: Write the component skeleton**

```tsx
// frontend/src/components/ConfigEditorModal.tsx
import { useState, useEffect } from "react";
import { apiFetch } from "../api/client";
import { Button } from "./ui/button";
import { CameraConfigForm } from "./CameraConfigForm";
import type { ConfigGroup } from "./ConfigCard";

export interface ConfigEntry {
  name: string;
  group: ConfigGroup;
  content: Record<string, unknown>;
}

export type ConfigEditorMode = "edit" | "new" | "clone";

interface Props {
  config: ConfigEntry | null;        // null = closed
  mode: ConfigEditorMode;
  onClose: () => void;
  onSaved: (saved: ConfigEntry) => void;
}

export function ConfigEditorModal({ config, mode, onClose, onSaved }: Props) {
  const [editJson, setEditJson] = useState("");
  const [editName, setEditName] = useState("");

  useEffect(() => {
    if (!config) return;
    setEditJson(JSON.stringify(config.content, null, 2));
    setEditName(mode === "clone" || mode === "new" ? "" : config.name);
  }, [config, mode]);

  if (!config) return null;

  const isCamera =
    config.group === "cameras"
    && (config.content as Record<string, unknown>)._target_
        === "mimicrec.cameras.opencv_camera.OpenCVCamera";

  const handleSave = async () => {
    try {
      const content = JSON.parse(editJson);
      const name = (mode === "edit") ? config.name : editName;
      if (!name) {
        alert("Name is required");
        return;
      }
      const method = mode === "edit" ? "PUT" : "POST";
      await apiFetch(`/api/settings/configs/${config.group}/${name}`, {
        method,
        body: JSON.stringify({ content }),
      });
      onSaved({ ...config, name, content });
      onClose();
    } catch (e) {
      alert(`Save failed: ${e}`);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-canvas-dark/40"
      onClick={onClose}
    >
      <div
        className="bg-canvas rounded-lg border border-hairline p-xl w-[600px] max-h-[80vh] overflow-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {isCamera && mode === "edit" ? (
          <CameraConfigForm
            name={config.name}
            currentContent={config.content as Record<string, unknown>}
            onSave={(validationSkipped) => {
              onClose();
              if (validationSkipped) {
                alert(
                  "Saved. Camera was busy so the configured parameters " +
                  "will be validated when the next session starts.",
                );
              }
              onSaved(config);
            }}
            onCancel={onClose}
          />
        ) : (
          <>
            <h3 className="text-heading-5 text-ink mb-xs">
              {mode === "edit" && `Edit ${config.group}/${config.name}`}
              {mode === "new" && `New ${config.group}`}
              {mode === "clone" && `Clone ${config.group}/${config.name}`}
            </h3>
            {(mode === "new" || mode === "clone") && (
              <input
                type="text"
                placeholder="config name (without .yaml)"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                className="w-full border border-hairline rounded px-3 py-2 mb-md font-mono text-code-sm"
              />
            )}
            <textarea
              className="w-full h-64 rounded-md border border-hairline bg-canvas p-md font-mono text-code-sm text-charcoal mb-md focus:outline-none focus:border-2 focus:border-ink"
              value={editJson}
              onChange={(e) => setEditJson(e.target.value)}
            />
            <div className="flex justify-end gap-xs">
              <Button variant="secondary" onClick={onClose}>Cancel</Button>
              <Button onClick={handleSave}>Save</Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npm run build
```

Expected: build succeeds. If TS errors point to missing `ConfigGroup` import path, verify `frontend/src/components/ConfigCard.tsx:7` exports it (it does).

### Task 1.2: Replace inline modal in `SettingsPage`

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx` — replace lines 259-305 (modal block) and adjust state/imports.

- [ ] **Step 1: Add the import and refactor state**

At the top of `SettingsPage.tsx`, add:

```tsx
import { ConfigEditorModal, type ConfigEntry as ModalConfigEntry } from "../components/ConfigEditorModal";
```

The page's local `ConfigEntry` interface (lines 22-26) duplicates the modal's `ConfigEntry`. Keep the page's local type but ensure the `group: string` field assigns to the modal's `group: ConfigGroup` — narrow at the call site.

- [ ] **Step 2: Replace the inline modal**

Find lines 259-305 (`{editingConfig && (...)}`) and replace with:

```tsx
<ConfigEditorModal
  config={
    editingConfig
      ? { ...editingConfig, group: editingConfig.group as ConfigGroup }
      : null
  }
  mode="edit"
  onClose={() => setEditingConfig(null)}
  onSaved={() => {
    setEditingConfig(null);
    loadConfigs();
  }}
/>
```

Remove `handleSaveConfig` (lines 94-107) and the `editJson` state (line 35) — they're now inside the modal.

- [ ] **Step 3: Type-check**

```bash
cd frontend && npm run build
```

Expected: build succeeds. If there's a TS error about `ConfigGroup`, import it from `../components/ConfigCard` (note: relative path from `pages/`, not `./`).

- [ ] **Step 4: Manual smoke test**

```bash
cd frontend && npm run dev
```

Open `http://localhost:5173/settings`, click `⚙ Edit` on any robot config → modal opens → modify JSON → Save → modal closes → list refreshes. Click `⚙ Edit` on a camera config → `CameraConfigForm` renders (not the JSON textarea). Both branches must work identically to before.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ConfigEditorModal.tsx frontend/src/pages/SettingsPage.tsx
git commit -m "refactor(settings): extract inline config modal into ConfigEditorModal"
```

### Task 1.3: Add demo handlers for POST (clone path)

**Files:**
- Modify: `frontend/src/demo/rest-handlers.ts:222-241`

The demo currently stubs PUT only (line 240). Phase 2b/3 will exercise POST for new/clone. Add a stub now so the modal save path doesn't 404 in demo.

- [ ] **Step 1: Add POST handler**

In `frontend/src/demo/rest-handlers.ts`, find the `stubHandlers` array (line 222) and add:

```ts
http.post("/api/settings/configs/:group/:name", demoUnsupported),
```

near line 240 next to the existing PUT stub.

- [ ] **Step 2: Type-check**

```bash
cd frontend && npm run build:demo
```

Expected: demo build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/demo/rest-handlers.ts
git commit -m "demo: stub POST /api/settings/configs/:group/:name as unsupported"
```

---

## Phase 2a — `SessionConfigForm` Layout Rewrite (behaviour-preserving)

Two-column grid, Start at the bottom, Camera assignments stop using native `<select>`. Robot/Teleop/Mapper still render as the current grid of `ConfigCard`s — no popover yet. Goal: prove the 1280×900 no-scroll fit.

### Task 2a.1: Build the two-column shell

**Files:**
- Modify: `frontend/src/components/SessionConfigForm.tsx` — full rewrite of the JSX. Keep the imports and the data-loading hooks; rewrite from the `return (...)` block.

- [ ] **Step 1: Replace the form body**

Replace lines 81-336 (everything from `return (` to the end of the component) with:

```tsx
  return (
    <form
      className="flex flex-col h-full min-h-0"
      onSubmit={(e) => { e.preventDefault(); handleStart(); }}
    >
      {/* Two-column body */}
      <div className="flex-1 min-h-0 overflow-auto px-xl py-lg">
        <div className="max-w-[1280px] mx-auto grid grid-cols-1 xl:grid-cols-2 gap-2xl">

          {/* §02.A — RUN SHEET (left column) */}
          <section className="flex flex-col gap-md min-w-0">
            <header className="flex items-baseline gap-md">
              <SectionMark code="§02.A" name="Run sheet" />
              <span className="flex-1 h-px bg-hairline-soft" />
            </header>

            <Field label="Mode">
              <SegmentedTabBar>
                <SegmentedTab active={mode === "teleop"} onClick={() => form.set({ mode: "teleop" })}>
                  Teleop
                </SegmentedTab>
                <SegmentedTab active={mode === "hand_teach"} onClick={() => form.set({ mode: "hand_teach" })}>
                  Hand Teach
                </SegmentedTab>
              </SegmentedTabBar>
            </Field>

            <Field label="Dataset">
              <Input
                list="existing-datasets"
                value={dataset}
                onChange={e => form.set({ dataset: e.target.value })}
                placeholder="my_dataset"
                className="truncate"
              />
              <datalist id="existing-datasets">
                {datasets?.map(d => (
                  <option key={d.name} value={d.name}>{d.num_episodes} episodes</option>
                ))}
              </datalist>
            </Field>

            <Field label="Task">
              <Input
                list="existing-tasks"
                value={task}
                onChange={e => form.set({ task: e.target.value })}
                placeholder="pick"
                className="truncate"
              />
              <datalist id="existing-tasks">
                {tasks?.map(t => (
                  <option key={t.task_index} value={t.task}>{t.instruction ?? ""}</option>
                ))}
              </datalist>
            </Field>

            <Field label="FPS">
              <Input
                type="number"
                className="w-24"
                value={fps}
                onChange={e => form.set({ fps: Number(e.target.value) })}
              />
            </Field>

            <Field label="Parameters">
              <div className="border border-hairline rounded-md p-md gap-sm flex flex-col bg-surface-soft">
                <label className="flex items-center gap-2 text-body-sm-medium text-charcoal">
                  <input
                    type="checkbox"
                    checked={form.autoCycle}
                    onChange={e => form.set({ autoCycle: e.target.checked })}
                  />
                  Auto cycle <span className="text-caption text-steel">— record → save → next</span>
                </label>
                {form.autoCycle && (
                  <>
                    <div className="flex gap-3 text-body-sm pl-6">
                      <label className="flex items-center gap-1">
                        Duration
                        <Input
                          type="number"
                          className="w-20"
                          value={form.autoDurationSec}
                          onChange={e => form.set({ autoDurationSec: Math.max(1, Number(e.target.value) || 0) })}
                        />
                        <span className="text-steel">s</span>
                      </label>
                      <label className="flex items-center gap-1">
                        Review
                        <Input
                          type="number"
                          className="w-20"
                          value={form.autoReviewSec}
                          onChange={e => form.set({ autoReviewSec: Math.max(0, Number(e.target.value) || 0) })}
                        />
                        <span className="text-steel">s</span>
                      </label>
                    </div>
                    <p className="text-caption text-steel pl-6">
                      F = fail · D = discard · Esc = stop
                    </p>
                  </>
                )}
                <label className="flex items-center gap-2 text-body-sm-medium text-charcoal">
                  <input
                    type="checkbox"
                    checked={previewEnabled}
                    onChange={e => form.set({ previewEnabled: e.target.checked })}
                  />
                  Live preview <span className="text-caption text-steel">— turn off to free USB / CPU</span>
                </label>
              </div>
            </Field>
          </section>

          {/* §02.B — HARDWARE (right column) */}
          <section className="flex flex-col gap-md min-w-0">
            <header className="flex items-baseline gap-md">
              <SectionMark code="§02.B" name="Hardware" />
              <span className="flex-1 h-px bg-hairline-soft" />
            </header>

            <Field label="Robot">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {robots?.map(r => (
                  <ConfigCard
                    key={r.name}
                    config={r}
                    group="robot"
                    selected={robot === r.name}
                    onClick={() => form.set({ robot: r.name })}
                  />
                ))}
              </div>
            </Field>

            {mode === "teleop" && (
              <>
                <Field label="Teleop">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {teleops?.map(t => (
                      <ConfigCard
                        key={t.name}
                        config={t}
                        group="teleop"
                        selected={teleop === t.name}
                        onClick={() => form.set({ teleop: t.name })}
                      />
                    ))}
                  </div>
                </Field>
                <Field label="Mapper">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {mappers?.map(m => (
                      <ConfigCard
                        key={m.name}
                        config={m}
                        group="mapper"
                        selected={mapper === m.name}
                        onClick={() => form.set({ mapper: m.name })}
                      />
                    ))}
                  </div>
                </Field>
              </>
            )}

            <Field label="Cameras">
              <div className="flex flex-col gap-2">
                {allSlotsToShow.map(({ slot, device, locked }) => (
                  <CameraSlotRow
                    key={slot}
                    slot={slot}
                    device={device}
                    locked={locked}
                    legacy={legacySlots.includes(slot)}
                    deviceOptions={deviceOptions}
                    usedDevices={usedDevices}
                    onChange={(d) => setSlotDevice(slot, d)}
                    onRemove={!locked ? () => removeSlot(slot) : undefined}
                  />
                ))}
                {!datasetExists && availableRoles.length > 0 && (
                  <AddSlotButton roles={availableRoles} onAdd={addSlot} />
                )}
              </div>
            </Field>
          </section>

        </div>
      </div>

      {/* Error block */}
      {(startSession.isError || (!startSession.isError && lastError)) && (
        <div className="px-xl pb-2">
          {startSession.isError && (
            <pre className="text-brand-error text-sm whitespace-pre-wrap font-mono bg-brand-error/10 border border-brand-error/30 rounded-md p-3">
              {(startSession.error as Error).message}
            </pre>
          )}
          {!startSession.isError && lastError && (
            <div className="bg-brand-error/10 border border-brand-error/30 rounded-md p-3 space-y-1">
              <div className="text-brand-error text-sm font-semibold">
                Previous session ended with an error: {lastError.error}
              </div>
              <pre className="text-brand-error text-sm whitespace-pre-wrap font-mono">
                {lastError.message}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Footer — Start button anchored at bottom */}
      <div className="flex-shrink-0 border-t border-hairline bg-canvas px-xl py-md flex items-center justify-end gap-md">
        {(!robot || !dataset || !task) && (
          <span className="text-caption text-steel">
            Pick a robot, dataset, and task to enable start.
          </span>
        )}
        <Button
          variant="primary"
          size="lg"
          type="submit"
          disabled={startSession.isPending || !robot || !dataset || !task}
        >
          {startSession.isPending ? "Starting..." : "Start session →"}
        </Button>
      </div>
    </form>
  );
}

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
        {label}
      </label>
      {children}
      {hint && <div className="text-caption text-steel">{hint}</div>}
    </div>
  );
}
```

This references `CameraSlotRow` and `AddSlotButton` — those are created in Task 2a.2. The build will fail until they exist.

### Task 2a.2: Create `CameraSlotRow` and `AddSlotButton`

**Files:**
- Create: `frontend/src/components/CameraSlotRow.tsx`

- [ ] **Step 1: Write the component**

```tsx
// frontend/src/components/CameraSlotRow.tsx
import { Badge } from "./ui/badge";

export interface DeviceOption {
  name: string;
  kind: "camera" | "gopro";
}

interface CameraSlotRowProps {
  slot: string;
  device: string;
  locked: boolean;
  legacy: boolean;
  deviceOptions: DeviceOption[];
  usedDevices: Set<string>;
  onChange: (device: string) => void;
  onRemove?: () => void;
}

export function CameraSlotRow({
  slot,
  device,
  locked,
  legacy,
  deviceOptions,
  usedDevices,
  onChange,
  onRemove,
}: CameraSlotRowProps) {
  return (
    <div className="flex items-center gap-sm rounded-md border border-hairline bg-canvas px-md py-2">
      <Badge variant="type" className="font-mono">
        {slot}{legacy && " (legacy)"}
      </Badge>
      <span className="flex-1" />
      <select
        value={device}
        disabled={locked && !device}
        onChange={e => onChange(e.target.value)}
        className="border border-hairline rounded px-2 py-1 text-body-sm bg-canvas min-w-[200px]"
      >
        <option value="">— none —</option>
        {deviceOptions.map(opt => (
          <option
            key={opt.name}
            value={opt.name}
            disabled={usedDevices.has(opt.name) && device !== opt.name}
          >
            {opt.name} ({opt.kind}){usedDevices.has(opt.name) && device !== opt.name ? " (in use)" : ""}
          </option>
        ))}
      </select>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="text-stone hover:text-brand-error px-2"
          aria-label={`Remove ${slot}`}
        >
          ✕
        </button>
      )}
    </div>
  );
}

interface AddSlotButtonProps {
  roles: string[];
  onAdd: (role: string) => void;
}

export function AddSlotButton({ roles, onAdd }: AddSlotButtonProps) {
  return (
    <select
      value=""
      className="border border-dashed border-hairline rounded-md px-md py-2 text-body-sm bg-canvas text-stone"
      onChange={e => { if (e.target.value) onAdd(e.target.value); }}
    >
      <option value="">+ add slot…</option>
      {roles.map(r => (
        <option key={r} value={r}>{r}</option>
      ))}
    </select>
  );
}
```

Note: Phase 2a deliberately keeps a `<select>` here — Phase 2b replaces it with the popover row primitive. Phase 2a is *layout only*.

- [ ] **Step 2: Import in `SessionConfigForm`**

At the top of `SessionConfigForm.tsx`:

```tsx
import { CameraSlotRow, AddSlotButton } from "./CameraSlotRow";
```

- [ ] **Step 3: Type-check**

```bash
cd frontend && npm run build
```

Expected: build succeeds.

### Task 2a.3: Manual viewport check

- [ ] **Step 1: Run the dev server**

```bash
cd frontend && npm run dev
```

- [ ] **Step 2: Resize browser to 1280×900**

Use the browser devtools "Responsive" preset or `cmd/ctrl + opt/alt + I → device toolbar` to lock viewport. Navigate to `/record` (session must be idle).

- [ ] **Step 3: Verify acceptance criteria**

For `mode = teleop` with all of robot / teleop / mapper / 2 cameras selected:
- Start button is fully visible without scrolling
- Both columns render side-by-side
- Long dataset names truncate, do not wrap

For `mode = hand_teach`:
- Teleop and Mapper sections are hidden
- Start button stays anchored at the bottom (no jump)

For viewport at 1279×900 (below the breakpoint):
- Layout falls back to single column with vertical scroll
- This is the expected fallback behaviour

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/SessionConfigForm.tsx frontend/src/components/CameraSlotRow.tsx
git commit -m "feat(record): rewrite SessionConfigForm as two-column run sheet + hardware layout

Start anchored at the bottom; English-only labels; Camera assignments
extracted into CameraSlotRow / AddSlotButton primitives. Native <select>
is preserved for now (Phase 2b replaces it with the popover pattern).
Behaviour-preserving: no new endpoints, no new state."
```

---

## Phase 2b — Popovers + In-Place Editing

Replace the Hardware-column grids with `ConfigPickerRow` (selected + count + popover, keyboard-nav). Add `⚙ Edit` buttons on all picker rows + camera rows. Wire to the shared `ConfigEditorModal` via an `onEditConfig` prop.

### Task 2b.1: Create `ConfigPickerRow`

**Files:**
- Create: `frontend/src/components/ConfigPickerRow.tsx`

- [ ] **Step 1: Write the component**

```tsx
// frontend/src/components/ConfigPickerRow.tsx
import { useEffect, useRef, useState } from "react";
import { ChevronDown, Settings } from "lucide-react";
import type { ConfigGroup, ConfigCardEntry } from "./ConfigCard";
import { cn } from "../lib/utils";

interface ConfigPickerRowProps {
  group: ConfigGroup;
  selected: string;
  configs: ConfigCardEntry[];
  onSelect: (name: string) => void;
  onEdit: (name: string) => void;
  onNew: () => void;
}

export function ConfigPickerRow({
  group, selected, configs, onSelect, onEdit, onNew,
}: ConfigPickerRowProps) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const triggerRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const selectedConfig = configs.find(c => c.name === selected);
  const missing = selected && !selectedConfig;
  const count = configs.length;

  // Force open if selected config is missing (operator must re-pick).
  useEffect(() => {
    if (missing) setOpen(true);
  }, [missing]);

  // Force open if no configs exist (empty state needs the "+ new" affordance).
  const isEmpty = count === 0;

  // Close on outside click and Esc.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)
          && !triggerRef.current?.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlight(h => Math.min(h + 1, configs.length - 1));
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlight(h => Math.max(h - 1, 0));
      }
      if (e.key === "Enter") {
        e.preventDefault();
        const item = configs[highlight];
        if (item) {
          onSelect(item.name);
          setOpen(false);
          triggerRef.current?.focus();
        }
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, configs, highlight, onSelect]);

  // Empty state — no popover, full-width "+ new" button.
  if (isEmpty) {
    return (
      <button
        type="button"
        onClick={onNew}
        className="w-full rounded-md border-2 border-dashed border-hairline bg-canvas px-md py-sm text-stone hover:border-stone hover:text-ink transition-colors"
      >
        + new {group}…
      </button>
    );
  }

  // The trigger row contains nested interactive elements (⚙ Edit button).
  // Nesting <button> inside <button> is invalid HTML, so the row is a
  // <div role="button"> and the ⚙ Edit is a real <button> sibling.
  const onRowKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setOpen(o => !o);
    }
  };

  return (
    <div className="relative">
      <div
        ref={triggerRef}
        role="button"
        tabIndex={0}
        onClick={() => setOpen(o => !o)}
        onKeyDown={onRowKey}
        className={cn(
          "w-full rounded-md border-2 bg-canvas px-md py-sm transition-colors text-left",
          "flex items-center gap-sm cursor-pointer focus:outline-none focus:ring-2 focus:ring-ink",
          missing ? "border-brand-error/60" : "border-ink",
        )}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {missing ? (
          <span className="text-brand-error font-mono text-body-sm-medium">⚠ {selected} — missing</span>
        ) : (
          <>
            <span className="w-2 h-2 rounded-full bg-ink" aria-hidden />
            <span className="text-body-sm-medium text-ink truncate min-w-0 flex-1">
              {selected}
            </span>
            <span className="text-caption text-steel font-mono">
              {count} option{count !== 1 ? "s" : ""}
            </span>
          </>
        )}
        {selectedConfig && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onEdit(selected); }}
            className="text-stone hover:text-ink px-1"
            aria-label={`Edit ${selected}`}
          >
            <Settings className="w-4 h-4" />
          </button>
        )}
        <ChevronDown className="w-4 h-4 text-stone" />
      </div>

      {open && (
        <div
          ref={menuRef}
          role="menu"
          className="absolute z-40 mt-1 w-full bg-canvas border border-hairline rounded-md shadow-lg p-1 max-h-[240px] overflow-auto"
        >
          <div className="px-2 py-1 text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
            switch {group}
          </div>
          {configs.map((c, i) => (
            <div
              key={c.name}
              role="menuitem"
              className={cn(
                "flex items-center gap-2 px-2 py-1.5 rounded-sm cursor-pointer",
                i === highlight ? "bg-surface" : "",
                c.name === selected ? "border-l-2 border-ink" : "",
              )}
              onMouseEnter={() => setHighlight(i)}
              onClick={() => { onSelect(c.name); setOpen(false); }}
            >
              <span className="w-2 h-2 rounded-full" style={{ background: c.name === selected ? "var(--color-ink)" : "transparent", border: c.name === selected ? "none" : "1px solid var(--color-hairline)" }} />
              <span className="flex-1 text-body-sm text-ink truncate">{c.name}</span>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onEdit(c.name); setOpen(false); }}
                className="text-stone hover:text-ink px-1"
                aria-label={`Edit ${c.name}`}
              >
                <Settings className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
          <div className="border-t border-hairline-soft mt-1 pt-1">
            <button
              type="button"
              onClick={() => { onNew(); setOpen(false); }}
              className="w-full text-left px-2 py-1.5 rounded-sm text-stone hover:bg-surface hover:text-ink"
            >
              + new {group}…
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
```

Note: this references `ConfigCard` only for its types (`ConfigGroup`, `ConfigCardEntry`). The visual is a custom row, not a `ConfigCard` instance.

- [ ] **Step 2: Type-check**

```bash
cd frontend && npm run build
```

### Task 2b.2: Wire `RecordPage` to mount the shared modal

**Files:**
- Modify: `frontend/src/pages/RecordPage.tsx` — add modal state in the idle branch.

- [ ] **Step 1: Add the modal mount to the idle branch**

Find the idle branch at `RecordPage.tsx:104-114`:

```tsx
  if (sessionState === "idle") {
    return (
      <>
        <PageHeader code="§02" title="Configure session" />
        <div className="flex-1 overflow-auto px-xl py-xl">
          <SessionConfigForm onStarted={() => {}} />
        </div>
      </>
    );
  }
```

Replace with:

```tsx
  if (sessionState === "idle") {
    return <RecordIdle />;
  }
```

Add the `RecordIdle` component near the bottom of the file (after `XYPlot`):

```tsx
function RecordIdle() {
  const [editing, setEditing] = useState<{
    config: ModalConfigEntry;
    mode: ConfigEditorMode;
  } | null>(null);
  const queryClient = useQueryClient();

  const openEditor = (group: ConfigGroup, name: string, mode: ConfigEditorMode) => {
    // We need the current content to pre-fill the modal. Re-fetch from the
    // react-query cache populated by useConfigsWithContent. The key shape
    // is defined at frontend/src/api/queries.ts:107 as
    // ["configs-with-content", group] — not ["configs", group, true].
    const cached = queryClient.getQueryData<{ name: string; content: Record<string, unknown> }[]>(
      ["configs-with-content", group]
    );
    const found = cached?.find(c => c.name === name);
    const content = found?.content ?? {};
    setEditing({ config: { name, group, content }, mode });
  };

  return (
    <>
      <PageHeader code="§02" title="Configure session" />
      <div className="flex-1 min-h-0 flex flex-col">
        <SessionConfigForm
          onStarted={() => {}}
          onEditConfig={openEditor}
        />
      </div>
      <ConfigEditorModal
        config={editing?.config ?? null}
        mode={editing?.mode ?? "edit"}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          // Invalidate BOTH cache keys: useConfigsWithContent feeds the form,
          // useConfigs feeds the schema lookup. See queries.ts:97,107.
          queryClient.invalidateQueries({ queryKey: ["configs-with-content"] });
          queryClient.invalidateQueries({ queryKey: ["configs"] });
        }}
      />
    </>
  );
}
```

Imports to add at the top of `RecordPage.tsx`:

```tsx
import { useQueryClient } from "@tanstack/react-query";
import { ConfigEditorModal, type ConfigEntry as ModalConfigEntry, type ConfigEditorMode } from "../components/ConfigEditorModal";
import type { ConfigGroup } from "../components/ConfigCard";
```

The `["configs", group, true]` key shape comes from `useConfigsWithContent` — verify the actual key by reading `frontend/src/api/queries.ts` and adjusting if different.

- [ ] **Step 2: Verify the react-query key shape**

```bash
grep -n "configs.*queryKey\|queryKey.*configs" frontend/src/api/queries.ts
```

If the key is `["configs", group]` not `["configs", group, true]`, update the `getQueryData` call accordingly. `true` represents the `withContent` flag if it exists.

- [ ] **Step 3: Type-check**

```bash
cd frontend && npm run build
```

The build will fail because `SessionConfigForm` doesn't accept `onEditConfig` yet. Task 2b.3 adds it.

### Task 2b.3: Add `onEditConfig` prop and wire `ConfigPickerRow`

**Files:**
- Modify: `frontend/src/components/SessionConfigForm.tsx`

- [ ] **Step 1: Update the Props interface**

Find the `Props` interface near the top:

```tsx
interface Props {
  onStarted: () => void;
  onEditConfig?: (group: ConfigGroup, name: string, mode: ConfigEditorMode) => void;
}
```

Add the imports at the top:

```tsx
import type { ConfigEditorMode } from "./ConfigEditorModal";
import { ConfigPickerRow } from "./ConfigPickerRow";
```

The component signature becomes `({ onStarted, onEditConfig }: Props)`.

- [ ] **Step 2: Replace Robot, Teleop, Mapper grids with `ConfigPickerRow`**

In the Hardware column, replace each `<Field>` block for Robot / Teleop / Mapper. For Robot:

```tsx
<Field label="Robot">
  <ConfigPickerRow
    group="robot"
    selected={robot}
    configs={robots ?? []}
    onSelect={(name) => form.set({ robot: name })}
    onEdit={(name) => onEditConfig?.("robot", name, "edit")}
    onNew={() => onEditConfig?.("robot", "", "new")}
  />
</Field>
```

Identical pattern for Teleop (`group="teleop"`) and Mapper (`group="mapper"`). Both stay wrapped in the `{mode === "teleop" && ...}` conditional.

- [ ] **Step 3: Add `⚙ Edit` to `CameraSlotRow`**

In `frontend/src/components/CameraSlotRow.tsx`, add an `onEdit?: (deviceName: string) => void` prop and render a button when set:

```tsx
{onEdit && device && (
  <button
    type="button"
    onClick={() => onEdit(device)}
    className="text-stone hover:text-ink px-1"
    aria-label={`Edit ${device}`}
  >
    <Settings className="w-4 h-4" />
  </button>
)}
```

Add the `Settings` import from `lucide-react`.

In `SessionConfigForm`'s Cameras Field, pass `onEdit`:

```tsx
<CameraSlotRow
  key={slot}
  slot={slot}
  device={device}
  locked={locked}
  legacy={legacy}
  deviceOptions={deviceOptions}
  usedDevices={usedDevices}
  onChange={(d) => setSlotDevice(slot, d)}
  onRemove={!locked ? () => removeSlot(slot) : undefined}
  onEdit={(d) => {
    const kind = deviceOptions.find(o => o.name === d)?.kind ?? "camera";
    onEditConfig?.(kind === "gopro" ? "gopros" : "cameras", d, "edit");
  }}
/>
```

- [ ] **Step 4: Type-check**

```bash
cd frontend && npm run build
```

Expected: build succeeds.

- [ ] **Step 5: Manual smoke test**

```bash
cd frontend && npm run dev
```

At `http://localhost:5173/record` (idle):
- Click Robot picker row → popover opens listing all robots.
- Press `↓` then `Enter` → selection changes, popover closes.
- Press `Esc` to close without selecting.
- Click `⚙` on the selected row → modal opens with that robot's content. Save → modal closes → picker reflects updated content if name changed.
- Click `+ new robot…` in the popover → modal opens in `mode="new"` with empty name field.
- Click `⚙` next to a camera slot → modal opens with that camera's content.
- Verify a missing-config error state by renaming a YAML on disk (e.g. `mv configs/robot/so101.yaml configs/robot/so101.bak.yaml`), refreshing, picking `so101` from the form (zustand persistence): the picker should render `⚠ so101 — missing` and force-open the menu. Restore the file after.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ConfigPickerRow.tsx frontend/src/components/CameraSlotRow.tsx frontend/src/components/SessionConfigForm.tsx frontend/src/pages/RecordPage.tsx
git commit -m "feat(record): add ConfigPickerRow with in-place editing on Record idle

Robot/Teleop/Mapper now render as single-row pickers with keyboard-nav
popovers; Camera slots gain a ⚙ Edit button that mounts the shared
ConfigEditorModal at the page level via onEditConfig prop. Missing
configs render an inline error state and force the picker open."
```

---

## Phase 3 — Settings Rewrite

`HardwareStatusBlock` (Devices + Calibration unified), `ConfigurationsTabs` (SegmentedTab strip + per-tab row list). Add `⚙ Edit` and `clone` actions on tab rows. The `⌫` button is **deferred to Phase 4**.

### Task 3.1: Create `HardwareStatusBlock`

**Files:**
- Create: `frontend/src/components/HardwareStatusBlock.tsx`

- [ ] **Step 1: Write the component**

```tsx
// frontend/src/components/HardwareStatusBlock.tsx
import { Button } from "./ui/button";
import { SectionMark } from "./ui/section-mark";

interface SerialDevice { port: string; available: boolean }
interface CameraDevice {
  path: string; device_id: number; available: boolean; width: number; height: number;
}

interface Props {
  serial: SerialDevice[];
  cameras: CameraDevice[];
  calibrations: Record<string, Record<string, string[]>>;
  refreshing: boolean;
  onRefresh: () => void;
}

export function HardwareStatusBlock({
  serial, cameras, calibrations, refreshing, onRefresh,
}: Props) {
  return (
    <section className="flex flex-col gap-md">
      <header className="flex items-baseline gap-md">
        <SectionMark code="§04.A" name="Hardware status" />
        <span className="flex-1 h-px bg-hairline-soft" />
        <Button variant="secondary" size="sm" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh"}
        </Button>
      </header>
      <div className="rounded-md border border-hairline bg-canvas p-md grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-xl">
        <Column label={`Serial · ${serial.length}`}>
          {serial.length === 0
            ? <Empty>No serial ports found</Empty>
            : serial.map(p => (
                <Row key={p.port}>
                  <Dot ok={p.available} />
                  <Mono>{p.port}</Mono>
                </Row>
              ))}
        </Column>
        <Column label={`Cameras · ${cameras.length}`}>
          {cameras.length === 0
            ? <Empty>No cameras found</Empty>
            : cameras.map(c => (
                <Row key={c.path}>
                  <Dot ok={c.available} />
                  <Mono>{c.path}</Mono>
                  {c.available && (
                    <span className="ml-auto font-mono text-caption text-stone">
                      {c.width}×{c.height}
                    </span>
                  )}
                </Row>
              ))}
        </Column>
        <Column label="Calibration">
          {Object.keys(calibrations).length === 0
            ? <Empty>No calibrations found</Empty>
            : Object.entries(calibrations).map(([category, robots]) => (
                <div key={category} className="flex flex-col gap-1">
                  <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
                    {category}
                  </div>
                  {Object.entries(robots).map(([robotType, ids]) => (
                    <div
                      key={robotType}
                      className="flex items-baseline justify-between gap-md border-b border-dashed border-hairline-soft last:border-b-0 py-0.5"
                    >
                      <span className="text-body-sm-medium text-ink">{robotType}</span>
                      <span className="font-mono text-caption text-steel min-w-0 break-words">
                        {ids.length > 0 ? ids.join(", ") : "—"}
                      </span>
                    </div>
                  ))}
                </div>
              ))}
        </Column>
      </div>
      <p className="text-caption text-stone">
        Run calibration:{" "}
        <code className="rounded-xs border border-hairline bg-surface px-1.5 py-0.5 font-mono text-code-inline text-charcoal">
          python scripts/calibrate_so101.py --port /dev/ttyACM0 --id my_arm --type follower
        </code>
      </p>
    </section>
  );
}

function Column({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold mb-xs">
        {label}
      </div>
      <div className="flex flex-col gap-1">{children}</div>
    </div>
  );
}
function Row({ children }: { children: React.ReactNode }) {
  return <div className="flex items-center gap-xs text-body-sm">{children}</div>;
}
function Dot({ ok }: { ok: boolean }) {
  return <span aria-hidden className={`w-2 h-2 rounded-full ${ok ? "bg-brand-green" : "bg-brand-error"}`} />;
}
function Mono({ children }: { children: React.ReactNode }) {
  return <span className="font-mono text-code-sm text-charcoal">{children}</span>;
}
function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-body-sm text-stone">{children}</p>;
}
```

### Task 3.2: Create `ConfigurationsTabs`

**Files:**
- Create: `frontend/src/components/ConfigurationsTabs.tsx`

- [ ] **Step 1: Write the component**

```tsx
// frontend/src/components/ConfigurationsTabs.tsx
import { useState } from "react";
import { ConfigCard, type ConfigGroup, type ConfigCardEntry } from "./ConfigCard";
import { Button } from "./ui/button";
import { SegmentedTab, SegmentedTabBar } from "./ui/segmented-tab";
import { SectionMark } from "./ui/section-mark";

const GROUPS: { id: ConfigGroup; label: string }[] = [
  { id: "robot", label: "robot" },
  { id: "teleop", label: "teleop" },
  { id: "mapper", label: "mapper" },
  { id: "cameras", label: "cameras" },
  { id: "gopros", label: "gopros" },
];

interface Props {
  configs: Record<ConfigGroup, ConfigCardEntry[]>;
  refreshing: boolean;
  onRefresh: () => void;
  onEdit: (group: ConfigGroup, name: string) => void;
  onClone: (group: ConfigGroup, name: string) => void;
  onNew: (group: ConfigGroup) => void;
  // onDelete is intentionally NOT here in Phase 3 — added in Phase 4.
}

export function ConfigurationsTabs({
  configs, refreshing, onRefresh, onEdit, onClone, onNew,
}: Props) {
  const [active, setActive] = useState<ConfigGroup>("robot");
  const rows = configs[active] ?? [];

  return (
    <section className="flex flex-col gap-md">
      <header className="flex items-baseline gap-md">
        <SectionMark code="§04.B" name="Configurations" />
        <span className="flex-1 h-px bg-hairline-soft" />
        <Button variant="secondary" size="sm" onClick={() => onNew(active)}>
          + new {active}
        </Button>
        <Button variant="secondary" size="sm" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh"}
        </Button>
      </header>
      <SegmentedTabBar>
        {GROUPS.map(g => (
          <SegmentedTab
            key={g.id}
            active={active === g.id}
            onClick={() => setActive(g.id)}
          >
            {g.label} · {(configs[g.id] ?? []).length}
          </SegmentedTab>
        ))}
      </SegmentedTabBar>
      <div className="flex flex-col gap-2">
        {rows.length === 0 ? (
          <p className="text-body-sm text-stone py-md">No {active} configs.</p>
        ) : rows.map(cfg => (
          <ConfigCard
            key={cfg.name}
            config={cfg}
            group={active}
            rightSlot={
              <span className="flex items-center gap-1">
                <Button
                  variant="secondary"
                  size="sm"
                  className="!bg-surface hover:!bg-hairline"
                  onClick={() => onEdit(active, cfg.name)}
                >
                  ⚙ Edit
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  className="!bg-surface hover:!bg-hairline"
                  onClick={() => onClone(active, cfg.name)}
                >
                  Clone
                </Button>
                {/* ⌫ Delete — added in Phase 4 */}
              </span>
            }
          />
        ))}
      </div>
    </section>
  );
}
```

### Task 3.3: Rewrite `SettingsPage`

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Replace the page body**

Rewrite the file from the imports down:

```tsx
import { useEffect, useState } from "react";
import { apiFetch } from "../api/client";
import { ConfigEditorModal, type ConfigEntry, type ConfigEditorMode } from "../components/ConfigEditorModal";
import type { ConfigGroup, ConfigCardEntry } from "../components/ConfigCard";
import { ConfigurationsTabs } from "../components/ConfigurationsTabs";
import { HardwareStatusBlock } from "../components/HardwareStatusBlock";
import { PageHeader } from "../components/ui/page-header";

interface SerialDevice { port: string; available: boolean }
interface CameraDevice {
  path: string; device_id: number; available: boolean; width: number; height: number;
}

const CONFIG_GROUPS: ConfigGroup[] = ["robot", "teleop", "mapper", "cameras", "gopros"];

export default function SettingsPage() {
  const [serialPorts, setSerialPorts] = useState<SerialDevice[]>([]);
  const [cameras, setCameras] = useState<CameraDevice[]>([]);
  const [configs, setConfigs] = useState<Record<ConfigGroup, ConfigCardEntry[]>>({
    robot: [], teleop: [], mapper: [], cameras: [], gopros: [],
  });
  const [calibrations, setCalibrations] = useState<Record<string, Record<string, string[]>>>({});
  const [editing, setEditing] = useState<{ config: ConfigEntry; mode: ConfigEditorMode } | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const loadAll = async () => {
    setRefreshing(true);
    try {
      const [serial, cams, cal, ...groups] = await Promise.all([
        apiFetch<SerialDevice[]>("/api/settings/devices/serial"),
        apiFetch<CameraDevice[]>("/api/settings/devices/cameras"),
        apiFetch<Record<string, Record<string, string[]>>>("/api/settings/calibration"),
        ...CONFIG_GROUPS.map(g =>
          apiFetch<ConfigCardEntry[]>(`/api/settings/configs/${g}`).catch(() => [])
        ),
      ]);
      setSerialPorts(serial);
      setCameras(cams);
      setCalibrations(cal);
      const nextConfigs = { robot: [], teleop: [], mapper: [], cameras: [], gopros: [] } as Record<ConfigGroup, ConfigCardEntry[]>;
      CONFIG_GROUPS.forEach((g, i) => { nextConfigs[g] = groups[i]; });
      setConfigs(nextConfigs);
    } catch (e) {
      alert(`Failed to refresh: ${e}`);
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => { loadAll(); }, []);

  const openEditor = (group: ConfigGroup, name: string, mode: ConfigEditorMode) => {
    const cfg = configs[group]?.find(c => c.name === name);
    setEditing({
      config: { name, group, content: cfg?.content ?? {} },
      mode,
    });
  };

  return (
    <>
      <PageHeader
        code="§04"
        title="Settings"
      />
      <div className="flex-1 overflow-auto">
        <div className="max-w-[1200px] mx-auto px-xl py-xl flex flex-col gap-xl">
          <HardwareStatusBlock
            serial={serialPorts}
            cameras={cameras}
            calibrations={calibrations}
            refreshing={refreshing}
            onRefresh={loadAll}
          />
          <ConfigurationsTabs
            configs={configs}
            refreshing={refreshing}
            onRefresh={loadAll}
            onEdit={(g, n) => openEditor(g, n, "edit")}
            onClone={(g, n) => openEditor(g, n, "clone")}
            onNew={(g) => setEditing({ config: { name: "", group: g, content: {} }, mode: "new" })}
          />
        </div>
      </div>
      <ConfigEditorModal
        config={editing?.config ?? null}
        mode={editing?.mode ?? "edit"}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          loadAll();
        }}
      />
    </>
  );
}
```

The `gopros` group endpoint returns 404 in the demo (`rest-handlers.ts:205`); the `.catch(() => [])` keeps the tab empty rather than failing the whole page.

- [ ] **Step 2: Type-check**

```bash
cd frontend && npm run build
```

- [ ] **Step 3: Manual smoke**

```bash
cd frontend && npm run dev
```

Navigate to `/settings`. Verify:
- Hardware Status block shows three columns (Serial, Cameras, Calibration) above the fold.
- Tab strip shows all five groups with counts.
- Click each tab — rows appear / disappear correctly.
- Click `⚙ Edit` on a row → modal opens with content.
- Click `Clone` on a row → modal opens in `mode="clone"` with empty name field and pre-filled content.
- Click `+ new robot` in the tab header → modal opens empty.
- Save a new config with a unique name → modal closes → list refreshes with the new entry visible.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/HardwareStatusBlock.tsx frontend/src/components/ConfigurationsTabs.tsx frontend/src/pages/SettingsPage.tsx
git commit -m "feat(settings): unify Devices+Calibration into HardwareStatusBlock; tab Configurations

Three-column Hardware Status (Serial | Cameras | Calibration) replaces
the stacked Devices + Calibration sections. Configurations are now
tabbed across robot/teleop/mapper/cameras/gopros with per-tab Edit +
Clone actions. Single Refresh button replaces the three section-local
ones. Delete (⌫) deferred to Phase 4."
```

---

## Phase 4 — DELETE 409 hardening + `⌫` action

Add the active-session guard to the existing `DELETE /settings/configs/{group}/{name}` handler. Wire the `⌫` button in `ConfigurationsTabs`. Update demo handler.

### Task 4.1: Failing test for DELETE 409 active-session (cameras case)

**Files:**
- Modify: `tests/api/test_settings_routes.py` — append new tests at the end.

- [ ] **Step 1: Write the failing test for cameras**

Append to `tests/api/test_settings_routes.py`:

```python
from unittest.mock import MagicMock


def _stub_active_session(app, *, robot=None, teleop=None, mapper=None, image_sources=None):
    """Install a stub session_manager + session_meta on the app so
    the DELETE handler's `active` check (settings.py) reads as non-idle."""
    sm = MagicMock()
    sm.session.state.value = "recording"
    sm.session.stopped.is_set.return_value = False
    sm.session.sub_state = None
    sm.session.mode.value = "teleop"
    app.state.session_manager = sm
    app.state.session_meta = {
        "robot": robot,
        "teleop": teleop,
        "mapper": mapper,
        "slot_assignments": image_sources or [],
    }


def _stub_idle_manager(app):
    """Install a stale session_manager left over from a previous run that
    transitioned to IDLE on FatalHardwareError. The DELETE handler must
    treat this as logically gone and allow the delete."""
    sm = MagicMock()
    sm.session.state.value = "idle"
    sm.session.stopped.is_set.return_value = True
    app.state.session_manager = sm
    app.state.session_meta = {}


async def test_delete_config_refuses_409_when_robot_in_use(app, tmp_path):
    # Arrange: write a temp robot config + active session referencing it
    app.state.configs_root = tmp_path
    (tmp_path / "robot").mkdir()
    (tmp_path / "robot" / "so101.yaml").write_text("_target_: x\n")
    _stub_active_session(app, robot="so101")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.delete("/api/settings/configs/robot/so101")

    assert r.status_code == 409
    assert "active session" in r.json().get("detail", "").lower()
    # File must NOT be deleted
    assert (tmp_path / "robot" / "so101.yaml").exists()


async def test_delete_config_allowed_when_no_active_session(app, tmp_path):
    app.state.configs_root = tmp_path
    (tmp_path / "robot").mkdir()
    (tmp_path / "robot" / "so101.yaml").write_text("_target_: x\n")
    # No session_manager installed → idle.

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.delete("/api/settings/configs/robot/so101")

    assert r.status_code == 204
    assert not (tmp_path / "robot" / "so101.yaml").exists()


async def test_delete_camera_config_refuses_409_when_in_image_sources(app, tmp_path):
    app.state.configs_root = tmp_path
    (tmp_path / "cameras").mkdir()
    (tmp_path / "cameras" / "front.yaml").write_text("_target_: y\n")
    _stub_active_session(
        app,
        image_sources=[{"slot": "observation.images.front", "device": "front", "kind": "camera"}],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.delete("/api/settings/configs/cameras/front")

    assert r.status_code == 409
    assert (tmp_path / "cameras" / "front.yaml").exists()


async def test_delete_gopro_config_refuses_409_when_in_image_sources(app, tmp_path):
    app.state.configs_root = tmp_path
    (tmp_path / "gopros").mkdir()
    (tmp_path / "gopros" / "hero11.yaml").write_text("_target_: y\n")
    _stub_active_session(
        app,
        image_sources=[{"slot": "observation.images.wrist", "device": "hero11", "kind": "gopro"}],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.delete("/api/settings/configs/gopros/hero11")

    assert r.status_code == 409


async def test_delete_config_allowed_when_manager_is_stale_idle(app, tmp_path):
    # A FatalHardwareError can leave session_manager attached but in IDLE
    # state with stopped.is_set() == True (see session.py:81-86). Treat
    # this as logically gone and allow the delete.
    app.state.configs_root = tmp_path
    (tmp_path / "robot").mkdir()
    (tmp_path / "robot" / "so101.yaml").write_text("_target_: x\n")
    _stub_idle_manager(app)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.delete("/api/settings/configs/robot/so101")

    assert r.status_code == 204
    assert not (tmp_path / "robot" / "so101.yaml").exists()


async def test_delete_camera_config_ignores_unrelated_image_source(app, tmp_path):
    # An image_source pointing at `wrist` must not block deleting `front`.
    app.state.configs_root = tmp_path
    (tmp_path / "cameras").mkdir()
    (tmp_path / "cameras" / "front.yaml").write_text("_target_: y\n")
    _stub_active_session(
        app,
        image_sources=[{"slot": "observation.images.wrist", "device": "wrist", "kind": "camera"}],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.delete("/api/settings/configs/cameras/front")

    assert r.status_code == 204
```

- [ ] **Step 2: Run the tests — they must fail**

```bash
uv run pytest tests/api/test_settings_routes.py -v -k "delete_config or delete_camera or delete_gopro"
```

Expected: all five new tests FAIL (the handler currently doesn't check session state, so the 409 cases delete the file and return 204).

### Task 4.2: Implement the 409 guard

**Files:**
- Modify: `backend/mimicrec/api/routes/settings.py:209-217`

- [ ] **Step 1: Update the handler**

Find the current implementation:

```python
@router.delete("/settings/configs/{group}/{name}", status_code=204)
async def delete_config(request: Request, group: str, name: str):
    """Delete a config file."""
    root = get_configs_root(request.app)
    path = root / group / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"config '{group}/{name}' not found")
    path.unlink()
```

Replace with:

```python
@router.delete("/settings/configs/{group}/{name}", status_code=204)
async def delete_config(request: Request, group: str, name: str):
    """Delete a config file. Refuses with 409 if the config is currently
    bound to an active recording session — deleting it would leave the
    writer holding a path that no longer exists on disk.
    """
    # Active-session guard. The session metadata shape is documented in
    # `backend/mimicrec/api/routes/session.py:42-61` (build_state_payload).
    # A stale manager left in IDLE after FatalHardwareError is treated as
    # logically gone (matches the session_start path at session.py:81-83),
    # so we only refuse when the manager is in a non-idle, non-stopped state.
    meta = getattr(request.app.state, "session_meta", None) or {}
    sm = getattr(request.app.state, "session_manager", None)
    active = (
        sm is not None
        and getattr(sm.session, "state", None) is not None
        and sm.session.state.value != "idle"
        and not sm.session.stopped.is_set()
    )
    if active:
        if group in ("robot", "teleop", "mapper"):
            if meta.get(group) == name:
                raise HTTPException(
                    status_code=409,
                    detail=f"active session uses this config (group={group}, name={name})",
                )
        elif group == "cameras":
            for src in meta.get("slot_assignments", []):
                # slot_assignments come back as either dicts or SlotAssignment
                # models depending on call path — handle both.
                src_kind = src.get("kind") if isinstance(src, dict) else getattr(src, "kind", None)
                src_device = src.get("device") if isinstance(src, dict) else getattr(src, "device", None)
                if src_kind == "camera" and src_device == name:
                    raise HTTPException(
                        status_code=409,
                        detail=f"active session uses this camera config (name={name})",
                    )
        elif group == "gopros":
            for src in meta.get("slot_assignments", []):
                src_kind = src.get("kind") if isinstance(src, dict) else getattr(src, "kind", None)
                src_device = src.get("device") if isinstance(src, dict) else getattr(src, "device", None)
                if src_kind == "gopro" and src_device == name:
                    raise HTTPException(
                        status_code=409,
                        detail=f"active session uses this gopro config (name={name})",
                    )

    root = get_configs_root(request.app)
    path = root / group / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"config '{group}/{name}' not found")
    path.unlink()
```

Ensure `HTTPException` is imported at the top of the file (it should be — verify with `grep -n "HTTPException" backend/mimicrec/api/routes/settings.py`).

- [ ] **Step 2: Re-run the tests**

```bash
uv run pytest tests/api/test_settings_routes.py -v -k "delete_config or delete_camera or delete_gopro"
```

Expected: all five tests PASS.

- [ ] **Step 3: Run the full settings test file to confirm no regressions**

```bash
uv run pytest tests/api/test_settings_routes.py -v
```

Expected: all existing tests still pass (the GET/PUT/POST handlers weren't touched).

- [ ] **Step 4: Commit**

```bash
git add backend/mimicrec/api/routes/settings.py tests/api/test_settings_routes.py
git commit -m "feat(settings): refuse DELETE /settings/configs/* with 409 when in use

When a recording session is active and the config being deleted is the
current robot/teleop/mapper, or the device of a camera/gopro
image_source, the handler returns 409 instead of unlinking. Prevents
the writer from being left holding a stale path mid-session.

Covers all five groups (robot/teleop/mapper/cameras/gopros) with
distinct field-matching rules per the SessionStatePayload shape at
session.py:42-61."
```

### Task 4.3: Surface the `⌫` button + frontend wiring

**Files:**
- Modify: `frontend/src/components/ConfigurationsTabs.tsx`

- [ ] **Step 1: Add `onDelete` prop**

In `ConfigurationsTabs.tsx`, add to `Props`:

```tsx
onDelete: (group: ConfigGroup, name: string) => void;
```

Update the `rightSlot` block to include the delete button:

```tsx
rightSlot={
  <span className="flex items-center gap-1">
    <Button
      variant="secondary"
      size="sm"
      className="!bg-surface hover:!bg-hairline"
      onClick={() => onEdit(active, cfg.name)}
    >
      ⚙ Edit
    </Button>
    <Button
      variant="secondary"
      size="sm"
      className="!bg-surface hover:!bg-hairline"
      onClick={() => onClone(active, cfg.name)}
    >
      Clone
    </Button>
    <Button
      variant="secondary"
      size="sm"
      className="!bg-surface hover:!bg-brand-error/15 !text-brand-error"
      onClick={() => onDelete(active, cfg.name)}
      aria-label={`Delete ${cfg.name}`}
    >
      ⌫
    </Button>
  </span>
}
```

- [ ] **Step 2: Wire `onDelete` in `SettingsPage`**

In `SettingsPage.tsx`, add a delete handler:

```tsx
const handleDelete = async (group: ConfigGroup, name: string) => {
  if (!window.confirm(`Delete ${group}/${name}?`)) return;
  // NOTE: cannot use apiFetch — it calls res.json() unconditionally
  // (client.ts:38), which fails on the 204 No Content response from a
  // successful DELETE. Use raw fetch with explicit status handling.
  const res = await fetch(`/api/settings/configs/${group}/${name}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (res.status === 204) {
    loadAll();
    return;
  }
  if (res.status === 409) {
    const body = await res.json().catch(() => ({ detail: "in use" }));
    alert(`Cannot delete ${group}/${name}: ${body.detail}`);
    return;
  }
  const body = await res.json().catch(() => ({ detail: res.statusText }));
  alert(`Delete failed: ${body.detail}`);
};
```

Pass it to `ConfigurationsTabs`:

```tsx
<ConfigurationsTabs
  ...
  onDelete={handleDelete}
/>
```

- [ ] **Step 3: Update demo handler**

In `frontend/src/demo/rest-handlers.ts`, find the `stubHandlers` array and add:

```ts
http.delete("/api/settings/configs/:group/:name", demoUnsupported),
```

- [ ] **Step 4: Type-check both builds**

```bash
cd frontend && npm run build && npm run build:demo
```

Expected: both build cleanly.

- [ ] **Step 5: Manual smoke**

```bash
cd frontend && npm run dev
```

Make a throwaway config (`echo '{"_target_": "test"}' | curl -X POST http://localhost:5173/api/settings/configs/robot/throwaway -H 'Content-Type: application/json' -d @-`), then in the UI:

- Click `⌫` on `throwaway.yaml` → confirm dialog → row disappears, list refreshes.
- Start a session with `robot=so101`, then in another window click `⌫` on `so101.yaml` → alert shows "is in use by the current session".

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ConfigurationsTabs.tsx frontend/src/pages/SettingsPage.tsx frontend/src/demo/rest-handlers.ts
git commit -m "feat(settings): wire ⌫ delete action with 409 in-use messaging

Adds the ⌫ button to per-tab config rows; handler issues DELETE and
surfaces the 409 active-session refusal inline as an alert. Demo build
stubs DELETE as unsupported."
```

---

## Self-Review

Spec sections vs plan tasks — every requirement maps to at least one task:

- **Goals → 1280×900 no-scroll Record idle** → Task 2a.1 (grid layout) + Task 2a.3 (viewport check). ✓
- **Goals → Hardware-list scalability** → Task 2b.1 (ConfigPickerRow with count chip, whole-row click, missing-config state). ✓
- **Goals → In-place editing** → Task 2b.2 (modal mount in RecordPage) + Task 2b.3 (wiring). ✓
- **Goals → Settings Hardware Status above the fold** → Task 3.1 + Task 3.3 (page order). ✓
- **Goals → Settings Configurations as horizontal tabs** → Task 3.2. ✓
- **Goals → Camera assignments no longer native <select>** — *Partial:* Task 2a.2 extracts to `CameraSlotRow` but **keeps the native `<select>` inside the row for device choice**. The spec says "no native <select>" but the popover replacement for camera *device* choice is not in this plan. **Adding follow-up task below** (Task 2b.4) to fully replace the device select with a popover for parity with the Robot/Teleop/Mapper rows.
- **Architecture → shared ConfigEditorModal** → Task 1.1 + Task 1.2. ✓
- **Architecture → ConfigPickerRow** → Task 2b.1. ✓
- **Architecture → keyboard nav day-1** → Task 2b.1 (arrow/Enter/Esc in the useEffect). ✓
- **Architecture → POST for new/clone** → Task 1.1 (modal save branches on mode). ✓
- **Architecture → DELETE 409 active-session** → Task 4.1 (test) + Task 4.2 (implementation). ✓
- **Architecture → editing during live session** — *Not implemented:* the "affects next session" badge from the spec is not in this plan. Low priority; flagging for follow-up rather than adding a task now (parity with current behaviour where Settings already allows editing during a session without warning).
- **Migration → 5 phases** → Phases 1, 2a, 2b, 3, 4 as written. ✓

### Task 2b.4: Replace `CameraSlotRow`'s device `<select>` with a popover (fills the Goals gap)

**Files:**
- Modify: `frontend/src/components/CameraSlotRow.tsx`

- [ ] **Step 1: Rewrite `CameraSlotRow` with an inline `DevicePickerButton`**

Replace the entire `CameraSlotRow` function body. The component now embeds a popover button that mirrors the `ConfigPickerRow` keyboard-nav pattern but renders a narrower trigger inline (not a full-width row).

```tsx
// frontend/src/components/CameraSlotRow.tsx
import { useEffect, useRef, useState } from "react";
import { ChevronDown, Settings } from "lucide-react";
import { Badge } from "./ui/badge";
import { cn } from "../lib/utils";

export interface DeviceOption {
  name: string;
  kind: "camera" | "gopro";
}

interface CameraSlotRowProps {
  slot: string;
  device: string;
  locked: boolean;
  legacy: boolean;
  deviceOptions: DeviceOption[];
  usedDevices: Set<string>;
  onChange: (device: string) => void;
  onRemove?: () => void;
  onEdit?: (deviceName: string) => void;
}

export function CameraSlotRow({
  slot, device, locked, legacy, deviceOptions, usedDevices,
  onChange, onRemove, onEdit,
}: CameraSlotRowProps) {
  return (
    <div className="flex items-center gap-sm rounded-md border border-hairline bg-canvas px-md py-2">
      <Badge variant="type" className="font-mono">
        {slot}{legacy && " (legacy)"}
      </Badge>
      <span className="flex-1" />
      <DevicePickerButton
        device={device}
        options={deviceOptions}
        usedDevices={usedDevices}
        disabled={locked && !device}
        onChange={onChange}
      />
      {onEdit && device && (
        <button
          type="button"
          onClick={() => onEdit(device)}
          className="text-stone hover:text-ink px-1"
          aria-label={`Edit ${device}`}
        >
          <Settings className="w-4 h-4" />
        </button>
      )}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="text-stone hover:text-brand-error px-2"
          aria-label={`Remove ${slot}`}
        >
          ✕
        </button>
      )}
    </div>
  );
}

interface AddSlotButtonProps {
  roles: string[];
  onAdd: (role: string) => void;
}

export function AddSlotButton({ roles, onAdd }: AddSlotButtonProps) {
  return (
    <select
      value=""
      className="border border-dashed border-hairline rounded-md px-md py-2 text-body-sm bg-canvas text-stone"
      onChange={e => { if (e.target.value) onAdd(e.target.value); }}
    >
      <option value="">+ add slot…</option>
      {roles.map(r => (
        <option key={r} value={r}>{r}</option>
      ))}
    </select>
  );
}

interface DevicePickerButtonProps {
  device: string;
  options: DeviceOption[];
  usedDevices: Set<string>;
  disabled: boolean;
  onChange: (device: string) => void;
}

function DevicePickerButton({
  device, options, usedDevices, disabled, onChange,
}: DevicePickerButtonProps) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)
          && !triggerRef.current?.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlight(h => Math.min(h + 1, options.length));
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlight(h => Math.max(h - 1, 0));
      }
      if (e.key === "Enter") {
        e.preventDefault();
        // Slot 0 = "none", slots 1..N = options
        if (highlight === 0) {
          onChange("");
        } else {
          const item = options[highlight - 1];
          if (item) onChange(item.name);
        }
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, options, highlight, onChange]);

  const label = device
    ? `${device} (${options.find(o => o.name === device)?.kind ?? "?"})`
    : "— none —";

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        onClick={() => setOpen(o => !o)}
        className={cn(
          "border border-hairline rounded px-2 py-1 text-body-sm bg-canvas min-w-[200px] flex items-center gap-2",
          "focus:outline-none focus:ring-2 focus:ring-ink",
          disabled && "opacity-50 cursor-not-allowed",
        )}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="flex-1 text-left truncate">{label}</span>
        <ChevronDown className="w-3.5 h-3.5 text-stone" />
      </button>
      {open && (
        <div
          ref={menuRef}
          role="menu"
          className="absolute z-40 mt-1 w-full bg-canvas border border-hairline rounded-md shadow-lg p-1 max-h-[200px] overflow-auto"
        >
          <div
            role="menuitem"
            className={cn(
              "px-2 py-1 rounded-sm cursor-pointer text-stone",
              highlight === 0 ? "bg-surface" : "",
            )}
            onMouseEnter={() => setHighlight(0)}
            onClick={() => { onChange(""); setOpen(false); }}
          >
            — none —
          </div>
          {options.map((opt, i) => {
            const inUse = usedDevices.has(opt.name) && device !== opt.name;
            return (
              <div
                key={opt.name}
                role="menuitem"
                aria-disabled={inUse}
                className={cn(
                  "px-2 py-1 rounded-sm",
                  inUse ? "text-stone cursor-not-allowed" : "cursor-pointer text-ink",
                  highlight === i + 1 ? "bg-surface" : "",
                )}
                onMouseEnter={() => setHighlight(i + 1)}
                onClick={() => {
                  if (inUse) return;
                  onChange(opt.name);
                  setOpen(false);
                }}
              >
                {opt.name} <span className="text-caption text-stone">({opt.kind}){inUse && " · in use"}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npm run build
```

Expected: build succeeds.

- [ ] **Step 3: Manual smoke**

```bash
cd frontend && npm run dev
```

At `/record` idle: click a camera slot's device button → popover opens with keyboard nav (↑↓ + Enter + Esc). Selecting a device updates the slot; "— none —" clears it; "in use" devices appear disabled.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/CameraSlotRow.tsx
git commit -m "feat(record): replace native <select> in CameraSlotRow with keyboard-nav popover"
```

### Placeholder scan

No `TBD`, `TODO`, "implement later", or vague-handling steps in any task body. All function names referenced in later tasks (`openEditor`, `handleStart`, `loadAll`, `_stub_active_session`) are defined in earlier tasks. ✓

### Type consistency

- `ConfigGroup` is imported from `frontend/src/components/ConfigCard.tsx` everywhere (Phase 1+2b+3). ✓
- `ConfigEditorMode` is exported by `ConfigEditorModal.tsx` and consumed by `SessionConfigForm`, `RecordPage`, and `SettingsPage`. ✓
- `ConfigCardEntry` from `ConfigCard.tsx:9-12` is the shape passed into `ConfigPickerRow.configs` and `ConfigurationsTabs.configs`. Both use it consistently. ✓
- The backend test fixture `_stub_active_session` matches the actual `build_state_payload` shape at `session.py:42-61`. ✓

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-14-record-settings-layout.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
