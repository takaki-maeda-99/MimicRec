# Pages Layout Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure Inference / Episodes / Replay pages to use full viewport width, add monochrome icons to sidebar nav, and wire synchronized playback across video + plots + scrubber on Replay.

**Architecture:** Phased rollout. Phase 0 lays foundations (sidebar icons + shared frame-data hook). Phases 1–3 redesign each page using the foundations. Each phase is independently mergeable — phase boundaries are natural review/commit checkpoints.

**Tech Stack:** React 19 + TypeScript 6 + Vite 8, React Router 7, Recharts 3.8, lucide-react 1.11, @tanstack/react-query 5, zustand 5, Tailwind CSS 4. No frontend test framework — verification = `tsc --noEmit` + manual dev-server smoke. Tests run via `cd frontend && npx tsc --noEmit` (treat exit 0 as pass).

**Reference spec:** `docs/superpowers/specs/2026-05-14-pages-layout-design.md`. Read it before starting.

---

## File structure

**New files:**
- `frontend/src/hooks/useEpisodeFrames.ts` — shared React Query hook fetching `/api/datasets/:ds/episodes/:idx/frames`
- `frontend/src/hooks/useEpisodeThumbnail.ts` — offscreen-video → canvas → cached dataURL
- `frontend/src/hooks/useEpisodeTimeline.ts` — master timeline state driven by rVFC / `timeupdate`
- `frontend/src/hooks/useSecondaryVideoSync.ts` — slave secondary `<video>` to master
- `frontend/src/components/Scrubber.tsx` — full-width timeline scrubber
- `frontend/src/components/inference/SessionColumn.tsx`
- `frontend/src/components/inference/CameraColumn.tsx`
- `frontend/src/components/inference/TelemetryColumn.tsx`
- `frontend/src/components/inference/PhaseActionBar.tsx`
- `frontend/src/components/episodes/EpisodesFilterBar.tsx`
- `frontend/src/components/episodes/EpisodesList.tsx`
- `frontend/src/components/episodes/EpisodePreviewPane.tsx`
- `frontend/src/components/episodes/MiniJointPlot.tsx`
- `frontend/src/components/episodes/MiniEePlot.tsx`

**Modified files:**
- `frontend/src/components/ui/sidebar-nav-item.tsx` — accept `icon` prop
- `frontend/src/components/Layout.tsx` — wire icons per nav item
- `frontend/src/components/JointPlot.tsx` — consume `useEpisodeFrames`, accept `cursorTimeSec` + `onSeek` props, add `<ReferenceLine>`
- `frontend/src/components/EndEffectorPlot.tsx` — consume `useEpisodeFrames`, accept `cursorFrameIdx`, draw current-position dot
- `frontend/src/components/VideoPlayer.tsx` — accept `videoRef`, `isMaster`, `onTimeUpdate` props
- `frontend/src/pages/InferencePage.tsx` — full rewrite as 3-column + bottom bar
- `frontend/src/pages/EpisodesPage.tsx` — full rewrite as filter bar + split view
- `frontend/src/pages/ReplayPage.tsx` — full rewrite as left-video / right-plots + master scrubber

**Conventions for every task:**
1. Write the smallest unit of code that achieves the step.
2. After each implementation step, run `cd frontend && npx tsc --noEmit` and fix every error before moving on.
3. After each task is functionally complete, run `pnpm dev` (or `npm run dev`) and verify the screen renders + the described interaction works.
4. Commit at the end of every task with a `feat(...)` / `refactor(...)` message. Frequent small commits beat one big commit.

---

## Phase 0 — Foundation

### Task 0.1: Sidebar icons

**Files:**
- Modify: `frontend/src/components/ui/sidebar-nav-item.tsx`
- Modify: `frontend/src/components/Layout.tsx:10-15` and `:68-72`

- [ ] **Step 1: Add `icon` prop to `SidebarNavItem`**

Replace the file with:

```tsx
import { NavLink } from "react-router-dom";
import type { LucideIcon } from "lucide-react";
import { cn } from "../../lib/utils";

interface SidebarNavItemProps {
  to: string;
  /** Section code prefix, e.g. "§01". Required by the new design. */
  code?: string;
  /** Optional monochrome icon (Lucide). Stroke uses currentColor so the
   * active-state inversion works automatically. */
  icon?: LucideIcon;
  children: React.ReactNode;
  className?: string;
}

export function SidebarNavItem({
  to,
  code,
  icon: Icon,
  children,
  className,
}: SidebarNavItemProps) {
  return (
    <NavLink
      to={to}
      end={false}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-sm rounded-sm px-2.5 py-1.5 text-body-sm-medium transition-colors",
          isActive
            ? "bg-ink text-on-primary"
            : "text-slate hover:bg-surface-soft hover:text-ink",
          className,
        )
      }
    >
      {({ isActive }) => (
        <>
          {Icon && (
            <Icon
              size={14}
              strokeWidth={1.75}
              className="flex-shrink-0"
              aria-hidden
            />
          )}
          {code && (
            <span
              className={cn(
                "font-mono text-micro-uppercase",
                isActive ? "text-on-dark-mark" : "text-stone",
              )}
            >
              {code}
            </span>
          )}
          <span>{children}</span>
        </>
      )}
    </NavLink>
  );
}
```

- [ ] **Step 2: Wire icons in `Layout.tsx`**

Replace the `navItems` array (lines 10-15) with:

```tsx
import { LayoutGrid, Disc, Play, Settings as SettingsIcon } from "lucide-react";

const navItems = [
  { to: "/datasets",  code: "§01", label: "Datasets",  icon: LayoutGrid },
  { to: "/record",    code: "§02", label: "Record",    icon: Disc },
  { to: "/inference", code: "§03", label: "Inference", icon: Play },
  { to: "/settings",  code: "§04", label: "Settings",  icon: SettingsIcon },
];
```

And update the map call (line ~68) to pass the icon:

```tsx
{navItems.map((item) => (
  <SidebarNavItem key={item.to} to={item.to} code={item.code} icon={item.icon}>
    {item.label}
  </SidebarNavItem>
))}
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: exit 0.

- [ ] **Step 4: Manual verify**

Run dev server, open the app, confirm each nav item shows its icon to the left of `§XX Label`. Active item inverts (white icon on dark background).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui/sidebar-nav-item.tsx frontend/src/components/Layout.tsx
git commit -m "feat(sidebar): add monochrome icons to nav items"
```

---

### Task 0.2: Shared `useEpisodeFrames` hook + plot migration

**Files:**
- Create: `frontend/src/hooks/useEpisodeFrames.ts`
- Modify: `frontend/src/components/JointPlot.tsx`
- Modify: `frontend/src/components/EndEffectorPlot.tsx`

- [ ] **Step 1: Create the hook**

Create `frontend/src/hooks/useEpisodeFrames.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";

export interface FrameRow {
  timestamp: number;
  "observation.state.joint_pos"?: number[];
  "observation.state.joint_vel"?: number[];
  [key: string]: unknown;
}

/**
 * Fetches the frames parquet for a single episode and caches it under the
 * stable key ["episode-frames", ds, idx]. Multiple consumers (JointPlot,
 * EndEffectorPlot, MiniJointPlot, MiniEePlot) share the cache so each
 * episode is fetched at most once until it becomes stale.
 */
export function useEpisodeFrames(ds: string, idx: number, enabled = true) {
  return useQuery<FrameRow[]>({
    queryKey: ["episode-frames", ds, idx],
    queryFn: () =>
      apiFetch<FrameRow[]>(`/api/datasets/${ds}/episodes/${idx}/frames`),
    enabled: enabled && !!ds && Number.isFinite(idx),
    staleTime: 5 * 60_000,
  });
}
```

- [ ] **Step 2: Migrate `JointPlot` to consume the hook**

Replace the fetching block in `JointPlot.tsx` (the `useEffect` that calls `apiFetch<FrameRow[]>`) with the hook + a `useMemo`-driven transform. The complete diff:

Find:
```tsx
const [data, setData] = useState<Record<string, number>[]>([]);
const [jointNames, setJointNames] = useState<string[]>([]);
const [hasVelocity, setHasVelocity] = useState(false);
const [mode, setMode] = useState<"position" | "velocity">("position");
const [loading, setLoading] = useState(true);

useEffect(() => {
  setLoading(true);
  apiFetch<FrameRow[]>(`/api/datasets/${ds}/episodes/${idx}/frames`)
    .then((rows) => {
      // ... transform ...
    })
    .catch(console.error)
    .finally(() => setLoading(false));
}, [ds, idx]);
```

Replace with:

```tsx
import { useEpisodeFrames } from "../hooks/useEpisodeFrames";
import { useEffect, useMemo, useState } from "react";

const { data: rows = [], isLoading: loading } = useEpisodeFrames(ds, idx);
const [mode, setMode] = useState<"position" | "velocity">("position");

const { data, jointNames, hasVelocity } = useMemo(() => {
  if (!rows.length) {
    return { data: [] as Record<string, number>[], jointNames: [] as string[], hasVelocity: false };
  }
  const firstPos = rows[0]["observation.state.joint_pos"];
  if (!Array.isArray(firstPos) || firstPos.length === 0) {
    return { data: [] as Record<string, number>[], jointNames: [] as string[], hasVelocity: false };
  }
  const nJoints = firstPos.length;
  const names = Array.from({ length: nJoints }, (_, i) => `j${i + 1}`);
  let nonzeroVel = false;
  const chartData = rows.map((row) => {
    const pos = row["observation.state.joint_pos"];
    const vel = row["observation.state.joint_vel"];
    const entry: Record<string, number> = {
      time: Math.round((row.timestamp as number) * 1000) / 1000,
    };
    if (Array.isArray(pos)) {
      names.forEach((name, i) => {
        entry[`pos_${name}`] = Math.round(((pos[i] as number) ?? 0) * 1000) / 1000;
        const v = (Array.isArray(vel) ? (vel[i] as number) : 0) ?? 0;
        entry[`vel_${name}`] = Math.round(v * 1000) / 1000;
        if (v !== 0) nonzeroVel = true;
      });
    }
    return entry;
  });
  return { data: chartData, jointNames: names, hasVelocity: nonzeroVel };
}, [rows]);

// Clamp mode to position when velocity becomes unavailable. Effect, not
// render-phase setState — render-phase writes are an anti-pattern under
// React 18+ concurrent rendering.
useEffect(() => {
  if (!hasVelocity && mode !== "position") setMode("position");
}, [hasVelocity, mode]);
```

Delete the now-unused `useEffect`, `useState<…[]>([])` for data/jointNames/hasVelocity, and the top-level `apiFetch` import if unused elsewhere in the file.

- [ ] **Step 3: Migrate `EndEffectorPlot` similarly**

Same pattern. Replace its fetching `useEffect` with:

```tsx
import { useEpisodeFrames } from "../hooks/useEpisodeFrames";
import { useMemo } from "react";

const { data: rows = [], isLoading: loading } = useEpisodeFrames(ds, idx);

const { data, presentChannels } = useMemo(() => {
  if (!rows.length) return { data: [] as Record<string, number>[], presentChannels: [] as typeof CHANNELS };
  const present = CHANNELS.filter((c) =>
    rows.some((r) => typeof r[c.key] === "number")
  );
  const chartData = rows.map((row) => {
    const entry: Record<string, number> = {
      time: Math.round((row.timestamp as number) * 1000) / 1000,
    };
    for (const c of present) {
      const v = row[c.key];
      if (typeof v === "number") entry[c.key] = Math.round(v * 1000) / 1000;
    }
    return entry;
  });
  return { data: chartData, presentChannels: present };
}, [rows]);
```

Delete the unused `useState`/`useEffect`/`apiFetch` accordingly.

- [ ] **Step 4: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: exit 0.

- [ ] **Step 5: Manual verify**

Run dev server, navigate to any recorded episode's Replay page, confirm joint plot and EE plot still render identically to before. Open browser DevTools → Network and refresh — confirm `/frames` is requested **once** even though two plots use it. (Episodes page is not yet ready to verify dedup-across-pages here; that gets checked again in Task 2.7's manual verify.)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useEpisodeFrames.ts frontend/src/components/JointPlot.tsx frontend/src/components/EndEffectorPlot.tsx
git commit -m "refactor(plots): share episode-frames fetch via useEpisodeFrames hook"
```

---

## Phase 1 — Inference 3-column

### Task 1.1: SessionColumn component

**Files:**
- Create: `frontend/src/components/inference/SessionColumn.tsx`

- [ ] **Step 1: Implement**

```tsx
import { useInferenceStore } from "../../state/inference-store";
import { useSessionStore } from "../../state/session-store";
import { Button } from "../ui/button";
import { Select } from "../ui/select";
import { Input } from "../ui/input";

interface Props {
  disabled: boolean;
}

export function SessionColumn({ disabled }: Props) {
  const s = useInferenceStore();
  const sessionDataset = useSessionStore((x) => x.dataset);
  const selected = s.configs.find((c) => c.name === s.selectedConfig);
  const selectedHasError = !!selected?.error;

  return (
    <aside className="w-[220px] flex-shrink-0 border-r border-hairline bg-canvas flex flex-col">
      <div className="px-md py-md flex-1 overflow-auto flex flex-col gap-md">
        <Section title="Session">
          <Field label="Config">
            {s.phase === "pre-start" ? (
              <Select
                value={s.selectedConfig}
                onChange={(e) => s.selectConfig(e.target.value)}
                disabled={disabled}
              >
                <option value="">— select —</option>
                {s.configs.map((c) => (
                  <option key={c.name} value={c.name} disabled={!!c.error}>
                    {c.title && c.title !== c.name ? `${c.name} — ${c.title}` : c.name}
                    {c.error ? " (load error)" : ""}
                  </option>
                ))}
              </Select>
            ) : (
              <Readonly>{s.selectedConfig || "—"}</Readonly>
            )}
            {selected?.description && (
              <div className={`text-xs mt-1 ${selectedHasError ? "text-brand-error" : "text-steel"}`}>
                {selected.description}
              </div>
            )}
          </Field>

          <Field label={s.phase === "recording" || s.phase === "review" ? "Instruction (locked)" : "Instruction"}>
            {s.phase === "pre-start" || s.phase === "ready" ? (
              <div className="flex gap-2">
                <Input
                  type="text"
                  value={s.instruction}
                  onChange={(e) => s.setInstruction(e.target.value)}
                  placeholder="pick up the bottle"
                  disabled={disabled}
                />
                {s.phase === "ready" && (
                  <Button variant="outline" size="sm" onClick={() => s.updateInstruction()}>
                    Update
                  </Button>
                )}
              </div>
            ) : (
              <Readonly>{s.lockedInstruction ?? s.instruction}</Readonly>
            )}
          </Field>

          <Field label="Dataset">
            <Readonly>
              <code className="text-ink">{sessionDataset ?? "—"}</code>
            </Readonly>
          </Field>

          {(s.phase === "recording" || s.phase === "review") && s.reviewEpisode && (
            <Field label="Episode">
              <Readonly>
                #{s.reviewEpisode.index} · {s.reviewEpisode.durationSec.toFixed(1)}s
              </Readonly>
            </Field>
          )}
        </Section>
      </div>

      {(s.phase === "ready" || s.phase === "recording") && (
        <div className="px-md pb-md border-t border-hairline-soft pt-md">
          <Button
            variant="outline"
            className="w-full"
            onClick={() => s.stopSession()}
            disabled={s.phase === "recording"}
            title={s.phase === "recording" ? "Stop the episode first" : undefined}
          >
            Stop session
          </Button>
        </div>
      )}
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">{title}</div>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <div className="text-xs text-slate">{label}</div>
      {children}
    </label>
  );
}

function Readonly({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-sm bg-surface px-2 py-1 text-body-sm text-ink">
      {children}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: exit 0. (The file isn't imported yet, but it should compile standalone.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/inference/SessionColumn.tsx
git commit -m "feat(inference): add SessionColumn region component"
```

---

### Task 1.2: CameraColumn component

**Files:**
- Create: `frontend/src/components/inference/CameraColumn.tsx`

- [ ] **Step 1: Implement**

```tsx
import { useSessionStore } from "../../state/session-store";
import CameraPreview from "../CameraPreview";

export function CameraColumn() {
  // session-store exposes `cameras: string[]` (camera names, e.g. ["front", "wrist"])
  const cameras = useSessionStore((s) => s.cameras);
  const previewEnabled = useSessionStore((s) => s.previewEnabled);

  if (!previewEnabled) {
    return (
      <section className="flex-1 min-w-0 bg-surface flex items-center justify-center">
        <p className="text-body-sm text-stone">
          Camera preview disabled for this session.
        </p>
      </section>
    );
  }

  if (cameras.length === 0) {
    return (
      <section className="flex-1 min-w-0 bg-surface flex items-center justify-center">
        <p className="text-body-sm text-stone">No cameras available.</p>
      </section>
    );
  }

  const cols = cameras.length === 1 ? "grid-cols-1" : "grid-cols-2";

  return (
    <section className="flex-1 min-w-0 bg-surface p-md flex flex-col gap-sm">
      <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
        Cameras (live)
      </div>
      <div className={`grid ${cols} gap-sm flex-1 min-h-0`}>
        {cameras.map((cam) => (
          <CameraPreview key={cam} camName={cam} />
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/inference/CameraColumn.tsx
git commit -m "feat(inference): add CameraColumn region (reuses CameraPreview)"
```

---

### Task 1.3: TelemetryColumn component

**Files:**
- Create: `frontend/src/components/inference/TelemetryColumn.tsx`

- [ ] **Step 1: Implement**

Pull the existing `TelemetryBlock`, `Stat`, and `ActionPreview` helpers out of `InferencePage.tsx:285-359` and into this file, rendered in a 2-column tile grid:

```tsx
import { useInferenceStore } from "../../state/inference-store";

export function TelemetryColumn() {
  const t = useInferenceStore((x) => x.telemetry);
  const a = t.nextAction;

  return (
    <aside className="w-[220px] flex-shrink-0 border-l border-hairline bg-canvas flex flex-col">
      <div className="px-md py-md flex-1 overflow-auto flex flex-col gap-md">
        <div className="space-y-2">
          <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
            Telemetry
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Tile k="buffer"  v={`${t.bufferDepth} / ${t.bufferOrigin}`} />
            <Tile k="latency" v={t.lastLatencyMs == null ? "—" : `${t.lastLatencyMs.toFixed(1)} ms`} />
            <Tile k="chunks"  v={String(t.chunksConsumed)} />
            <Tile k="errors"  v={String(t.inferenceErrors)} warn={t.inferenceErrors > 0} />
            <Tile k="clamps"  v={t.clampsLastChunk == null ? "—" : String(t.clampsLastChunk)} />
            <Tile k="safety"  v={String(t.safetyEvents.length)} warn={t.safetyEvents.length > 0} />
          </div>
        </div>

        {a && Array.isArray(a.ee_delta) && (
          <div className="space-y-2">
            <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
              Next action
            </div>
            <div className="rounded-sm bg-surface-code px-2 py-2 font-mono text-xs text-on-dark space-y-0.5">
              <div>ΔEE [{a.ee_delta.map((v: number) => v.toFixed(3)).join(", ")}]</div>
              <div>gripper {typeof a.gripper === "number" ? a.gripper.toFixed(3) : "—"}</div>
            </div>
          </div>
        )}

        {t.modelDoneSignal && (
          <div className="space-y-1">
            <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
              Model done
            </div>
            <div className="text-body-sm">
              {t.modelDoneSignal === "waiting"     && <span className="text-stone">waiting…</span>}
              {t.modelDoneSignal === "received"    && <span className="text-brand-green-deep">received ✓</span>}
              {t.modelDoneSignal === "unsupported" && <span className="text-stone">unsupported</span>}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

function Tile({ k, v, warn }: { k: string; v: string; warn?: boolean }) {
  return (
    <div className="rounded-sm border border-hairline-soft bg-surface-soft px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-steel">{k}</div>
      <div className={`font-mono text-body-sm-medium ${warn ? "text-brand-error" : "text-ink"}`}>
        {v}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Adjust `t.modelDoneSignal` / `t.nextAction` / `t.safetyEvents` to match the actual telemetry slice shape from `frontend/src/state/inference-store.ts`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/inference/TelemetryColumn.tsx
git commit -m "feat(inference): add TelemetryColumn region"
```

---

### Task 1.4: PhaseActionBar component

**Files:**
- Create: `frontend/src/components/inference/PhaseActionBar.tsx`

- [ ] **Step 1: Implement**

```tsx
import { useInferenceStore } from "../../state/inference-store";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";

interface Props {
  /** True when session is in a state that permits starting inference. */
  canStartSession: boolean;
}

export function PhaseActionBar({ canStartSession }: Props) {
  const s = useInferenceStore();
  const selected = s.configs.find((c) => c.name === s.selectedConfig);
  const selectedHasError = !!selected?.error;
  const canStart = canStartSession && !!s.selectedConfig && !selectedHasError && !!s.instruction;

  return (
    <footer className="flex-shrink-0 flex items-center gap-md px-md py-sm border-t border-hairline bg-canvas">
      {s.phase === "pre-start" && (
        <>
          <span className="text-body-sm text-steel">Configure the inference session, then start.</span>
          <span className="flex-1" />
          <Button onClick={() => s.startSession()} disabled={!canStart}>
            Start session
          </Button>
        </>
      )}

      {s.phase === "ready" && (
        <>
          <span className="text-body-sm text-steel">Ready — start an episode when you're set.</span>
          <span className="flex-1" />
          <Button onClick={() => s.startEpisode()}>Start episode</Button>
        </>
      )}

      {s.phase === "recording" && (
        <>
          <Badge variant="destructive">⏺ {s.episodeElapsedSec.toFixed(1)}s</Badge>
          <span className="text-body-sm text-steel">REC · instruction locked</span>
          <span className="flex-1" />
          <Button variant="destructive" onClick={() => s.stopEpisode()}>⏹ Stop episode</Button>
        </>
      )}

      {s.phase === "review" && (
        <>
          <span className="text-body-sm text-steel">
            Episode
            {s.reviewEpisode && <> #{s.reviewEpisode.index} · {s.reviewEpisode.durationSec.toFixed(1)}s</>}
            {" ended."}
          </span>
          <span className="flex-1" />
          <Button onClick={() => s.commitEpisode(true)}>Save success</Button>
          <Button variant="outline" onClick={() => s.commitEpisode(false)}>Save failure</Button>
          <Button variant="ghost" onClick={() => s.discardEpisode()}>Discard</Button>
        </>
      )}
    </footer>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/inference/PhaseActionBar.tsx
git commit -m "feat(inference): add PhaseActionBar region"
```

---

### Task 1.5: Rewrite InferencePage to use the 3-column layout

**Files:**
- Modify: `frontend/src/pages/InferencePage.tsx` (full rewrite)

- [ ] **Step 1: Rewrite**

Replace the entire file with:

```tsx
import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { useInferenceStore } from "../state/inference-store";
import { useSessionStore } from "../state/session-store";
import { subscribeInferenceWS } from "../api/inference";
import { Badge } from "../components/ui/badge";
import { PageHeader } from "../components/ui/page-header";
import { SessionColumn } from "../components/inference/SessionColumn";
import { CameraColumn } from "../components/inference/CameraColumn";
import { TelemetryColumn } from "../components/inference/TelemetryColumn";
import { PhaseActionBar } from "../components/inference/PhaseActionBar";

export function InferencePage() {
  const s = useInferenceStore();
  const sessionState = useSessionStore((x) => x.state);
  const sessionRobot = useSessionStore((x) => x.robot);
  const sessionMode = useSessionStore((x) => x.mode);
  const wsCleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    s.loadConfigs();
    s.rehydrateFromBackend();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (s.phase === "pre-start") {
      wsCleanupRef.current?.();
      wsCleanupRef.current = null;
      return;
    }
    if (wsCleanupRef.current) return;
    wsCleanupRef.current = subscribeInferenceWS((e) => s.handleEvent(e));
    return () => {
      wsCleanupRef.current?.();
      wsCleanupRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.phase]);

  const isLive = s.phase === "ready" || s.phase === "recording";
  const sessionReadyForInference =
    sessionState === "ready" && sessionMode !== "inference";
  const sessionBlocker: string | null = (() => {
    if (sessionState === "idle") return "no-session";
    if (sessionState === "recording") return "recording";
    if (sessionState === "review") return "review";
    if (sessionMode === "inference") return "already-inference";
    return null;
  })();

  return (
    <>
      <PageHeader
        code="§03"
        title={
          <span className="flex items-baseline gap-md">
            Inference
            {isLive && <Badge variant="success">● live</Badge>}
          </span>
        }
        meta={
          sessionRobot && (
            <span className="font-mono text-micro text-stone">
              robot {sessionRobot}{sessionMode && ` · mode ${sessionMode}`}
            </span>
          )
        }
      />

      <div className="flex-1 flex flex-col min-h-0">
        {/* Error banner + session blockers (above 3-column area) */}
        {(s.error || (sessionBlocker && s.phase === "pre-start")) && (
          <div className="flex-shrink-0 px-md pt-sm space-y-2">
            {s.error && (
              <div className="rounded-md border border-brand-error/30 bg-brand-error/10 p-3 flex items-start justify-between gap-3">
                <div className="text-sm text-brand-error break-words">{s.error}</div>
                <button
                  onClick={() => s.setError(null)}
                  className="text-brand-error hover:text-brand-error text-lg leading-none"
                  aria-label="dismiss"
                >
                  ×
                </button>
              </div>
            )}
            {sessionBlocker && s.phase === "pre-start" && (
              <div className="rounded-md border border-brand-warn/30 bg-brand-warn/10 p-3 text-sm text-brand-warn">
                <SessionBlockerMessage kind={sessionBlocker} />
              </div>
            )}
          </div>
        )}

        {/* 3-column body */}
        <div className="flex-1 flex min-h-0">
          <SessionColumn disabled={s.phase === "pre-start" && !sessionReadyForInference} />
          <CameraColumn />
          <TelemetryColumn />
        </div>

        <PhaseActionBar canStartSession={sessionReadyForInference} />
      </div>
    </>
  );
}

function SessionBlockerMessage({ kind }: { kind: string }) {
  return (
    <div>
      <div className="font-medium mb-1">
        {kind === "no-session" && "⚠ No active session"}
        {kind === "recording" && "⚠ Session is recording"}
        {kind === "review" && "⚠ Session is in review"}
        {kind === "already-inference" && "⚠ Already in inference mode"}
      </div>
      <div>
        {kind === "no-session" && (
          <>
            The inference pipeline runs on top of an active robot session. Open the{" "}
            <Link to="/record" className="underline font-medium">Record page</Link> first
            to load a robot adapter, then come back here.
          </>
        )}
        {(kind === "recording" || kind === "review") && (
          <>
            Stop the current episode on the{" "}
            <Link to="/record" className="underline font-medium">Record page</Link> before
            starting an inference session.
          </>
        )}
        {kind === "already-inference" && (
          <>The page is rehydrating from the backend — refresh if it stays stuck.</>
        )}
      </div>
    </div>
  );
}
```

The named export `InferencePage` is preserved (App.tsx imports `{ InferencePage }`). The `max-w-[1100px]` wrapper, Field helper, and per-phase Card panels are gone.

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Fix any prop / type mismatches that surface (most likely places: telemetry slice shape, cameras slice shape).

- [ ] **Step 3: Manual verify**

Run the dev server, open `/inference`. Verify:
- No active session → blocker banner shows with link to Record.
- Active session + pre-start → SessionColumn shows config select + instruction input; PhaseActionBar shows "Start session" disabled until both filled.
- After Start → SessionColumn flips Config to readonly, CameraColumn shows live preview, TelemetryColumn populates; bar shows "Start episode".
- After Start episode → instruction shows "(locked)"; bar shows "⏺ Stop episode".
- After Stop episode → bar shows Save success / Save failure / Discard.
- Window resize: 3 columns hold their widths; only the center stretches.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/InferencePage.tsx
git commit -m "feat(inference): 3-column layout (settings / cameras / telemetry) + phase bar"
```

---

## Phase 2 — Episodes preview pane

### Task 2.1: useEpisodeThumbnail hook

**Files:**
- Create: `frontend/src/hooks/useEpisodeThumbnail.ts`

- [ ] **Step 1: Implement**

```ts
import { useEffect, useState } from "react";

const cache = new Map<string, string>(); // key: `${ds}:${idx}:${cam}` → dataURL
const MAX = 50;

/**
 * Generates a poster-frame thumbnail from the episode's video by mounting an
 * offscreen <video>, seeking to t=0.001, drawing it to a <canvas>, and caching
 * the resulting dataURL in memory. Avoids any backend writes and works
 * consistently across browsers (unlike <video preload="metadata">, which often
 * shows black until an explicit seek).
 *
 * Each effect run has its own local `cancelled` flag — a late event from a
 * superseded video (when the user clicks through episodes quickly) cannot
 * write into state. The previous thumbnail is cleared at the top of each
 * cache-miss to avoid showing a stale image during the new load.
 */
export function useEpisodeThumbnail(ds: string | undefined, idx: number | null, cam: string | undefined) {
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    if (!ds || idx == null || !cam) {
      setSrc(null);
      return;
    }
    const key = `${ds}:${idx}:${cam}`;
    const cached = cache.get(key);
    if (cached) {
      setSrc(cached);
      return;
    }

    // Cache miss → clear current src so the UI doesn't show the previously
    // selected episode's thumbnail while this one loads.
    setSrc(null);

    let cancelled = false;
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.crossOrigin = "anonymous";
    video.preload = "metadata";
    video.src = `/api/datasets/${ds}/episodes/${idx}/video/${cam}`;

    const onLoaded = () => {
      if (cancelled) return;
      try {
        video.currentTime = 0.001;
      } catch {
        finish(null);
      }
    };
    const onSeeked = () => {
      if (cancelled) return;
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth || 320;
      canvas.height = video.videoHeight || 180;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        finish(null);
        return;
      }
      try {
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const url = canvas.toDataURL("image/jpeg", 0.7);
        if (cache.size >= MAX) {
          const oldest = cache.keys().next().value as string | undefined;
          if (oldest) cache.delete(oldest);
        }
        cache.set(key, url);
        finish(url);
      } catch {
        // toDataURL throws if the canvas is tainted (cross-origin issues).
        finish(null);
      }
    };
    const onError = () => finish(null);

    function detachListeners() {
      video.removeEventListener("loadedmetadata", onLoaded);
      video.removeEventListener("seeked", onSeeked);
      video.removeEventListener("error", onError);
    }

    function finish(url: string | null) {
      detachListeners();
      // Release the network connection.
      video.removeAttribute("src");
      try { video.load(); } catch { /* ignore */ }
      if (!cancelled) setSrc(url);
    }

    video.addEventListener("loadedmetadata", onLoaded);
    video.addEventListener("seeked", onSeeked);
    video.addEventListener("error", onError);

    return () => {
      cancelled = true;
      detachListeners();
      video.removeAttribute("src");
      try { video.load(); } catch { /* ignore */ }
    };
  }, [ds, idx, cam]);

  return src;
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useEpisodeThumbnail.ts
git commit -m "feat(episodes): add useEpisodeThumbnail (offscreen video → canvas → cache)"
```

---

### Task 2.2: EpisodesFilterBar

**Files:**
- Create: `frontend/src/components/episodes/EpisodesFilterBar.tsx`

- [ ] **Step 1: Implement**

```tsx
import { Input } from "../ui/input";

export type StatusFilter = "all" | "success" | "failure";

interface Props {
  total: number;
  successCount: number;
  failureCount: number;
  status: StatusFilter;
  onStatusChange: (s: StatusFilter) => void;
  modes: Set<string>;             // empty = no mode filter
  availableModes: string[];
  onToggleMode: (mode: string) => void;
  search: string;
  onSearchChange: (q: string) => void;
}

export function EpisodesFilterBar({
  total, successCount, failureCount,
  status, onStatusChange,
  modes, availableModes, onToggleMode,
  search, onSearchChange,
}: Props) {
  return (
    <div className="flex-shrink-0 flex items-center gap-2 px-xl py-sm border-b border-hairline bg-canvas">
      <Chip active={status === "all"}     onClick={() => onStatusChange("all")}>All ({total})</Chip>
      <Chip active={status === "success"} edge="success" onClick={() => onStatusChange("success")}>Success ({successCount})</Chip>
      <Chip active={status === "failure"} edge="failure" onClick={() => onStatusChange("failure")}>Failure ({failureCount})</Chip>

      {availableModes.length > 0 && (
        <>
          <span className="text-hairline">|</span>
          {availableModes.map((m) => (
            <Chip key={m} active={modes.has(m)} onClick={() => onToggleMode(m)}>{m}</Chip>
          ))}
        </>
      )}

      <Input
        placeholder="Search task…"
        value={search}
        onChange={(e) => onSearchChange(e.target.value)}
        className="ml-auto w-[200px]"
      />
    </div>
  );
}

function Chip({
  active, edge, onClick, children,
}: {
  active: boolean;
  edge?: "success" | "failure";
  onClick: () => void;
  children: React.ReactNode;
}) {
  const edgeClass =
    edge === "success" ? "border-l-[3px] border-l-brand-green-deep pl-[7px]"
  : edge === "failure" ? "border-l-[3px] border-l-brand-error pl-[7px]"
  : "";
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        `text-caption rounded-full px-3 py-1 border transition-colors ${edgeClass} ` +
        (active
          ? "bg-ink text-on-primary border-ink"
          : "bg-canvas text-slate border-hairline hover:border-stone")
      }
    >
      {children}
    </button>
  );
}
```

- [ ] **Step 2: Typecheck + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/components/episodes/EpisodesFilterBar.tsx
git commit -m "feat(episodes): add filter chip bar"
```

---

### Task 2.3: EpisodesList (compact rows)

**Files:**
- Create: `frontend/src/components/episodes/EpisodesList.tsx`

- [ ] **Step 1: Implement**

```tsx
import type { EpisodeSummary } from "../../api/types";

interface Props {
  episodes: EpisodeSummary[];
  selectedIdx: number | null;
  onSelect: (idx: number) => void;
}

export function EpisodesList({ episodes, selectedIdx, onSelect }: Props) {
  if (episodes.length === 0) {
    return <p className="text-steel p-md">No episodes match the current filter.</p>;
  }

  return (
    <ul className="flex-1 min-h-0 overflow-auto" role="listbox">
      {episodes.map((ep) => {
        const isSel = ep.episode_index === selectedIdx;
        return (
          <li
            key={ep.episode_index}
            role="option"
            aria-selected={isSel}
            onClick={() => onSelect(ep.episode_index)}
            className={
              "grid grid-cols-[56px_1fr_60px_38px_80px] gap-md items-center px-xl py-sm border-b border-hairline-soft cursor-pointer transition-colors " +
              (isSel ? "bg-surface" : "hover:bg-surface-soft")
            }
          >
            <span className="font-mono text-caption text-stone tabular-nums">#{ep.display_index}</span>
            <span className="text-body-sm text-ink truncate">{ep.task}</span>
            <span className="font-mono text-caption text-steel tabular-nums">{ep.duration_sec.toFixed(1)}s</span>
            <StatusGlyph success={ep.success} />
            <span className="text-caption text-steel truncate">{ep.mode}</span>
          </li>
        );
      })}
    </ul>
  );
}

function StatusGlyph({ success }: { success: boolean | null }) {
  if (success === true)  return <span className="text-brand-green-deep font-semibold">✓</span>;
  if (success === false) return <span className="text-brand-error font-semibold">✗</span>;
  return <span className="text-stone">—</span>;
}
```

If `Episode` type doesn't have those fields exactly, adapt — read `frontend/src/api/types.ts`.

- [ ] **Step 2: Typecheck + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/components/episodes/EpisodesList.tsx
git commit -m "feat(episodes): add compact selectable list"
```

---

### Task 2.4: MiniJointPlot

**Files:**
- Create: `frontend/src/components/episodes/MiniJointPlot.tsx`

- [ ] **Step 1: Implement**

```tsx
import { useMemo } from "react";
import { useEpisodeFrames } from "../../hooks/useEpisodeFrames";

interface Props {
  ds: string;
  idx: number;
}

const TRACE_COLORS = ["#3772cf", "#d45656", "#00b48a", "#5a5a5c", "#c37d0d", "#888888"];

export function MiniJointPlot({ ds, idx }: Props) {
  const { data: rows = [] } = useEpisodeFrames(ds, idx);

  const { traces, gripper, n } = useMemo(() => {
    if (!rows.length) return { traces: [] as number[][], gripper: [] as number[], n: 0 };
    const nJoints = (rows[0]["observation.state.joint_pos"] as number[] | undefined)?.length ?? 0;
    const out: number[][] = Array.from({ length: Math.min(nJoints, 6) }, () => []);
    const grip: number[] = [];
    for (const r of rows) {
      const pos = r["observation.state.joint_pos"] as number[] | undefined;
      if (!pos) continue;
      for (let i = 0; i < out.length; i++) out[i].push(pos[i]);
      const g = (r["action.gripper_pos"] ?? r["observation.gripper_pos"]) as number | undefined;
      grip.push(typeof g === "number" ? g : NaN);
    }
    return { traces: out, gripper: grip, n: rows.length };
  }, [rows]);

  if (n === 0) return <Empty />;

  return (
    <svg viewBox="0 0 200 44" preserveAspectRatio="none" className="w-full h-[44px] block">
      {traces.map((tr, i) => (
        <polyline key={i} points={pathPoints(tr, n)} stroke={TRACE_COLORS[i % TRACE_COLORS.length]} strokeWidth="0.9" fill="none" />
      ))}
      {gripper.some((g) => !Number.isNaN(g)) && (
        <polyline points={pathPoints(gripper, n)} stroke="var(--color-ink)" strokeWidth="0.9" strokeDasharray="2 2" fill="none" />
      )}
    </svg>
  );
}

function pathPoints(values: number[], n: number): string {
  if (!values.length) return "";
  const min = Math.min(...values.filter(Number.isFinite));
  const max = Math.max(...values.filter(Number.isFinite));
  const range = max - min || 1;
  const out: string[] = [];
  for (let i = 0; i < values.length; i++) {
    const x = (i / Math.max(1, n - 1)) * 200;
    const v = Number.isFinite(values[i]) ? values[i] : (min + max) / 2;
    const y = 42 - ((v - min) / range) * 38 - 2;
    out.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  return out.join(" ");
}

function Empty() {
  return <div className="h-[44px] flex items-center justify-center text-stone text-caption">—</div>;
}
```

- [ ] **Step 2: Typecheck + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/components/episodes/MiniJointPlot.tsx
git commit -m "feat(episodes): add MiniJointPlot sparkline"
```

---

### Task 2.5: MiniEePlot

**Files:**
- Create: `frontend/src/components/episodes/MiniEePlot.tsx`

- [ ] **Step 1: Implement**

```tsx
import { useMemo } from "react";
import { useEpisodeFrames } from "../../hooks/useEpisodeFrames";

interface Props {
  ds: string;
  idx: number;
}

export function MiniEePlot({ ds, idx }: Props) {
  const { data: rows = [] } = useEpisodeFrames(ds, idx);

  // Backend writes EE position as a 3-vector under "observation.state.ee_pos"
  // (see backend/mimicrec/recording/parquet_row.py). Element 0 = x, 1 = y, 2 = z.
  const points = useMemo(() => {
    const xs: number[] = [];
    const ys: number[] = [];
    for (const r of rows) {
      const ee = r["observation.state.ee_pos"];
      if (Array.isArray(ee) && typeof ee[0] === "number" && typeof ee[1] === "number") {
        xs.push(ee[0] as number);
        ys.push(ee[1] as number);
      }
    }
    return { xs, ys };
  }, [rows]);

  if (points.xs.length === 0) {
    return <div className="aspect-[1.5] bg-surface-soft border border-hairline-soft rounded-sm flex items-center justify-center text-stone text-caption">—</div>;
  }

  const minX = Math.min(...points.xs);
  const maxX = Math.max(...points.xs);
  const minY = Math.min(...points.ys);
  const maxY = Math.max(...points.ys);
  const rngX = maxX - minX || 1;
  const rngY = maxY - minY || 1;
  const W = 100;
  const H = 70;
  const path = points.xs
    .map((x, i) => {
      const px = ((x - minX) / rngX) * (W - 10) + 5;
      const py = H - (((points.ys[i] - minY) / rngY) * (H - 10) + 5);
      return `${i === 0 ? "M" : "L"}${px.toFixed(1)},${py.toFixed(1)}`;
    })
    .join(" ");
  const start = { x: ((points.xs[0] - minX) / rngX) * (W - 10) + 5, y: H - (((points.ys[0] - minY) / rngY) * (H - 10) + 5) };
  const end = {
    x: ((points.xs.at(-1)! - minX) / rngX) * (W - 10) + 5,
    y: H - (((points.ys.at(-1)! - minY) / rngY) * (H - 10) + 5),
  };

  return (
    <div className="aspect-[1.5] bg-surface-soft border border-hairline-soft rounded-sm relative">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 w-full h-full">
        <line x1={W / 2} y1="0" x2={W / 2} y2={H} stroke="var(--color-hairline-soft)" strokeWidth="0.4" />
        <line x1="0" y1={H / 2} x2={W} y2={H / 2} stroke="var(--color-hairline-soft)" strokeWidth="0.4" />
        <path d={path} stroke="var(--color-brand-tag)" strokeWidth="1.3" fill="none" />
        <circle cx={start.x} cy={start.y} r="2" fill="var(--color-brand-green-deep)" />
        <circle cx={end.x} cy={end.y} r="2" fill="var(--color-brand-error)" />
      </svg>
    </div>
  );
}
```

If EE position keys in your dataset are different, adjust the `r["observation.ee_pos.x"]` lookups to match. Grep `frontend/src/components/EndEffectorPlot.tsx` for the existing key names if unsure.

- [ ] **Step 2: Typecheck + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/components/episodes/MiniEePlot.tsx
git commit -m "feat(episodes): add MiniEePlot XY trajectory"
```

---

### Task 2.6: EpisodePreviewPane

**Files:**
- Create: `frontend/src/components/episodes/EpisodePreviewPane.tsx`

- [ ] **Step 1: Implement**

```tsx
import { useNavigate } from "react-router-dom";
import type { EpisodeSummary } from "../../api/types";
import { Button } from "../ui/button";
import { useEpisodeThumbnail } from "../../hooks/useEpisodeThumbnail";
import { MiniJointPlot } from "./MiniJointPlot";
import { MiniEePlot } from "./MiniEePlot";

interface Props {
  ds: string;
  episode: EpisodeSummary | null;
  onDelete: (idx: number) => void;
}

export function EpisodePreviewPane({ ds, episode, onDelete }: Props) {
  const navigate = useNavigate();
  const masterCam = episode?.cameras?.[0];
  const thumb = useEpisodeThumbnail(ds, episode?.episode_index ?? null, masterCam);

  if (!episode) {
    return (
      <aside className="w-[360px] flex-shrink-0 border-l border-hairline bg-canvas p-md text-stone text-body-sm">
        Select an episode to preview.
      </aside>
    );
  }

  const open = () => navigate(`/datasets/${ds}/episodes/${episode.episode_index}/replay`);

  return (
    <aside className="w-[360px] flex-shrink-0 border-l border-hairline bg-canvas p-md overflow-auto flex flex-col gap-md">
      <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
        Preview · #{episode.display_index}
      </div>

      <div className="aspect-video bg-surface-code rounded-sm relative overflow-hidden cursor-pointer" onClick={open}>
        {thumb ? (
          <img src={thumb} alt="" className="absolute inset-0 w-full h-full object-cover" />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-stone text-caption">loading…</div>
        )}
        <div className="absolute top-1 left-2 font-mono text-[10px] text-on-dark-muted bg-black/55 px-1 py-0.5 rounded-sm">
          {episode.duration_sec.toFixed(1)}s · {episode.num_frames}f
        </div>
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-9 h-9 rounded-full bg-white/15 flex items-center justify-center text-on-dark">▶</div>
        </div>
      </div>

      <div className="border-y border-hairline-soft py-1 space-y-0.5">
        <Fact k="Task"        v={episode.task} />
        <Fact k="Duration"    v={`${episode.duration_sec.toFixed(1)}s · ${episode.num_frames} frames`} mono />
        <Fact k="Status"      v={episode.success === true ? "Success" : episode.success === false ? "Failure" : "—"}
              color={episode.success === true ? "text-brand-green-deep" : episode.success === false ? "text-brand-error" : "text-stone"} />
        <Fact k="Mode · robot" v={`${episode.mode} · ${episode.robot ?? "—"}`} mono />
        <Fact k="Recorded"    v={episode.recorded_at || "—"} mono />
      </div>

      <div className="border border-hairline rounded-sm p-2">
        <div className="flex items-center justify-between text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold mb-1">
          <span>Joint trajectory</span>
          <span className="font-mono text-[10px] text-muted">j1–j6 + grip</span>
        </div>
        <MiniJointPlot ds={ds} idx={episode.episode_index} />
      </div>

      <div className="border border-hairline rounded-sm p-2">
        <div className="flex items-center justify-between text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold mb-1">
          <span>End-Effector · XY</span>
          <span className="font-mono text-[10px] text-muted">top-down</span>
        </div>
        <MiniEePlot ds={ds} idx={episode.episode_index} />
      </div>

      <div className="flex gap-2 mt-auto">
        <Button onClick={open} className="flex-1">▶ Open replay</Button>
        <Button variant="destructive" size="sm" onClick={() => onDelete(episode.episode_index)}>
          Delete
        </Button>
      </div>
    </aside>
  );
}

function Fact({ k, v, mono, color = "text-ink" }: { k: string; v: React.ReactNode; mono?: boolean; color?: string }) {
  return (
    <div className="flex items-baseline justify-between text-caption">
      <span className="text-micro-uppercase uppercase tracking-[0.5px] text-stone font-semibold">{k}</span>
      <span className={`${color} ${mono ? "font-mono" : ""}`}>{v}</span>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/components/episodes/EpisodePreviewPane.tsx
git commit -m "feat(episodes): add EpisodePreviewPane (thumb + facts + mini plots)"
```

---

### Task 2.7: Rewrite EpisodesPage to use the split layout

**Files:**
- Modify: `frontend/src/pages/EpisodesPage.tsx` (full rewrite)

- [ ] **Step 1: Rewrite**

```tsx
import { useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useEpisodes, useDeleteEpisode } from "../api/queries";
import { CodeInline } from "../components/ui/code-inline";
import { PageHeader } from "../components/ui/page-header";
import { EpisodesFilterBar, type StatusFilter } from "../components/episodes/EpisodesFilterBar";
import { EpisodesList } from "../components/episodes/EpisodesList";
import { EpisodePreviewPane } from "../components/episodes/EpisodePreviewPane";

export default function EpisodesPage() {
  const { ds } = useParams<{ ds: string }>();
  const { data: episodes = [], isLoading } = useEpisodes(ds || "");
  const deleteMutation = useDeleteEpisode(ds || "");

  const [status, setStatus] = useState<StatusFilter>("all");
  const [modes, setModes] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);

  const availableModes = useMemo(
    () => Array.from(new Set(episodes.map((e) => e.mode).filter(Boolean))) as string[],
    [episodes],
  );

  const filtered = useMemo(() => {
    return episodes.filter((e) => {
      if (status === "success" && e.success !== true) return false;
      if (status === "failure" && e.success !== false) return false;
      if (modes.size > 0 && !modes.has(e.mode)) return false;
      if (search && !e.task.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [episodes, status, modes, search]);

  // Auto-select first in filtered list when selection becomes invalid
  const effectiveSel = useMemo(() => {
    if (selectedIdx != null && filtered.some((e) => e.episode_index === selectedIdx)) return selectedIdx;
    return filtered[0]?.episode_index ?? null;
  }, [filtered, selectedIdx]);

  const selectedEpisode = filtered.find((e) => e.episode_index === effectiveSel) ?? null;

  const successCount = episodes.filter((e) => e.success === true).length;
  const failureCount = episodes.filter((e) => e.success === false).length;

  const toggleMode = (m: string) => {
    setModes((prev) => {
      const next = new Set(prev);
      if (next.has(m)) next.delete(m); else next.add(m);
      return next;
    });
  };

  if (!ds) return <div className="p-xl">No dataset selected</div>;

  return (
    <>
      <PageHeader
        code="§01.B"
        title={
          <span className="flex items-baseline gap-md">
            Episodes
            <span className="text-steel">·</span>
            <CodeInline>{ds}</CodeInline>
          </span>
        }
        meta={
          <span className="font-mono text-micro text-stone">
            {episodes.length} episodes · {successCount} ok / {failureCount} failed
          </span>
        }
        actions={
          <Link to="/datasets" className="text-caption text-steel hover:text-ink">
            ← Datasets
          </Link>
        }
      />

      <EpisodesFilterBar
        total={episodes.length}
        successCount={successCount}
        failureCount={failureCount}
        status={status} onStatusChange={setStatus}
        modes={modes} availableModes={availableModes} onToggleMode={toggleMode}
        search={search} onSearchChange={setSearch}
      />

      <div className="flex-1 flex min-h-0">
        {isLoading ? (
          <p className="text-steel p-md">Loading…</p>
        ) : (
          <>
            <div className="flex-1 min-w-0 flex flex-col border-r border-hairline">
              <EpisodesList
                episodes={filtered}
                selectedIdx={effectiveSel}
                onSelect={setSelectedIdx}
              />
            </div>
            <EpisodePreviewPane
              ds={ds}
              episode={selectedEpisode}
              onDelete={(idx) => {
                if (confirm(`Delete episode #${selectedEpisode?.display_index ?? idx}?`)) {
                  deleteMutation.mutate(idx);
                }
              }}
            />
          </>
        )}
      </div>
    </>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: Manual verify**

Run dev server, navigate to a dataset with multiple episodes. Verify:
- All filter chips toggle correctly. Counts always reflect unfiltered totals.
- Selection updates the right pane within ~200ms.
- Thumbnail appears after a brief load (first selection), instantly on re-select (cache).
- Mini joint plot and EE XY render in the right pane.
- **Rapid selection regression**: click rapidly through 4-5 different episodes before any of them finish loading. The right pane should never show a stale thumbnail belonging to a previous selection; it shows "loading…" then the correct image for the current selection.
- **Frame data sharing**: navigate from Episodes (preview pane loaded) to Replay for the same episode. Network tab should show no second request to `/frames` — React Query's cache serves it.
- "Open replay" navigates to the existing Replay page; "Delete" prompts and deletes.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/EpisodesPage.tsx
git commit -m "feat(episodes): split layout (filter bar + compact list + preview pane)"
```

---

## Phase 3 — Replay synchronized timeline

### Task 3.1: VideoPlayer accepts ref + isMaster + onTimeUpdate

**Files:**
- Modify: `frontend/src/components/VideoPlayer.tsx`

- [ ] **Step 1: Update**

Replace the file with:

```tsx
import { forwardRef, useState } from "react";

interface Props {
  ds: string;
  idx: number;
  cam: string;
  /** Master video gets default controls. Secondaries get `controls={false}`
   *  and a transparent overlay that swallows pointer events.
   *  (Timeline state is driven from useEpisodeTimeline reading directly from
   *  the master video's ref via rVFC/timeupdate — VideoPlayer itself doesn't
   *  emit time updates.) */
  isMaster?: boolean;
}

const VideoPlayer = forwardRef<HTMLVideoElement, Props>(function VideoPlayer(
  { ds, idx, cam, isMaster = true },
  ref,
) {
  const [error, setError] = useState(false);
  const src = `/api/datasets/${ds}/episodes/${idx}/video/${cam}`;

  return (
    <div className="rounded-lg overflow-hidden border border-hairline bg-canvas">
      <div className="relative bg-black aspect-square">
        {error ? (
          <div className="absolute inset-0 flex items-center justify-center text-steel text-sm">
            Video unavailable for {cam}
          </div>
        ) : (
          <>
            <video
              ref={ref}
              className="absolute inset-0 w-full h-full object-contain"
              controls={isMaster}
              src={src}
              onError={() => setError(true)}
            />
            {!isMaster && (
              <div
                className="absolute inset-0 cursor-default"
                onClick={(e) => e.preventDefault()}
                aria-hidden
              />
            )}
          </>
        )}
      </div>
      <div className="px-2 py-1 text-caption text-stone bg-surface">{cam}</div>
    </div>
  );
});

export default VideoPlayer;
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/VideoPlayer.tsx
git commit -m "feat(replay): VideoPlayer accepts ref + isMaster"
```

---

### Task 3.2: useEpisodeTimeline hook

**Files:**
- Create: `frontend/src/hooks/useEpisodeTimeline.ts`

- [ ] **Step 1: Implement**

```ts
import { useEffect, useRef, useState, useCallback, type RefObject } from "react";

interface VideoFrameCallbackMetadata {
  mediaTime: number;
  presentedFrames: number;
}

interface VideoWithRVFC extends HTMLVideoElement {
  requestVideoFrameCallback?: (cb: (now: number, meta: VideoFrameCallbackMetadata) => void) => number;
  cancelVideoFrameCallback?: (handle: number) => void;
}

/**
 * Master timeline state for synchronized playback. The master <video>'s
 * playback drives `currentTimeSec` via rVFC (or `timeupdate` fallback). The
 * `seek(t)` function is the *only* way callers should change the master's
 * position — it calls `video.currentTime = t`, and the rVFC/`timeupdate`
 * callback propagates the change back into state. This single-writer
 * invariant prevents the scrubber/state/seek feedback loop described in
 * the design spec.
 */
export function useEpisodeTimeline(masterRef: RefObject<HTMLVideoElement | null>) {
  const [currentTimeSec, setCurrentTimeSec] = useState(0);
  const rvfcHandleRef = useRef<number | null>(null);

  useEffect(() => {
    const video = masterRef.current as VideoWithRVFC | null;
    if (!video) return;

    if (typeof video.requestVideoFrameCallback === "function") {
      const onFrame = (_now: number, meta: VideoFrameCallbackMetadata) => {
        setCurrentTimeSec(meta.mediaTime);
        rvfcHandleRef.current = video.requestVideoFrameCallback!(onFrame);
      };
      rvfcHandleRef.current = video.requestVideoFrameCallback(onFrame);
      return () => {
        if (rvfcHandleRef.current != null && video.cancelVideoFrameCallback) {
          video.cancelVideoFrameCallback(rvfcHandleRef.current);
        }
      };
    }

    // Fallback: timeupdate (4–15 Hz). Chunky but functional.
    const onTimeUpdate = () => setCurrentTimeSec(video.currentTime);
    video.addEventListener("timeupdate", onTimeUpdate);
    return () => video.removeEventListener("timeupdate", onTimeUpdate);
  }, [masterRef]);

  const seek = useCallback((t: number) => {
    const video = masterRef.current;
    if (!video) return;
    // Setting currentTime triggers a seek → eventually the rVFC/timeupdate
    // callback writes the new value into state. Do NOT setCurrentTimeSec(t)
    // here — that would create a second writer.
    video.currentTime = Math.max(0, t);
  }, [masterRef]);

  return { currentTimeSec, seek };
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useEpisodeTimeline.ts
git commit -m "feat(replay): useEpisodeTimeline (rVFC + timeupdate, single-writer)"
```

---

### Task 3.3: useSecondaryVideoSync hook

**Files:**
- Create: `frontend/src/hooks/useSecondaryVideoSync.ts`

- [ ] **Step 1: Implement**

```ts
import { useEffect, type RefObject } from "react";

/**
 * Slaves a secondary <video> to a master <video>:
 *   - mirrors play/pause/rate/ended events from master
 *   - mirrors seeks via guarded currentTime writes (readyState + !seeking +
 *     > 1/fps drift threshold) to prevent seek storms when the master is
 *     emitting per-frame timeupdates.
 */
export function useSecondaryVideoSync(
  secondaryRef: RefObject<HTMLVideoElement | null>,
  masterRef: RefObject<HTMLVideoElement | null>,
  currentTimeSec: number,
  fps: number,
) {
  // Mirror play/pause/rate
  useEffect(() => {
    const master = masterRef.current;
    const secondary = secondaryRef.current;
    if (!master || !secondary) return;

    const onPlay = () => secondary.play().catch(() => {});
    const onPause = () => secondary.pause();
    const onRate = () => { secondary.playbackRate = master.playbackRate; };
    const onEnded = () => secondary.pause();

    master.addEventListener("play", onPlay);
    master.addEventListener("pause", onPause);
    master.addEventListener("ratechange", onRate);
    master.addEventListener("ended", onEnded);

    // Initial sync
    secondary.playbackRate = master.playbackRate;
    if (!master.paused) secondary.play().catch(() => {});

    return () => {
      master.removeEventListener("play", onPlay);
      master.removeEventListener("pause", onPause);
      master.removeEventListener("ratechange", onRate);
      master.removeEventListener("ended", onEnded);
    };
  }, [masterRef, secondaryRef]);

  // Mirror seeks (guarded)
  useEffect(() => {
    const secondary = secondaryRef.current;
    if (!secondary) return;
    if (secondary.readyState < 1 /* HAVE_METADATA */) return;
    if (secondary.seeking) return;
    const frameTime = 1 / Math.max(1, fps);
    if (Math.abs(secondary.currentTime - currentTimeSec) <= frameTime) return;
    secondary.currentTime = currentTimeSec;
  }, [secondaryRef, currentTimeSec, fps]);
}
```

- [ ] **Step 2: Typecheck + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/hooks/useSecondaryVideoSync.ts
git commit -m "feat(replay): useSecondaryVideoSync (guarded mirror of master)"
```

---

### Task 3.4: Scrubber component

**Files:**
- Create: `frontend/src/components/Scrubber.tsx`

- [ ] **Step 1: Implement**

```tsx
interface Props {
  durationSec: number;
  currentTimeSec: number;
  onSeek: (t: number) => void;
}

export function Scrubber({ durationSec, currentTimeSec, onSeek }: Props) {
  const fraction = durationSec > 0 ? Math.min(1, Math.max(0, currentTimeSec / durationSec)) : 0;

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const fx = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    onSeek(fx * durationSec);
  };

  const handleDrag = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.buttons === 0) return; // not dragging
    handleClick(e);
  };

  return (
    <div className="flex-shrink-0 h-9 px-md flex items-center gap-md border-t border-hairline-soft bg-surface-soft">
      <span className="font-mono text-caption text-steel min-w-[44px]">00:00</span>
      <div
        className="flex-1 h-1 bg-hairline rounded-full relative cursor-pointer"
        onClick={handleClick}
        onMouseMove={handleDrag}
      >
        <div className="absolute left-0 top-0 bottom-0 bg-ink rounded-full" style={{ width: `${fraction * 100}%` }} />
        <div
          className="absolute -top-1.5 w-3 h-3 -translate-x-1/2 rounded-full bg-canvas border-2 border-ink"
          style={{ left: `${fraction * 100}%` }}
        />
      </div>
      <span className="font-mono text-caption text-steel min-w-[88px] text-right">
        {fmt(currentTimeSec)} / {fmt(durationSec)}
      </span>
    </div>
  );
}

function fmt(sec: number): string {
  const mm = Math.floor(sec / 60).toString().padStart(2, "0");
  const ss = (sec % 60).toFixed(1).padStart(4, "0");
  return `${mm}:${ss}`;
}
```

- [ ] **Step 2: Typecheck + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/components/Scrubber.tsx
git commit -m "feat(replay): Scrubber component (master timeline)"
```

---

### Task 3.5: JointPlot — cursor + click-anywhere seek via overlay

The spec requires *click-anywhere* seek on the joint plot (not snapping to data points). Recharts' `onClick` returns `activeLabel`/`activePayload` that snap to the nearest data point, so it doesn't satisfy the requirement reliably. The robust pattern is an absolutely-positioned transparent `<div>` over the plot area that captures clicks and computes time from its own known pixel bounds. We also need to switch the chart's X-axis to numeric mode so the `<ReferenceLine>` positions correctly along the continuous time domain.

**Files:**
- Modify: `frontend/src/components/JointPlot.tsx`

- [ ] **Step 1: Make the time axis continuous**

In the existing chart JSX, find the `<XAxis>` and ensure it has:

```tsx
<XAxis
  dataKey="time"
  type="number"
  domain={["dataMin", "dataMax"]}
  tickFormatter={(t: number) => `${t.toFixed(1)}s`}
  /* keep any other existing props */
/>
```

If `<XAxis dataKey="time" />` was the existing form (categorical), this change converts it to numeric. Verify the visible plot ticks still look reasonable after the change.

- [ ] **Step 2: Add `cursorTimeSec` + `onSeek` props**

```tsx
interface Props {
  ds: string;
  idx: number;
  cursorTimeSec?: number;
  onSeek?: (timeSec: number) => void;
}
```

Import `ReferenceLine`:

```tsx
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
```

Inside the `<LineChart>` JSX, add (after `<CartesianGrid>`):

```tsx
{typeof cursorTimeSec === "number" && (
  <ReferenceLine
    x={cursorTimeSec}
    stroke="var(--color-ink)"
    strokeOpacity={0.7}
    ifOverflow="visible"
  />
)}
```

- [ ] **Step 3: Wrap the chart in a positioned container with a click overlay**

Replace the existing `<ResponsiveContainer>…</ResponsiveContainer>` render with:

```tsx
const tMin = data[0]?.time ?? 0;
const tMax = data[data.length - 1]?.time ?? 0;
const overlayRef = useRef<HTMLDivElement | null>(null);

const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
  if (!onSeek || tMax <= tMin) return;
  const rect = overlayRef.current?.getBoundingClientRect();
  if (!rect) return;
  // Recharts 3.x default LineChart left margin is 20 / right is 30. If you've
  // overridden margins on the LineChart, mirror those here. With unchanged
  // defaults this gives accurate click-anywhere seek.
  const LEFT = 20;
  const RIGHT = 30;
  const plotWidth = Math.max(1, rect.width - LEFT - RIGHT);
  const px = e.clientX - rect.left - LEFT;
  const fraction = Math.min(1, Math.max(0, px / plotWidth));
  onSeek(tMin + fraction * (tMax - tMin));
};

return (
  <div className="relative w-full h-full">
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} /* ... existing props ... */>
        {/* ... existing children + the new <ReferenceLine /> ... */}
      </LineChart>
    </ResponsiveContainer>
    {/* Click-anywhere seek overlay. Pointer-events on the overlay only when
        onSeek is provided. The overlay sits ABOVE the chart but ALLOWS Recharts'
        own hover tooltip to keep working by setting pointer-events: none on
        mousemove, then toggling back on click. We accept that hover-tooltips
        and click-seek are mutually exclusive on the same surface — clicks win. */}
    {onSeek && (
      <div
        ref={overlayRef}
        className="absolute inset-0 cursor-crosshair"
        onClick={handleClick}
        aria-hidden
      />
    )}
  </div>
);
```

Don't pass `onClick` to `<LineChart>` itself.

The tradeoff above (overlay defeats Recharts' native hover tooltip on the joint plot when `onSeek` is provided) is acceptable per the spec — hover tooltips are a nice-to-have on Replay, and click-to-seek is the primary requirement.

- [ ] **Step 4: Typecheck + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/components/JointPlot.tsx
git commit -m "feat(replay): JointPlot cursor + click-anywhere seek via overlay"
```

---

### Task 3.6: Convert EndEffectorPlot to XY view with cursor dot

The current `EndEffectorPlot.tsx` is a time-series Recharts `LineChart` showing EE x/y/z + gripper over time. The spec calls for an XY (top-down) trajectory on Replay, with start/end dots and a current-position cursor dot. This task replaces the rendered chart entirely — the data-loading via `useEpisodeFrames` is preserved.

**Files:**
- Modify: `frontend/src/components/EndEffectorPlot.tsx` (rewrite render half)

- [ ] **Step 1: Rewrite the component**

Replace the file with (preserving the data-loading from Task 0.2's migration):

```tsx
import { useMemo } from "react";
import { useEpisodeFrames } from "../hooks/useEpisodeFrames";

interface Props {
  ds: string;
  idx: number;
  cursorFrameIdx?: number;
}

// Backend writes EE position as a 3-vector "observation.state.ee_pos"
// (parquet row produced in backend/mimicrec/recording/parquet_row.py).
// We use [0]=x, [1]=y for the top-down trajectory.
const EE_KEY = "observation.state.ee_pos";

export default function EndEffectorPlot({ ds, idx, cursorFrameIdx }: Props) {
  const { data: rows = [], isLoading: loading } = useEpisodeFrames(ds, idx);

  const { xs, ys } = useMemo(() => {
    const xArr: number[] = [];
    const yArr: number[] = [];
    for (const r of rows) {
      const ee = r[EE_KEY];
      if (Array.isArray(ee) && typeof ee[0] === "number" && typeof ee[1] === "number") {
        xArr.push(ee[0] as number);
        yArr.push(ee[1] as number);
      }
    }
    return { xs: xArr, ys: yArr };
  }, [rows]);

  if (loading) return <p className="text-stone p-4">Loading chart...</p>;
  if (xs.length === 0) {
    return <p className="text-stone p-4">No EE position data for this episode.</p>;
  }

  // Domain bounds with 5% padding
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const padX = (maxX - minX) * 0.05 || 0.01;
  const padY = (maxY - minY) * 0.05 || 0.01;
  const xLo = minX - padX, xHi = maxX + padX;
  const yLo = minY - padY, yHi = maxY + padY;
  const rngX = xHi - xLo || 1;
  const rngY = yHi - yLo || 1;

  // ViewBox is fixed; we let the SVG scale via preserveAspectRatio.
  const W = 200;
  const H = 140;
  const project = (x: number, y: number) => ({
    px: ((x - xLo) / rngX) * W,
    // Flip Y so positive Y goes up on screen.
    py: H - ((y - yLo) / rngY) * H,
  });

  const path = xs
    .map((x, i) => {
      const { px, py } = project(x, ys[i]);
      return `${i === 0 ? "M" : "L"}${px.toFixed(2)},${py.toFixed(2)}`;
    })
    .join(" ");

  const start = project(xs[0], ys[0]);
  const end = project(xs[xs.length - 1], ys[ys.length - 1]);

  const cursorIdx =
    typeof cursorFrameIdx === "number"
      ? Math.min(Math.max(cursorFrameIdx, 0), xs.length - 1)
      : null;
  const cursor = cursorIdx != null ? project(xs[cursorIdx], ys[cursorIdx]) : null;

  return (
    <div className="w-full h-full min-h-0 bg-surface-soft rounded-sm relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
        className="absolute inset-0 w-full h-full"
        aria-label="End-effector XY trajectory"
      >
        {/* Origin crosshair (mid-domain) */}
        <line x1={W / 2} y1={0} x2={W / 2} y2={H} stroke="var(--color-hairline-soft)" strokeWidth="0.4" />
        <line x1={0} y1={H / 2} x2={W} y2={H / 2} stroke="var(--color-hairline-soft)" strokeWidth="0.4" />

        {/* Trajectory */}
        <path d={path} stroke="var(--color-brand-tag)" strokeWidth="1.2" fill="none" />

        {/* Start / end markers */}
        <circle cx={start.px} cy={start.py} r="2.4" fill="var(--color-brand-green-deep)" />
        <circle cx={end.px}   cy={end.py}   r="2.4" fill="var(--color-brand-error)" />

        {/* Cursor (current frame position) */}
        {cursor && (
          <circle cx={cursor.px} cy={cursor.py} r="2.6" fill="var(--color-ink)" stroke="var(--color-canvas)" strokeWidth="0.8" />
        )}
      </svg>

      {/* Legend */}
      <div className="absolute bottom-1 right-2 flex items-center gap-2 font-mono text-[10px] text-stone bg-canvas/80 px-1.5 py-0.5 rounded-sm">
        <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-brand-green-deep" /> start</span>
        <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-brand-error" /> end</span>
      </div>
    </div>
  );
}
```

Key choice rationale: the existing time-series `EndEffectorPlot` (pre-rewrite) only reads `observation.state.gripper_pos` and `action.gripper_pos` — it does *not* expose any EE-XYZ data today. The new XY view pulls the actual end-effector position from `observation.state.ee_pos`, which is written by `backend/mimicrec/recording/parquet_row.py` whenever the adapter provides forward kinematics. Episodes without FK (e.g. an adapter that left `ee_pos = None`) won't have this column and the component will fall through to the "No EE position data" path.

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/EndEffectorPlot.tsx
git commit -m "feat(replay): rewrite EndEffectorPlot as XY view with cursor dot"
```

Note: this drops the time-series view of EE (x/y/z + gripper over time) that the page used to show. If preserving that view is also wanted, a follow-up can add it as a tab next to the XY view — out of scope for this plan.

---

### Task 3.7: Rewrite ReplayPage with synced timeline

**Files:**
- Modify: `frontend/src/pages/ReplayPage.tsx` (full rewrite)

- [ ] **Step 1: Rewrite**

```tsx
import { useMemo, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import { useEpisodes, useReplayStart, useReplayStop } from "../api/queries";
import { useSessionStore } from "../state/session-store";
import VideoPlayer from "../components/VideoPlayer";
import JointPlot from "../components/JointPlot";
import EndEffectorPlot from "../components/EndEffectorPlot";
import { Scrubber } from "../components/Scrubber";
import { Button } from "../components/ui/button";
import { PageHeader } from "../components/ui/page-header";
import { useEpisodeTimeline } from "../hooks/useEpisodeTimeline";
import { useSecondaryVideoSync } from "../hooks/useSecondaryVideoSync";

export default function ReplayPage() {
  const { ds, idx } = useParams<{ ds: string; idx: string }>();
  const episodeIdx = Number(idx);
  const { data: episodes } = useEpisodes(ds || "");
  const episode = episodes?.find((e) => e.episode_index === episodeIdx);
  const replayStart = useReplayStart();
  const replayStop = useReplayStop();
  const sessionState = useSessionStore((s) => s.state);
  const subState = useSessionStore((s) => s.subState);
  const replayProgress = useSessionStore((s) => s.replayProgress);

  const allCameras = episode?.cameras ?? ["front"];
  // Hard cap: master + 3 secondaries = 4 total. If a session exposes more, we
  // only render 4 and drop the rest (rather than rendering unsynced extras that
  // are forced into the no-controls state). Most adapters expose ≤ 2 cameras.
  const cameras = allCameras.slice(0, 4);
  if (allCameras.length > 4) {
    // eslint-disable-next-line no-console
    console.warn(`Replay: ${allCameras.length} cameras present, only first 4 rendered (sync limit).`);
  }

  const masterRef = useRef<HTMLVideoElement>(null);
  const sec1Ref = useRef<HTMLVideoElement>(null);
  const sec2Ref = useRef<HTMLVideoElement>(null);
  const sec3Ref = useRef<HTMLVideoElement>(null);
  const secondaryRefs = [sec1Ref, sec2Ref, sec3Ref] as const;

  const { currentTimeSec, seek } = useEpisodeTimeline(masterRef);
  const fps = (episode?.num_frames ?? 1) / Math.max(0.001, episode?.duration_sec ?? 1);

  // Always call all 3 sync hooks (rules-of-hooks). Each hook no-ops when its
  // ref is null (no secondary at that slot).
  useSecondaryVideoSync(sec1Ref, masterRef, currentTimeSec, fps);
  useSecondaryVideoSync(sec2Ref, masterRef, currentTimeSec, fps);
  useSecondaryVideoSync(sec3Ref, masterRef, currentTimeSec, fps);

  const cursorFrameIdx = useMemo(
    () => Math.min(Math.round(currentTimeSec * fps), (episode?.num_frames ?? 1) - 1),
    [currentTimeSec, fps, episode?.num_frames],
  );

  if (!ds || !idx) return <div className="p-6">Invalid URL</div>;

  return (
    <>
      <PageHeader
        code="§01.C"
        title={
          <span className="flex items-baseline gap-md">
            Replay
            <span className="text-steel">·</span>
            <span className="font-mono text-caption text-ink">{ds} / ep {idx}</span>
          </span>
        }
        meta={episode && (
          <span className="font-mono text-micro text-stone">
            {episode.duration_sec.toFixed(1)}s · {episode.num_frames} frames
          </span>
        )}
      />

      {/* Control row */}
      <div className="flex-shrink-0 flex items-center gap-md px-xl py-sm border-b border-hairline bg-canvas">
        <Link to={`/datasets/${ds}/episodes`} className="text-caption text-stone hover:text-ink">
          ← Episodes
        </Link>
        <span className="text-hairline">|</span>
        {replayProgress && subState === "replaying" && (
          <span className="text-body-sm text-slate font-mono">
            HW replay {replayProgress.frame_index} / {replayProgress.total_frames}
          </span>
        )}
        <span className="flex-1" />
        {subState === "replaying" ? (
          <Button variant="destructive" onClick={() => replayStop.mutate()}>Stop Replay</Button>
        ) : (
          <Button
            onClick={() => replayStart.mutate({ dataset: ds, episode_idx: episodeIdx })}
            disabled={sessionState !== "ready" || replayStart.isPending}
          >
            {sessionState !== "ready"
              ? "Start a session first"
              : replayStart.isPending
              ? "Starting…"
              : "▶ Replay on Robot"}
          </Button>
        )}
      </div>

      {/* Meta strip */}
      {episode && (
        <div className="flex-shrink-0 flex flex-wrap items-baseline gap-x-lg gap-y-1 px-xl py-sm border-b border-hairline-soft bg-surface-soft text-body-sm">
          <MetaItem k="Task"     v={episode.task} />
          <MetaItem k="Duration" v={`${episode.duration_sec.toFixed(1)}s`} />
          <MetaItem k="Frames"   v={String(episode.num_frames)} />
          <MetaItem k="Success"  v={episode.success === true ? "Yes" : episode.success === false ? "No" : "—"}
                    color={episode.success === true ? "text-brand-green-deep" : episode.success === false ? "text-brand-error" : "text-stone"} />
          <MetaItem k="Mode"     v={episode.mode} />
          <MetaItem k="Robot"    v={episode.robot} />
        </div>
      )}

      {/* Body: left video / right plots */}
      <div className="flex-1 flex min-h-0 gap-sm p-sm">
        <div className="flex-[1.5] min-w-0 grid gap-sm" style={{ gridTemplateColumns: `repeat(${Math.min(cameras.length, 2)}, minmax(0, 1fr))` }}>
          {cameras.map((cam, i) => {
            const ref = i === 0 ? masterRef : (secondaryRefs[i - 1] ?? null);
            return (
              <VideoPlayer
                key={cam}
                ds={ds}
                idx={episodeIdx}
                cam={cam}
                isMaster={i === 0}
                ref={ref ?? undefined}
              />
            );
          })}
        </div>

        <div className="flex-1 min-w-0 flex flex-col gap-sm">
          <div className="flex-1 min-h-0 flex flex-col border border-hairline rounded-sm bg-canvas overflow-hidden">
            <div className="flex-shrink-0 px-md py-sm border-b border-hairline-soft text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold flex items-center justify-between">
              <span>Joint trajectory</span>
              <span className="font-mono text-[10px] text-muted">click to seek</span>
            </div>
            <div className="flex-1 min-h-0">
              <JointPlot ds={ds} idx={episodeIdx} cursorTimeSec={currentTimeSec} onSeek={seek} />
            </div>
          </div>
          <div className="flex-1 min-h-0 flex flex-col border border-hairline rounded-sm bg-canvas overflow-hidden">
            <div className="flex-shrink-0 px-md py-sm border-b border-hairline-soft text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
              End-Effector
            </div>
            <div className="flex-1 min-h-0">
              <EndEffectorPlot ds={ds} idx={episodeIdx} cursorFrameIdx={cursorFrameIdx} />
            </div>
          </div>
        </div>
      </div>

      <Scrubber
        durationSec={episode?.duration_sec ?? 0}
        currentTimeSec={currentTimeSec}
        onSeek={seek}
      />
    </>
  );
}

function MetaItem({ k, v, color = "text-ink" }: { k: string; v: string; color?: string }) {
  return (
    <div className="flex items-baseline gap-1">
      <span className="text-caption-bold text-steel uppercase tracking-[0.5px]">{k}</span>
      <span className={`text-body-sm-medium ${color}`}>{v}</span>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: Manual verify**

Run dev server, navigate to an episode's Replay. Verify each of these explicitly:

- *Master playback*: press play on the master video. Joint plot vertical cursor advances at near-frame-rate (Chromium has rVFC; Firefox ≥ 124 has it too — verify in your test browser).
- *Click-anywhere seek on joint plot*: click any horizontal position over the joint plot, including between data points. Video, scrubber, and EE current-position dot all jump to that time. Click far-left → snaps to t=0; click far-right → snaps to t=duration.
- *Scrubber drag*: hold mouse on the scrubber head and drag. All four surfaces (video, joint cursor, EE dot, scrubber position) stay in lockstep.
- *Pause/rate mirroring*: pause master. Confirm secondary videos pause within ~1 frame. Change master playback rate via the right-click menu → confirm secondaries follow.
- *Seek while paused*: with master paused, drag scrubber. Secondary videos jump to the same time and stay paused there.
- *Browser fallback*: open the page in a browser without rVFC (Safari < 16, older Firefox if you have one). Confirm playback still works, cursor just updates at lower granularity. (If your only browser is Chromium-current, document that this fallback path was NOT manually verified.)
- *Secondary sync after episode change*: navigate to a different episode (back to Episodes list, pick another). Confirm the new episode's videos and plots load and stay in sync (no leftover state from the previous episode).
- *HW replay independence*: with `sessionState === "ready"`, press "▶ Replay on Robot". Confirm the HW progress indicator advances in the control row; *separately*, the video scrubber can still be operated and does NOT affect the robot's replay progress.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ReplayPage.tsx
git commit -m "feat(replay): full-width layout + master-timeline synced playback"
```

---

## Self-test gates

After Phase 3 lands, do a final sweep before declaring done:

- [ ] **Frontend build**

```bash
cd frontend && npm run build
```

Expected: exit 0, no TS errors.

- [ ] **Backend smoke**

```bash
.venv/bin/python -c "from mimicrec.api.app import create_app; app = create_app(); print(len(app.routes))"
```

Expected: count unchanged from after annotation-removal commit (`216d524`) — verify Inference HTTP API surface preserved.

- [ ] **External HTTP smoke run (per spec § "Inference HTTP API")**

The spec calls for an end-to-end HTTP-driven inference run to confirm no regressions to the API surface external apps depend on. Run this against a running backend with an inference config wired (substitute `<configname>` with one returned by `GET /api/configs/inference`):

```bash
# 1. Discover available inference configs
curl -sS localhost:8000/api/configs/inference | jq .

# 2. Open robot session in inference-compatible state
curl -sS -X POST localhost:8000/api/session/start \
  -H "Content-Type: application/json" \
  -d '{"robot":"so101","teleop":null,"cameras":["front"],"dataset":"smoke","task":"smoke","mode":"inference"}' | jq .

# 3. Start inference session
curl -sS -X POST localhost:8000/api/session/inference/start \
  -H "Content-Type: application/json" \
  -d '{"config":"<configname>","instruction":"smoke"}' | jq .

# 4. Run one episode end-to-end
curl -sS -X POST localhost:8000/api/episode/start    -H "Content-Type: application/json" -d '{}' | jq .
sleep 3
curl -sS -X POST localhost:8000/api/episode/stop     -H "Content-Type: application/json" -d '{}' | jq .
curl -sS -X POST localhost:8000/api/episode/save     -H "Content-Type: application/json" -d '{"success":false,"comment":"smoke"}' | jq .

# 5. Stop inference session, end robot session
curl -sS -X POST localhost:8000/api/session/inference/stop -H "Content-Type: application/json" -d '{}' | jq .
curl -sS -X POST localhost:8000/api/session/end -H "Content-Type: application/json" -d '{}' | jq .

# 6. Confirm route count unchanged from baseline (62 routes pre-annotation-removal,
#    59 routes after commit 216d524; this plan does not add or remove any routes).
.venv/bin/python -c "from mimicrec.api.app import create_app; print(len(create_app().routes))"
```

Expected: every `curl` returns 2xx; the route count line prints `59`. If any step 4xx/5xx's, capture the response body and stop — there's an API regression that needs investigation before merge.

If there's no inference config available in the test environment, document this gap on the PR rather than skipping silently — at minimum re-run `curl localhost:8000/api/configs/inference` to confirm the discovery endpoint still works.

- [ ] **Manual cross-page smoke**

Navigate Datasets → Episodes → click "Open replay" → back → check icon-sidebar identification works without color cues. Tab through `/datasets`, `/record`, `/inference`, `/settings`; the active item is identifiable by sidebar icon + inverted style.

---

## Out of scope (for follow-ups, NOT this plan)

- Migrating `JointPlot`'s color palette to brand tokens (the existing `#2563eb`/`#dc2626` set stays — flag this with an issue or follow-up).
- Backend-pre-generated `poster.jpg` per episode (replace `useEpisodeThumbnail` with a server-side route if the client-side approach proves too slow).
- URL-state persistence of Episodes filters.
- Keyboard navigation (↑/↓) in EpisodesList.
- Sub-1280px responsive collapse for Inference 3-column.
- vitest setup for hook unit tests.

