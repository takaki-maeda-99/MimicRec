# UI Modernization — Modernized Lab Notebook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the "Modernized Lab Notebook" visual language across the frontend by (1) extending the Mintlify token foundation with two new colors, (2) adding four new primitives plus a `PageHeader` component, (3) refactoring existing primitives, (4) rewriting `Layout.tsx` with a global E-Stop slot, and (5) rewriting four page bodies (`Record`, `Datasets`, `Episodes`, `Settings`). `Replay` and `Inference` receive only the shell + per-page E-Stop removal in this pass.

**Architecture:** Six phases in dependency order. Foundation (tokens + primitives) lands first as dead code that compiles. Phase 2 swaps in the new shell, removes per-page E-Stops, and deletes the `/mocks/*` exploration. Phases 3–6 rewrite each remaining page using the new primitives. Each phase is one PR.

**Tech Stack:** React 19, Vite, Tailwind CSS v4 (`@theme` tokens), `tailwind-merge` via `cn()`, Inter + Geist Mono via Google Fonts CDN. Zustand state, React Query, Recharts (existing).

**Spec:** `docs/superpowers/specs/2026-05-13-ui-modernized-lab-notebook-design.md`

**Approved high-fidelity mocks:**
- `.superpowers/brainstorm/211843-1778620183/record-c-v3.html`
- `.superpowers/brainstorm/211843-1778620183/datasets-c-v3.html`

**Verification model:** Per-task, `pnpm --dir frontend exec tsc --noEmit` for type checks (fast). At phase boundaries, `pnpm --dir frontend build` (tsc + vite) and a manual browser smoke pass at 1440×900 (and 1200×800 for `RecordPage`). **We do not add a test framework as part of this plan.** Pure-function logic (e.g., the sparkline path computation) is structured to be self-evident; smoke checks cover the rest.

**Working directory:** All commands assume `/home/takakimaeda/MimicRec` as cwd unless stated otherwise.

---

## File Structure

**Created:**
- `frontend/src/components/ui/section-mark.tsx`
- `frontend/src/components/ui/corner-ticks.tsx`
- `frontend/src/components/ui/instrument-well.tsx`
- `frontend/src/components/ui/sparkline.tsx`
- `frontend/src/components/ui/page-header.tsx`
- `frontend/src/components/SidebarStatus.tsx` (sidebar Status block — small helper for `Layout.tsx`)
- `frontend/src/hooks/useJointHistory.ts` (rolling buffer hook for sparklines)

**Modified:**
- `frontend/src/index.css` (add 2 color tokens)
- `frontend/src/components/ui/property-row.tsx` (add `density` and `divider` props)
- `frontend/src/components/ui/badge.tsx` (add `status` variant family)
- `frontend/src/components/ui/button.tsx` (add `size="xs"`)
- `frontend/src/components/ui/sidebar-nav-item.tsx` (add `code` prop, restyle active state)
- `frontend/src/components/Layout.tsx` (sidebar rewrite, global E-Stop slot, PageHeader pattern)
- `frontend/src/components/EStopButton.tsx` (sidebar-fit visual, 64 px tall)
- `frontend/src/pages/RecordPage.tsx` (single-viewport grid; remove `<EStopButton />`)
- `frontend/src/pages/DatasetsPage.tsx` (new card body, toolbar)
- `frontend/src/pages/EpisodesPage.tsx` (PageHeader + table polish)
- `frontend/src/pages/SettingsPage.tsx` (§-numbered sections via SectionMark)
- `frontend/src/pages/ReplayPage.tsx` (PageHeader only — layout untouched)
- `frontend/src/pages/InferencePage.tsx` (PageHeader + remove `<EStopButton />` — layout untouched)
- `frontend/src/App.tsx` (remove `/mocks/*` routes & imports)

**Deleted:**
- `frontend/src/pages/mocks/MockMissionControl.tsx`
- `frontend/src/pages/mocks/MockEditorial.tsx`
- `frontend/src/pages/mocks/MockNotebook.tsx`
- `frontend/src/pages/mocks/MockIndex.tsx`
- `frontend/src/pages/mocks/sample-data.ts`
- The `frontend/src/pages/mocks/` directory itself (after files removed).

---

## Phase 1 — Tokens & primitives (foundation, no visual change)

End of phase: build green, new primitives importable, no page consumes them yet. **One PR.**

### Task 1: Add two new color tokens

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Read the file, find the line that ends the color block**

Open `frontend/src/index.css` with the Read tool. Locate the existing line `--color-on-dark-muted: #b3b3b3;` (currently around line 33). Use an Edit operation that anchors on that exact line.

- [ ] **Step 2: Add the two tokens immediately after `--color-on-dark-muted`**

```
old_string:  --color-on-dark-muted: #b3b3b3;
new_string:  --color-on-dark-muted: #b3b3b3;
  --color-on-dark-dim: #71717a;     /* secondary text on canvas-dark wells */
  --color-on-dark-mark: #fbbf24;    /* corner ticks / accents on canvas-dark */
```

(The lines must remain inside the `@theme { ... }` block — no closing brace between `--color-on-dark-muted` and the new tokens.)

- [ ] **Step 3: Type-check**

Run: `pnpm --dir frontend exec tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Verify Tailwind auto-generates utilities**

```bash
pnpm --dir frontend exec tsc --noEmit
# Briefly run dev to confirm `bg-on-dark-dim` and `border-on-dark-mark` are valid:
# pnpm --dir frontend dev (Ctrl-C after first compile)
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/index.css
git commit -m "feat(ui): add on-dark-dim and on-dark-mark color tokens"
```

---

### Task 2: New primitive `CornerTicks`

A purely decorative 4-corner L-bracket overlay. Expects its parent to be `position: relative`.

**Files:**
- Create: `frontend/src/components/ui/corner-ticks.tsx`

- [ ] **Step 1: Create the file**

```tsx
import { cn } from "../../lib/utils";

interface CornerTicksProps {
  /**
   * "light" → uses brand-warn (visible against canvas / surface).
   * "dark"  → uses on-dark-mark (visible against canvas-dark).
   */
  tone?: "light" | "dark";
  /** px from each corner. Default 6. */
  inset?: number;
  /** px length of each L arm. Default 8. */
  size?: number;
  className?: string;
}

export function CornerTicks({
  tone = "light",
  inset = 6,
  size = 8,
  className,
}: CornerTicksProps) {
  const color =
    tone === "dark" ? "border-on-dark-mark" : "border-brand-warn";
  const common = cn("absolute pointer-events-none", color);
  const style = { width: size, height: size };
  return (
    <div className={cn("absolute inset-0 pointer-events-none", className)} aria-hidden>
      <span
        className={cn(common, "border-t border-l")}
        style={{ ...style, top: inset, left: inset }}
      />
      <span
        className={cn(common, "border-t border-r")}
        style={{ ...style, top: inset, right: inset }}
      />
      <span
        className={cn(common, "border-b border-l")}
        style={{ ...style, bottom: inset, left: inset }}
      />
      <span
        className={cn(common, "border-b border-r")}
        style={{ ...style, bottom: inset, right: inset }}
      />
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `pnpm --dir frontend exec tsc --noEmit`
Expected: success (component unused).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/corner-ticks.tsx
git commit -m "feat(ui): add CornerTicks primitive"
```

---

### Task 3: New primitive `SectionMark`

The §-numbered mono caps label. Used in `PageHeader` and inline as sub-section dividers.

**Files:**
- Create: `frontend/src/components/ui/section-mark.tsx`

- [ ] **Step 1: Create the file**

```tsx
import { cn } from "../../lib/utils";

interface SectionMarkProps {
  /** Section code, e.g. "§02" or "§02.A". Rendered verbatim. */
  code: string;
  /** Optional section name appended after a middle dot, e.g. "Record". */
  name?: string;
  className?: string;
}

export function SectionMark({ code, name, className }: SectionMarkProps) {
  return (
    <span
      className={cn(
        "font-mono text-micro-uppercase uppercase text-brand-warn",
        "tracking-[0.16em] font-semibold",
        className,
      )}
    >
      {code}
      {name && (
        <>
          <span className="mx-1 text-stone"> · </span>
          {name}
        </>
      )}
    </span>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `pnpm --dir frontend exec tsc --noEmit`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/section-mark.tsx
git commit -m "feat(ui): add SectionMark primitive"
```

---

### Task 4: New primitive `Sparkline`

Inline SVG line plot, 160×14 by default, no axes. Pure-functional path computation — read the data array, normalize to height, output an SVG `<polyline points>`.

**Files:**
- Create: `frontend/src/components/ui/sparkline.tsx`

- [ ] **Step 1: Create the file**

```tsx
import { cn } from "../../lib/utils";

interface SparklineProps {
  data: number[];
  /** "ok" → brand-green-deep; "warn" → brand-warn. */
  tone?: "ok" | "warn";
  width?: number;
  height?: number;
  strokeWidth?: number;
  className?: string;
}

/**
 * Pure: map numeric series → SVG polyline points string.
 * Min / max are inferred from the data; if the series is flat,
 * we draw it on the vertical midline.
 */
function pointsFor(data: number[], width: number, height: number): string {
  if (data.length === 0) return "";
  if (data.length === 1) return `0,${height / 2} ${width},${height / 2}`;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min;
  const step = width / (data.length - 1);

  return data
    .map((v, i) => {
      const x = i * step;
      const y =
        range === 0 ? height / 2 : height - ((v - min) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

export function Sparkline({
  data,
  tone = "ok",
  width = 160,
  height = 14,
  strokeWidth = 1,
  className,
}: SparklineProps) {
  const stroke =
    tone === "warn" ? "var(--color-brand-warn)" : "var(--color-brand-green-deep)";
  const pts = pointsFor(data, width, height);

  return (
    <svg
      className={cn("block", className)}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden
    >
      <polyline points={pts} fill="none" stroke={stroke} strokeWidth={strokeWidth} />
    </svg>
  );
}

// exported for ad-hoc reuse / spot-checking; not part of the rendered API
export const __testing__ = { pointsFor };
```

- [ ] **Step 2: Type-check**

Run: `pnpm --dir frontend exec tsc --noEmit`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/sparkline.tsx
git commit -m "feat(ui): add Sparkline primitive"
```

---

### Task 5: New primitive `InstrumentWell`

Dark panel for live data (cameras, plots). Optional header strip with title + LIVE indicator. Optional corner ticks (default on).

**Files:**
- Create: `frontend/src/components/ui/instrument-well.tsx`

- [ ] **Step 1: Create the file**

```tsx
import { cn } from "../../lib/utils";
import { CornerTicks } from "./corner-ticks";

interface InstrumentWellProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Mono uppercase header strip text, e.g. "CAM · 01 · FRONT". */
  header?: React.ReactNode;
  /** When true, shows a pulsing teal LIVE indicator on the header. */
  live?: boolean;
  /** Show corner ticks. Default true. */
  ticks?: boolean;
  /** Optional caption rendered below the body. */
  caption?: React.ReactNode;
  children?: React.ReactNode;
}

export function InstrumentWell({
  header,
  live,
  ticks = true,
  caption,
  children,
  className,
  ...props
}: InstrumentWellProps) {
  return (
    <div
      className={cn(
        "relative bg-canvas-dark text-on-dark rounded-md overflow-hidden",
        "flex flex-col min-h-0",
        "px-sm py-xs",
        className,
      )}
      {...props}
    >
      {ticks && <CornerTicks tone="dark" />}
      {(header || live) && (
        <div className="relative flex items-baseline justify-between mb-xs flex-shrink-0 font-mono text-micro-uppercase uppercase tracking-[0.14em] text-on-dark-dim">
          <span>{header}</span>
          {live && (
            <span className="inline-flex items-center gap-1.5 text-brand-green">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-green animate-pulse" />
              LIVE
            </span>
          )}
        </div>
      )}
      <div className="relative flex-1 min-h-0">{children}</div>
      {caption && (
        <div className="relative mt-xs text-micro text-on-dark-dim flex-shrink-0">
          {caption}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `pnpm --dir frontend exec tsc --noEmit`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/instrument-well.tsx
git commit -m "feat(ui): add InstrumentWell primitive"
```

---

### Task 6: New primitive `PageHeader`

The 52 px top-of-main bar with `SectionMark` + title + state slot + meta slot.

**Files:**
- Create: `frontend/src/components/ui/page-header.tsx`

- [ ] **Step 1: Create the file**

```tsx
import { cn } from "../../lib/utils";
import { SectionMark } from "./section-mark";

interface PageHeaderProps {
  /** Section code, e.g. "§02". */
  code: string;
  /** Title, e.g. "Live capture — pick & place, blue cube". */
  title: React.ReactNode;
  /** Right-aligned state slot, e.g. a REC badge. */
  state?: React.ReactNode;
  /** Right-aligned meta slot, e.g. "pp. 047 – 061". */
  meta?: React.ReactNode;
  /** Right-aligned action slot, e.g. "+ New dataset" button (Datasets). */
  actions?: React.ReactNode;
  className?: string;
}

export function PageHeader({
  code,
  title,
  state,
  meta,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <header
      className={cn(
        "flex items-center gap-md px-xl py-sm border-b border-hairline bg-canvas",
        "flex-shrink-0 min-h-[52px]",
        className,
      )}
    >
      <SectionMark code={code} />
      <h1 className="text-heading-5 text-ink truncate">{title}</h1>
      <span className="flex-1" />
      {state}
      {meta && <span className="font-mono text-micro text-stone">{meta}</span>}
      {actions}
    </header>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `pnpm --dir frontend exec tsc --noEmit`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/page-header.tsx
git commit -m "feat(ui): add PageHeader primitive"
```

---

### Task 7: Refactor `PropertyRow` — add `density` and `divider` props

Add optional props so the same row can serve dense joint-position tables (compact + dashed) and dataset-card fact strips (comfortable + solid). Existing call sites pass nothing; behaviour preserved.

**Files:**
- Modify: `frontend/src/components/ui/property-row.tsx`

- [ ] **Step 1: Replace file contents**

```tsx
import { cn } from "../../lib/utils";
import { CodeInline } from "./code-inline";
import { Badge } from "./badge";

interface PropertyRowProps extends React.HTMLAttributes<HTMLDivElement> {
  name: string;
  type?: string;
  required?: boolean;
  description?: React.ReactNode;
  control?: React.ReactNode;
  /** "comfortable" (default) = py-md; "compact" = py-1. */
  density?: "comfortable" | "compact";
  /** "solid" (default) hairline-soft; "dashed" hairline-soft dashed; "none" for grouped rows. */
  divider?: "solid" | "dashed" | "none";
}

export function PropertyRow({
  className,
  name,
  type,
  required = false,
  description,
  control,
  density = "comfortable",
  divider = "solid",
  ...props
}: PropertyRowProps) {
  const dividerCls =
    divider === "dashed"
      ? "border-b border-dashed border-hairline-soft last:border-b-0"
      : divider === "solid"
      ? "border-b border-hairline-soft last:border-b-0"
      : "";
  const pad = density === "compact" ? "py-1" : "py-md";
  return (
    <div className={cn(pad, dividerCls, className)} {...props}>
      <div className="flex items-center gap-xs flex-wrap">
        <CodeInline>{name}</CodeInline>
        {type && <Badge variant="type">{type}</Badge>}
        {required && <Badge variant="required">REQUIRED</Badge>}
      </div>
      {description && (
        <div className="mt-1.5 text-body-sm text-steel">{description}</div>
      )}
      {control && <div className="mt-md">{control}</div>}
    </div>
  );
}
```

- [ ] **Step 2: Type-check + grep for existing call sites**

```bash
pnpm --dir frontend exec tsc --noEmit
grep -rn "PropertyRow" frontend/src --include="*.tsx" --include="*.ts"
```

Expected: tsc success; no existing call sites that would break (current callers all use the default `comfortable`/`solid`).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/property-row.tsx
git commit -m "refactor(ui): PropertyRow gains density + divider props"
```

---

### Task 8: Refactor `Badge` — add `status` variant family

Add a `state` prop scoped to `variant="status"` that maps the six hub/recording states to a pill style. Other variants keep their existing API.

**Files:**
- Modify: `frontend/src/components/ui/badge.tsx`

- [ ] **Step 1: Replace file contents**

```tsx
import { cn } from "../../lib/utils";

export type StatusState =
  | "synced"
  | "pushing"
  | "stale"
  | "pending"
  | "unconfigured"
  | "error";

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?:
    | "default"
    | "success"
    | "warning"
    | "destructive"
    | "outline"
    | "tag"
    | "type"
    | "required"
    | "status";
  /** Required when variant="status". Ignored otherwise. */
  state?: StatusState;
}

const STATUS_STYLE: Record<StatusState, { wrap: string; dot: string; label: string }> = {
  synced: {
    wrap: "bg-brand-green-soft/40 text-brand-green-deep border border-brand-green-deep/20",
    dot: "bg-brand-green-deep",
    label: "Synced",
  },
  pushing: {
    wrap: "bg-brand-tag/15 text-brand-tag border border-brand-tag/25",
    dot: "bg-brand-tag animate-pulse",
    label: "Pushing",
  },
  stale: {
    wrap: "bg-brand-warn/15 text-brand-warn border border-brand-warn/25",
    dot: "bg-brand-warn",
    label: "Stale",
  },
  pending: {
    wrap: "bg-surface-soft text-steel border border-dashed border-hairline",
    dot: "bg-stone",
    label: "Pending",
  },
  unconfigured: {
    wrap: "bg-transparent text-steel border border-dashed border-hairline",
    dot: "",
    label: "Hub not configured",
  },
  error: {
    wrap: "bg-brand-error/10 text-brand-error border border-brand-error/30",
    dot: "bg-brand-error",
    label: "Push failed",
  },
};

export function Badge({ className, variant = "default", state, children, ...props }: BadgeProps) {
  if (variant === "status" && state) {
    const s = STATUS_STYLE[state];
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5",
          "font-mono text-micro-uppercase uppercase tracking-[0.1em]",
          s.wrap,
          className,
        )}
        {...props}
      >
        {s.dot && <span className={cn("w-1.5 h-1.5 rounded-full", s.dot)} />}
        {children ?? s.label}
      </span>
    );
  }

  const base = "inline-flex items-center text-caption-bold";
  const variants: Record<string, string> = {
    default: "rounded-full border border-hairline text-steel bg-transparent px-2 py-0.5",
    success: "rounded-full bg-brand-green text-primary px-2 py-0.5",
    warning: "rounded-full bg-brand-warn/15 text-brand-warn px-2 py-0.5",
    destructive: "rounded-full bg-brand-error text-on-dark px-2 py-0.5",
    outline: "rounded-full border border-hairline text-steel bg-transparent px-2 py-0.5",
    tag: "rounded-sm bg-brand-tag/15 text-brand-tag px-2 py-0.5",
    type: "rounded-sm bg-surface text-steel font-mono text-code-sm px-1.5 py-0.5",
    required:
      "rounded-sm bg-brand-error text-on-dark text-micro-uppercase px-1.5 py-0.5 uppercase tracking-[0.5px]",
  };
  return <span className={cn(base, variants[variant], className)} {...props}>{children}</span>;
}
```

- [ ] **Step 2: Type-check + verify existing call sites still compile**

```bash
pnpm --dir frontend exec tsc --noEmit
```

Expected: success. Existing `<Badge variant="success">…</Badge>` etc. unchanged.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/badge.tsx
git commit -m "refactor(ui): Badge gains 'status' variant family"
```

---

### Task 9: Refactor `Button` — add `size="xs"`

A 28 px tall variant for dense toolbars (Datasets toolbar, Record controls bar). Existing sizes preserved.

**Files:**
- Modify: `frontend/src/components/ui/button.tsx`

- [ ] **Step 1: Replace the file**

```tsx
import { cn } from "../../lib/utils";

type VariantNew = "primary" | "secondary" | "ghost" | "link" | "iconCircular";
type VariantLegacy = "default" | "destructive" | "outline";
type Variant = VariantNew | VariantLegacy;

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "default" | "xs" | "sm" | "lg";
}

export function Button({
  className,
  variant = "primary",
  size = "default",
  ...props
}: ButtonProps) {
  const normalized: VariantNew | "destructive" =
    variant === "default"
      ? "primary"
      : variant === "outline"
      ? "secondary"
      : variant === "destructive"
      ? "destructive"
      : variant;

  const base =
    "inline-flex items-center justify-center font-medium transition-colors disabled:cursor-not-allowed text-button-md";
  const pillPad =
    size === "xs"
      ? "h-7 px-2.5 text-micro"
      : size === "sm"
      ? "h-8 px-sm"
      : size === "lg"
      ? "h-10 px-lg"
      : "h-9 px-md";

  const variants: Record<VariantNew | "destructive", string> = {
    primary:
      "rounded-full bg-primary text-on-primary " +
      pillPad +
      " hover:bg-charcoal disabled:bg-hairline disabled:text-muted",
    secondary:
      "rounded-full border border-hairline bg-transparent text-ink " +
      pillPad +
      " hover:bg-surface disabled:text-muted",
    destructive:
      "rounded-full bg-primary text-brand-error " +
      pillPad +
      " hover:bg-charcoal disabled:bg-hairline disabled:text-muted",
    ghost:
      "rounded-md bg-transparent text-ink h-9 px-3 hover:bg-surface disabled:text-muted",
    link:
      "bg-transparent text-ink text-body-sm-medium underline-offset-2 hover:underline p-0",
    iconCircular:
      "rounded-full bg-canvas text-ink border border-hairline w-8 h-8 hover:bg-surface",
  };

  return <button className={cn(base, variants[normalized], className)} {...props} />;
}
```

- [ ] **Step 2: Type-check**

Run: `pnpm --dir frontend exec tsc --noEmit`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/button.tsx
git commit -m "refactor(ui): Button gains size='xs'"
```

---

### Task 10: Refactor `SidebarNavItem` — add `code` prop and new active state

Adds a mono `§NN` prefix and switches the active state to **ink background + on-primary text + on-dark-mark code numeral** (per v3 mock).

**Files:**
- Modify: `frontend/src/components/ui/sidebar-nav-item.tsx`

- [ ] **Step 1: Replace the file**

```tsx
import { NavLink } from "react-router-dom";
import { cn } from "../../lib/utils";

interface SidebarNavItemProps {
  to: string;
  /** Section code prefix, e.g. "§01". Required by the new design. */
  code?: string;
  children: React.ReactNode;
  className?: string;
}

export function SidebarNavItem({ to, code, children, className }: SidebarNavItemProps) {
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

- [ ] **Step 2: Type-check**

Run: `pnpm --dir frontend exec tsc --noEmit`
Expected: success. (`Layout.tsx` still imports the old shape but calls without `code` — TypeScript permits the omitted optional prop.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/sidebar-nav-item.tsx
git commit -m "refactor(ui): SidebarNavItem gains 'code' prop and new active state"
```

---

### Task 11: New hook `useJointHistory` (rolling buffer for sparklines)

Subscribes to the **`/ws/state`** websocket — the same one `EEMonitor` already uses (`frontend/src/components/EEMonitor.tsx:29`). The session websocket (`/ws/session`) emits `episode_progress` with backend-internal counters only (see `frontend/src/api/types.ts:43-49`), **not** joint positions. The state websocket emits `joint_pos`, `joint_vel`, `ee_pos`, `ee_rotvec`, `gripper_pos` per the backend's `state_hub.py:18-23`.

**Files:**
- Create: `frontend/src/hooks/useJointHistory.ts`

- [ ] **Step 1: Create the file**

```tsx
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { WsConnection } from "../api/ws";

interface StatePayload {
  joint_pos?: number[];
  joint_vel?: number[];
  ee_pos?: number[];
  ee_rotvec?: number[];
  gripper_pos?: number;
  t_mono_ns?: number;
}

interface Buffer {
  capacity: number;
  snapshots: number[][]; // [joint_idx][sample]
  version: number;
}

function makeBuffer(numJoints: number, capacity: number): Buffer {
  return {
    capacity,
    snapshots: Array.from({ length: numJoints }, () => []),
    version: 0,
  };
}

function push(buf: Buffer, sample: number[]) {
  while (buf.snapshots.length < sample.length) buf.snapshots.push([]);
  sample.forEach((v, i) => {
    const series = buf.snapshots[i];
    series.push(v);
    if (series.length > buf.capacity) series.shift();
  });
  buf.version += 1;
}

/**
 * Subscribe to /ws/state and keep a rolling buffer of the last
 * `secondsWindow` seconds of joint positions. Designed for sparkline
 * consumers; non-recording sessions are fine — the buffer simply stays
 * empty until samples arrive.
 *
 * Capacity is conservative: at 100 Hz × 6 s = 600 samples per joint.
 * If perf matters later, downsample at push time.
 */
export function useJointHistory(
  enabled: boolean,
  numJoints: number,
  secondsWindow = 6,
  hz = 100,
) {
  const capacity = secondsWindow * hz;
  const bufRef = useRef<Buffer>(makeBuffer(numJoints, capacity));
  const listenersRef = useRef<Set<() => void>>(new Set());
  const [numJointsObserved, setNumJointsObserved] = useState(numJoints);

  // Re-init buffer if numJoints changes.
  useEffect(() => {
    bufRef.current = makeBuffer(Math.max(numJoints, numJointsObserved), capacity);
    listenersRef.current.forEach((l) => l());
  }, [numJoints, capacity, numJointsObserved]);

  // Open / close the WS subscription as `enabled` flips.
  useEffect(() => {
    if (!enabled) return;
    const conn = new WsConnection("/ws/state");
    conn.onMessage((msg) => {
      const m = msg as StatePayload;
      if (!m.joint_pos || !m.joint_pos.length) return;
      if (m.joint_pos.length > numJointsObserved) {
        setNumJointsObserved(m.joint_pos.length);
      }
      push(bufRef.current, m.joint_pos);
      listenersRef.current.forEach((l) => l());
    });
    conn.connect();
    return () => conn.disconnect();
  }, [enabled, numJointsObserved]);

  const subscribe = (cb: () => void) => {
    listenersRef.current.add(cb);
    return () => listenersRef.current.delete(cb);
  };
  const getSnapshot = () => bufRef.current.version;
  useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  return bufRef.current.snapshots;
}
```

- [ ] **Step 2: Type-check**

Run: `pnpm --dir frontend exec tsc --noEmit`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useJointHistory.ts
git commit -m "feat(hooks): add useJointHistory rolling-buffer (subscribes /ws/state)"
```

---

### Task 12: Phase 1 gate — full build & sanity

- [ ] **Step 1: Full build**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 2: Confirm no page consumes new primitives yet (dead code by design)**

```bash
grep -rn "SectionMark\|InstrumentWell\|Sparkline\|PageHeader\|CornerTicks\|useJointHistory" frontend/src --include="*.tsx" --include="*.ts" | grep -v "components/ui/" | grep -v "hooks/useJointHistory"
```

Expected: no output (primitives defined but unused).

- [ ] **Step 3: Tag commit (optional but recommended)**

```bash
git tag ui-modlab-phase-1
```

**Phase 1 complete.** Foundation in place.

---

## Phase 2 — Shell + global E-Stop + per-page E-Stop removal + mocks teardown

Single bundled PR. After this phase every page renders the new shell, but `Record` / `Datasets` / `Episodes` / `Settings` still have their existing bodies (transitional but consistent). `Replay` and `Inference` reach their final state in this phase except for the `PageHeader` swap (done now too).

### Task 13: Rewrite `EStopButton.tsx` for sidebar fit

Drop the inline "clear E-stop" button — moved into a small affordance shown only after a successful E-stop. Make the visual a 64 px tall, full-width red panel.

**Files:**
- Modify: `frontend/src/components/EStopButton.tsx`

- [ ] **Step 1: Replace contents**

```tsx
import { useEstop, useClearEstop } from "../api/queries.ts";
import { cn } from "../lib/utils";

/**
 * Sidebar-fit safety affordance. Renders a single 64px panel with double
 * red border. "clear E-stop" is a small inline secondary link that only
 * appears after a stop has fired (estop.isSuccess or clear is needed).
 */
export default function EStopButton() {
  const estop = useEstop();
  const clear = useClearEstop();
  const showClear = estop.isSuccess || clear.isError;

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={() => estop.mutate()}
        disabled={estop.isPending}
        className={cn(
          "h-16 w-full flex flex-col items-center justify-center gap-0.5",
          "rounded-md border-2 border-double border-brand-error bg-brand-error/10",
          "text-brand-error transition-colors",
          "hover:bg-brand-error/15 disabled:opacity-60 disabled:cursor-not-allowed",
        )}
        aria-label="Emergency stop"
      >
        <span className="font-mono text-micro-uppercase tracking-[0.32em] opacity-70">
          EMERGENCY
        </span>
        <span className="font-bold text-body-md-medium tracking-wider leading-none">
          E-STOP
        </span>
      </button>
      {showClear && (
        <button
          type="button"
          onClick={() => clear.mutate()}
          disabled={clear.isPending}
          className="text-caption text-brand-error underline underline-offset-2 self-center"
        >
          clear E-stop
        </button>
      )}
      {estop.isError && (
        <span className="text-caption text-brand-error text-center">estop failed</span>
      )}
      {clear.isError && (
        <span className="text-caption text-brand-error text-center">clear failed</span>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `pnpm --dir frontend exec tsc --noEmit`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/EStopButton.tsx
git commit -m "refactor(estop): sidebar-fit 64px panel, conditional clear"
```

---

### Task 14: Create `SidebarStatus.tsx` helper

A small component encapsulating the `Hub / Robot / Session / GoPros` mono fact-row strip in the sidebar — keeps `Layout.tsx` readable. **Includes the GoPro-pending indicator** that the old header used to carry (`GoProPendingBadge.tsx`); the spec line 168 explicitly moves both `SessionBadge` and `GoProPendingBadge` here.

**Files:**
- Create: `frontend/src/components/SidebarStatus.tsx`

- [ ] **Step 1: Confirm what HF auth API exists**

```bash
grep -n "useAuthStatus\|fetchAuthStatus" frontend/src/api/*.ts
```

If only `fetchAuthStatus` exists (in `api/cloud.ts`) — that's the case today — use a small local `useEffect` to poll it once on mount. Don't introduce a new query hook for sidebar polish.

- [ ] **Step 2: Confirm GoPro pending source**

```bash
grep -n "getGoProPending\|gopros" frontend/src/api/queries.ts frontend/src/state/session-store.ts
```

Use whichever count surface `GoProPendingBadge.tsx` currently consumes (likely `getGoProPending()` from `api/queries.ts`, polled at 500–1000 ms).

- [ ] **Step 3: Create the file**

```tsx
import { useEffect, useState } from "react";
import { useSessionStore } from "../state/session-store";
import { fetchAuthStatus, type AuthStatus } from "../api/cloud";
import { getGoProPending } from "../api/queries";
import { cn } from "../lib/utils";

function Row({
  k,
  v,
  tone,
}: {
  k: string;
  v: React.ReactNode;
  tone?: "ok" | "warn" | "rec" | "idle";
}) {
  const color =
    tone === "ok"
      ? "text-brand-green-deep"
      : tone === "warn"
      ? "text-brand-warn"
      : tone === "rec"
      ? "text-brand-error"
      : "text-ink";
  return (
    <div className="flex items-baseline justify-between font-mono text-micro tracking-[0.04em]">
      <span className="text-steel">{k}</span>
      <span className={cn("flex items-center gap-1.5", color)}>
        {tone === "rec" && <span className="w-1.5 h-1.5 rounded-full bg-brand-error animate-pulse" />}
        {v}
      </span>
    </div>
  );
}

export default function SidebarStatus() {
  const robot = useSessionStore((s) => s.robot);
  const sessionState = useSessionStore((s) => s.state);
  const gopros = useSessionStore((s) => s.gopros);

  const [auth, setAuth] = useState<AuthStatus | null>(null);
  useEffect(() => {
    let alive = true;
    fetchAuthStatus()
      .then((s) => alive && setAuth(s))
      .catch(() => alive && setAuth(null));
    return () => {
      alive = false;
    };
  }, []);

  // GoPro pending count — poll while gopros are attached.
  const [goproPending, setGoproPending] = useState(0);
  useEffect(() => {
    if (!gopros.length) return;
    let alive = true;
    const tick = async () => {
      try {
        const n = await getGoProPending();
        if (alive) setGoproPending(n);
      } catch {
        /* swallow */
      }
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [gopros.length]);

  return (
    <div className="flex flex-col gap-1 px-md">
      <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold pb-1">
        Status
      </div>
      <Row
        k="hub"
        v={auth?.authenticated ? `@${auth.username ?? "—"}` : "—"}
        tone={auth?.authenticated ? "ok" : undefined}
      />
      <Row k="robot" v={robot ?? "not connected"} tone={robot ? "ok" : undefined} />
      <Row
        k="session"
        v={sessionState}
        tone={sessionState === "recording" ? "rec" : sessionState === "idle" ? "idle" : "ok"}
      />
      {gopros.length > 0 && (
        <Row
          k="gopro"
          v={goproPending > 0 ? `${goproPending} pending` : "ready"}
          tone={goproPending > 0 ? "warn" : "ok"}
        />
      )}
    </div>
  );
}
```

**Note:** if `getGoProPending` is not directly exported but is inlined in `RecordingControls.tsx`, lift it to `api/queries.ts` as a small `async function getGoProPending(): Promise<number>` first, then commit that hoist on its own.

- [ ] **Step 4: Type-check**

Run: `pnpm --dir frontend exec tsc --noEmit`
Expected: success.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SidebarStatus.tsx
git commit -m "feat(layout): add SidebarStatus helper (incl. GoPro pending)"
```

---

### Task 15: Rewrite `Layout.tsx`

The whole shell. Sidebar (brand → §-numbered nav → SidebarStatus → global E-Stop slot → version footer), main column with new `flex-col` arrangement so pages own their own `PageHeader`. Drop the `max-w-[1280px] mx-auto` constraint — pages are now full-width by default.

**Files:**
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Replace the file**

```tsx
import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { useSessionStore } from "../state/session-store";
import { useSessionState } from "../api/queries";
import { SidebarNavItem } from "./ui/sidebar-nav-item";
import { ErrorBoundary } from "./ErrorBoundary";
import EStopButton from "./EStopButton";
import SidebarStatus from "./SidebarStatus";

const navItems = [
  { to: "/datasets", code: "§01", label: "Datasets" },
  { to: "/record", code: "§02", label: "Record" },
  { to: "/inference", code: "§03", label: "Inference" },
  { to: "/settings", code: "§04", label: "Settings" },
];

function Brand() {
  return (
    <div className="flex items-center gap-xs">
      <span className="relative w-[18px] h-[18px] rounded-xs bg-ink">
        <span className="absolute -right-0.5 -bottom-0.5 w-[7px] h-[7px] rounded-xs bg-brand-warn" />
      </span>
      <span className="text-heading-5 text-ink tracking-tight">MimicRec</span>
    </div>
  );
}

export default function Layout() {
  const { data: apiState } = useSessionState();
  const setSessionState = useSessionStore((s) => s.setSessionState);
  const robot = useSessionStore((s) => s.robot);
  const state = useSessionStore((s) => s.state);

  useEffect(() => {
    if (apiState) setSessionState(apiState as unknown as Record<string, unknown>);
  }, [apiState, setSessionState]);

  const showEstop = robot === "rebotarm" && state !== "idle";

  return (
    <div className="flex h-screen bg-surface">
      <aside className="w-[220px] flex-shrink-0 bg-canvas border-r border-hairline flex flex-col">
        <div className="px-md py-md border-b border-hairline">
          <Brand />
          <div className="mt-2 font-mono text-micro text-steel tracking-wide">
            {new Date().toISOString().slice(0, 10)}
          </div>
        </div>

        <nav className="px-2 py-md flex flex-col gap-0.5">
          <div className="px-2.5 pb-1 text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
            Index
          </div>
          {navItems.map((item) => (
            <SidebarNavItem key={item.to} to={item.to} code={item.code}>
              {item.label}
            </SidebarNavItem>
          ))}
        </nav>

        <div className="mt-auto flex flex-col gap-md pb-md">
          <SidebarStatus />
          {showEstop && (
            <div className="px-md">
              <EStopButton />
            </div>
          )}
          <div className="px-md flex justify-between font-mono text-micro text-stone tracking-wide pt-md border-t border-hairline-soft">
            <span>v0.42</span>
            <span>build —</span>
          </div>
        </div>
      </aside>

      <main className="flex-1 flex flex-col min-w-0 min-h-0 overflow-auto">
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  );
}
```

**Note:** `main` keeps `overflow-auto` here so the as-yet-unrewritten page bodies (`DatasetsPage`, `EpisodesPage`, `SettingsPage`, and `RecordPage` until Phase 3) continue to scroll. `RecordPage`'s Phase 3 rewrite handles the no-scroll requirement *internally* (by making its root `h-full` + grid sizing that fits to viewport) — `main`'s `overflow-auto` becomes a no-op when content fits, and active when it doesn't.

The old `max-w-[1280px] mx-auto px-lg py-md` wrapper is intentionally **dropped**. Pages now own their own padding/width via their `PageHeader` and body wrappers. Until each page is rewritten, its body will look flush-left and full-width — that's acceptable for one PR's lifespan and is visually consistent with the new shell's intent.

- [ ] **Step 2: Type-check**

Run: `pnpm --dir frontend exec tsc --noEmit`
Expected: success.

- [ ] **Step 3: Smoke at 1440×900**

Visit Datasets, Episodes, Settings. Verify they render (full-width, no padding wrapper) without console errors. Long lists (e.g., 10+ datasets) **must scroll** — if any page clips, fix by adding a temporary `p-xl` wrapper before merging this commit. Long `RecordPage` (idle state with config form) scrolls similarly.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Layout.tsx
git commit -m "refactor(layout): new sidebar with §-codes, status, global E-Stop slot"
```

---

### Task 16: Remove `<EStopButton />` from `RecordPage.tsx`

Surgical removal. `RecordPage` body rewrites in Phase 3; this task only deletes the per-page E-Stop render so the global one takes over.

**Files:**
- Modify: `frontend/src/pages/RecordPage.tsx`

- [ ] **Step 1: Delete the import and the render block**

Edit instructions (find and remove):

Imports section — delete:
```tsx
import EStopButton from "../components/EStopButton.tsx";
```

Render block — delete the entire `{robot === "rebotarm" && ( ... )}` block currently at lines 148-152:
```tsx
{robot === "rebotarm" && (
  <div className="mb-md">
    <EStopButton />
  </div>
)}
```

- [ ] **Step 2: Type-check**

Run: `pnpm --dir frontend exec tsc --noEmit`
Expected: success (the `robot` variable usage drops; if TS complains about unused, it's a destructured Zustand selector — leave it for Phase 3 cleanup or remove the unused selector now).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/RecordPage.tsx
git commit -m "refactor(record): remove per-page E-Stop (now global in sidebar)"
```

---

### Task 17: Remove the inline E-Stop button from `InferencePage.tsx`

**Important — the InferencePage E-Stop is NOT a `<EStopButton />` import.** It is an inline `<Button variant="destructive" size="lg" onClick={() => s.emergencyStop()}>E-STOP</Button>` rendered in the page header (`InferencePage.tsx:68-70` at time of writing), where `s` is `useInferenceStore()`. The page also renders a "Robot under model control — use E-STOP to halt" warning banner (`InferencePage.tsx:118-120`).

**Files:**
- Modify: `frontend/src/pages/InferencePage.tsx`

- [ ] **Step 1: Inspect what `s.emergencyStop()` does**

```bash
grep -n "emergencyStop" frontend/src/state/inference-store.ts
```

Read the function body. Two cases:

- **Case A — it only POSTs to the same `/api/estop` endpoint that `useEstop()` (in `api/queries.ts`) calls.** Safe to delete the inline button entirely; the new global sidebar E-Stop covers Inference.
- **Case B — it does additional inference-specific cleanup** (clearing the model, stopping the inference WS, resetting phase). Keep the cleanup logic but refactor: stop binding it to the page button. Instead, have the global sidebar E-Stop trigger an effect in `InferencePage` (subscribe to the same backend event the sidebar's `useEstop` fires, or subscribe to a Zustand flag the sidebar sets). For Case B, **defer this task** — open a follow-up issue "wire global E-Stop to inference cleanup" and leave the inline button in place for now. The duplicate is acceptable; the alternative (deleting it without preserving cleanup) is unsafe.

- [ ] **Step 2: If Case A, delete the inline button**

In the JSX (around lines 67–71), remove:

```tsx
<Button variant="destructive" size="lg" onClick={() => s.emergencyStop()}>
  E-STOP
</Button>
```

The wrapping `<header>` flex container stays.

Also remove the warning banner (around lines 117–121):

```tsx
{isLive && (
  <div className="rounded-md border border-brand-warn/40 bg-brand-warn/15 px-3 py-2 text-sm font-semibold text-brand-warn">
    ⚠ Robot under model control — use E-STOP to halt
  </div>
)}
```

The "Robot under model control" message stays useful but is now decoupled from a CTA — leave a softer one-line indicator if you want, but no E-STOP reference.

- [ ] **Step 3: Type-check**

Run: `pnpm --dir frontend exec tsc --noEmit`
Expected: success. If `Button` becomes an unused import, remove it.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/InferencePage.tsx
git commit -m "refactor(inference): remove per-page E-Stop (now global in sidebar)"
```

(If Case B applied, commit nothing for this task; create an issue and proceed to Task 18.)

---

### Task 18: Delete `/mocks/*` files & routes

Remove the four mock pages and `sample-data.ts`; remove the imports and `<Route>` entries in `App.tsx`.

**Files:**
- Delete: `frontend/src/pages/mocks/MockMissionControl.tsx`
- Delete: `frontend/src/pages/mocks/MockEditorial.tsx`
- Delete: `frontend/src/pages/mocks/MockNotebook.tsx`
- Delete: `frontend/src/pages/mocks/MockIndex.tsx`
- Delete: `frontend/src/pages/mocks/sample-data.ts`
- Delete: `frontend/src/pages/mocks/` (now empty)
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Delete the directory**

```bash
git rm -r frontend/src/pages/mocks/
```

- [ ] **Step 2: Edit `App.tsx` — remove the 4 mock imports and the 4 `<Route>` lines**

Resulting `App.tsx` (replace verbatim):

```tsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Layout from "./components/Layout";
import { ErrorBoundary } from "./components/ErrorBoundary";
import DatasetsPage from "./pages/DatasetsPage";
import RecordPage from "./pages/RecordPage";
import EpisodesPage from "./pages/EpisodesPage";
import ReplayPage from "./pages/ReplayPage";
import SettingsPage from "./pages/SettingsPage";
import { InferencePage } from "./pages/InferencePage";

const queryClient = new QueryClient();

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<Navigate to="/datasets" replace />} />
              <Route path="/datasets" element={<DatasetsPage />} />
              <Route path="/record" element={<RecordPage />} />
              <Route path="/datasets/:ds/episodes" element={<EpisodesPage />} />
              <Route path="/datasets/:ds/episodes/:idx/replay" element={<ReplayPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/inference" element={<InferencePage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
```

- [ ] **Step 3: Type-check & build**

```bash
pnpm --dir frontend exec tsc --noEmit
pnpm --dir frontend build
```

Expected: both succeed.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/pages/mocks
git commit -m "chore(mocks): remove /mocks exploration pages and routes"
```

---

### Task 19: Phase 2 gate — smoke pass

- [ ] **Step 1: Start dev server**

```bash
pnpm --dir frontend dev
```

- [ ] **Step 2: In a browser at 1440×900, click through each page and verify:**

- New sidebar renders with brand glyph, §-numbered nav, Status block, version footer.
- E-Stop **does not appear** when no session is active (and you have no robot connected).
- E-Stop **appears** after starting a `rebotarm` session (manual test, optional if no hardware — verify by temporarily hard-coding `const robot = "rebotarm"; const state = "ready";` inside `Layout.tsx` for one render, confirm the slot appears at sidebar bottom, then revert the change before committing).
- No `/mocks/*` route resolves (`http://localhost:5173/mocks/mission-control` should 404 / redirect).
- The four primary pages (Datasets, Record, Episodes after clicking into a dataset, Settings) load without console errors.
- Replay page renders if you have any episodes; Inference loads.

- [ ] **Step 3: Stop dev server, tag commit**

```bash
git tag ui-modlab-phase-2
```

**Phase 2 complete.** Shell shipped, safety affordance centralized, mocks gone.

---

## Phase 3 — `RecordPage` rewrite (single-viewport grid)

This is the largest visual change. Build it in 5 task chunks so each commit is reviewable.

### Task 20: Convert `RecordPage` shell to PageHeader + viewport grid skeleton

Replace the page's outer wrapper with the new `PageHeader` + a body element styled for `flex-1 grid grid-cols-3 grid-rows-2`. Camera previews, telemetry, controls etc. continue to render in their existing positions for one commit (so the page is "ugly but visible"). Subsequent tasks slot real components into the grid cells.

**Files:**
- Modify: `frontend/src/pages/RecordPage.tsx`

- [ ] **Step 1: Inspect current structure**

```bash
grep -n "useSessionStore\|useEpisodes\|EEMonitor\|RecordingControls\|CameraPreview\|KeyboardTeleop\|SessionConfigForm" frontend/src/pages/RecordPage.tsx
```

- [ ] **Step 2: Replace `RecordPage.tsx` with the skeleton**

This replaces the active-session branch only. The idle branch keeps the existing `SessionConfigForm` wrapped in a `Card variant="feature"`.

```tsx
import { useEffect, useState } from "react";
import { useSessionStore } from "../state/session-store.ts";
import { useEndSession, useEpisodes, useSessionState } from "../api/queries.ts";
import { WsConnection } from "../api/ws.ts";
import SessionConfigForm from "../components/SessionConfigForm.tsx";
import CameraPreview from "../components/CameraPreview.tsx";
import RecordingControls from "../components/RecordingControls.tsx";
import KeyboardTeleop from "../components/KeyboardTeleop.tsx";
import EEMonitor from "../components/EEMonitor.tsx";
import IdlePoseCaptureButton from "../components/IdlePoseCaptureButton.tsx";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { PageHeader } from "../components/ui/page-header";
import { Badge } from "../components/ui/badge";
import type { EpisodeProgress, ReplayProgress } from "../api/types.ts";

function RecBadge({ elapsedSec }: { elapsedSec: number }) {
  const m = Math.floor(elapsedSec / 60).toString().padStart(2, "0");
  const s = Math.floor(elapsedSec % 60).toString().padStart(2, "0");
  return (
    <span className="inline-flex items-center gap-2 px-2.5 py-1 rounded-sm border border-brand-error/40 bg-brand-error/10 text-brand-error font-mono text-micro tracking-[0.08em]">
      <span className="w-1.5 h-1.5 rounded-full bg-brand-error animate-pulse" />
      REC {m}:{s}
    </span>
  );
}

/**
 * Detect whether the viewport is large enough for the no-scroll RecordPage
 * layout (width ≥ 1280 AND height ≥ 900). Tailwind's `max-[Xpx]:` only
 * targets width, so we resolve this in JS and conditionally apply classes.
 */
function useFitsRecordViewport() {
  const [fits, setFits] = useState(() =>
    typeof window === "undefined"
      ? true
      : window.innerWidth >= 1280 && window.innerHeight >= 900,
  );
  useEffect(() => {
    const check = () =>
      setFits(window.innerWidth >= 1280 && window.innerHeight >= 900);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);
  return fits;
}

export default function RecordPage() {
  const sessionState = useSessionStore((s) => s.state);
  const subState = useSessionStore((s) => s.subState);
  const cameras = useSessionStore((s) => s.cameras);
  const gopros = useSessionStore((s) => s.gopros);
  const previewEnabled = useSessionStore((s) => s.previewEnabled);
  const dataset = useSessionStore((s) => s.dataset);
  const task = useSessionStore((s) => s.task);
  const robot = useSessionStore((s) => s.robot);
  const teleop = useSessionStore((s) => s.teleop);
  const mode = useSessionStore((s) => s.mode);
  const fps = useSessionStore((s) => s.fps);
  const progress = useSessionStore((s) => s.episodeProgress);
  const setSessionState = useSessionStore((s) => s.setSessionState);
  const setEpisodeProgress = useSessionStore((s) => s.setEpisodeProgress);
  const setReplayProgress = useSessionStore((s) => s.setReplayProgress);
  const setError = useSessionStore((s) => s.setError);
  const endSession = useEndSession();
  const { data: episodes } = useEpisodes(dataset || "");

  const { data: apiState } = useSessionState();
  useEffect(() => {
    if (apiState && apiState.state !== "idle") {
      setSessionState(apiState as unknown as Record<string, unknown>);
    }
  }, [apiState, setSessionState]);

  const isIdle = sessionState === "idle";
  useEffect(() => {
    if (isIdle) return;
    const conn = new WsConnection("/ws/session");
    conn.onMessage((msg) => {
      const msgType = msg.type as string | undefined;
      const msgData = msg.data as Record<string, unknown> | undefined;
      if (!msgType || !msgData) return;
      if (msgType === "session_state") setSessionState(msgData);
      if (msgType === "episode_progress") setEpisodeProgress(msgData as unknown as EpisodeProgress);
      if (msgType === "replay_progress") setReplayProgress(msgData as unknown as ReplayProgress);
      if (msgType === "error")
        setError(msgData as unknown as { error: string; message: string });
    });
    conn.connect();
    return () => conn.disconnect();
  }, [isIdle, setSessionState, setEpisodeProgress, setReplayProgress, setError]);

  // CRITICAL — hooks must be called unconditionally and in the same order
  // every render. `useFitsRecordViewport` lives BEFORE the idle-branch
  // early return below; the value is unused in the idle branch but the
  // hook still runs (Rules of Hooks compliance).
  const fits = useFitsRecordViewport();

  // Idle branch
  if (sessionState === "idle") {
    return (
      <>
        <PageHeader code="§02" title="Configure session" />
        <div className="p-xl overflow-auto">
          <Card variant="feature">
            <SessionConfigForm onStarted={() => {}} />
          </Card>
        </div>
      </>
    );
  }

  // EpisodeProgress only carries num_frames + writer counters
  // (frontend/src/api/types.ts:43-49). Derive elapsed from frames / fps;
  // when fps is unknown, fall back to showing —.
  const elapsedSec =
    progress && fps && fps > 0 ? progress.num_frames / fps : 0;

  return (
    <>
      <PageHeader
        code="§02"
        title={
          task ? (
            <>
              Live capture <span className="text-steel">— {task}</span>
            </>
          ) : (
            "Live capture"
          )
        }
        state={
          sessionState === "recording" ? (
            <RecBadge elapsedSec={elapsedSec} />
          ) : (
            <Badge variant="outline">{sessionState}</Badge>
          )
        }
        actions={
          <Button variant="secondary" size="sm" onClick={() => endSession.mutate()}>
            End session
          </Button>
        }
      />

      {/* Brief strip (one row, key-value pills) */}
      <div className="flex flex-wrap items-center gap-md px-xl py-2 border-b border-hairline bg-canvas text-caption flex-shrink-0">
        <Brief k="Dataset" v={dataset ?? "—"} mono />
        <Brief k="Robot" v={robot ?? "—"} />
        <Brief k="Mode" v={mode ?? "—"} />
        <Brief k="Teleop" v={teleop ?? "—"} />
        <Brief k="Cameras" v={[...cameras, ...gopros].join(" · ") || "—"} mono />
        <Brief k="Episodes" v={`${episodes?.length ?? 0} saved`} />
      </div>

      {/* Body grid — placeholders for now; subsequent tasks slot real
          InstrumentWell / telemetry rail / episode progress / xy plot.
          Viewport-fit is detected in JS (`useFitsRecordViewport`) because
          Tailwind's max-[Xpx]: only targets width — we need width *and*
          height. */}
      <div
        className={
          "flex-1 min-h-0 p-xl grid gap-sm " +
          (fits
            ? "grid-cols-[1fr_1fr_380px] grid-rows-[1.35fr_1fr] overflow-hidden"
            : "grid-cols-1 overflow-auto")
        }
      >
        {/* Row 1, col 1 — cam front placeholder */}
        <div className="bg-canvas-dark rounded-md min-h-[200px] grid place-items-center text-on-dark-dim text-caption">
          cam · front (placeholder)
          {cameras[0] && previewEnabled && <CameraPreview camName={cameras[0]} />}
        </div>
        {/* Row 1, col 2 — cam wrist placeholder */}
        <div className="bg-canvas-dark rounded-md min-h-[200px] grid place-items-center text-on-dark-dim text-caption">
          cam · wrist (placeholder)
          {cameras[1] && previewEnabled && <CameraPreview camName={cameras[1]} />}
        </div>
        {/* Right rail spans both rows — telemetry placeholder */}
        <div className="row-span-2 bg-canvas border border-hairline rounded-md p-md flex flex-col gap-md">
          <div className="text-caption text-steel">telemetry (placeholder)</div>
          <EEMonitor enabled />
          {teleop === "web_keyboard" && (
            <KeyboardTeleop enabled={sessionState !== "review"} />
          )}
          <IdlePoseCaptureButton />
        </div>
        {/* Row 2, col 1 — episode progress placeholder */}
        <div className="bg-canvas border border-hairline rounded-md p-md text-caption text-steel">
          episode progress (placeholder)
        </div>
        {/* Row 2, col 2 — xy plot placeholder */}
        <div className="bg-canvas-dark rounded-md min-h-[140px] grid place-items-center text-on-dark-dim text-caption">
          xy trajectory (placeholder)
        </div>
      </div>

      {/* Controls bar */}
      <div className="border-t border-hairline bg-canvas px-xl py-2 flex items-center gap-2 flex-shrink-0">
        <RecordingControls />
      </div>
    </>
  );
}

function Brief({ k, v, mono }: { k: string; v: React.ReactNode; mono?: boolean }) {
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
        {k}
      </span>
      <span className={mono ? "font-mono text-caption text-ink" : "text-ink"}>{v}</span>
    </span>
  );
}
```

- [ ] **Step 3: Type-check + smoke**

```bash
pnpm --dir frontend exec tsc --noEmit
```

Then in browser (with dev server running), start a recording session. Verify:

- New PageHeader sits at the top with `§02 · Record`.
- Brief strip below has key/value pairs.
- Body grid shows 5 placeholders (2 cams + telemetry rail + episode progress + xy plot) at 1440×900.
- At 1200×800, the body switches to a 1-column scrollable layout.
- Controls bar at the bottom still shows the existing RecordingControls.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/RecordPage.tsx
git commit -m "feat(record): PageHeader + viewport-locked grid skeleton (placeholders)"
```

---

### Task 21: Slot real InstrumentWell cameras

Replace the two camera placeholders with `<InstrumentWell>` wrapping `<CameraPreview>`.

**Files:**
- Modify: `frontend/src/pages/RecordPage.tsx`

- [ ] **Step 1: Replace the two camera placeholder divs**

For each of the first two cells in the grid, replace the placeholder div with:

```tsx
{/* cam · 01 · front */}
<InstrumentWell
  header={`CAM · 01 · ${cameras[0] ?? "FRONT"}`}
  live={!!cameras[0] && previewEnabled}
  caption={
    cameras[0] && (
      <div className="flex justify-between">
        <span>fixed</span>
        <span className="font-mono text-brand-green">live</span>
      </div>
    )
  }
>
  {cameras[0] && previewEnabled ? (
    <CameraPreview camName={cameras[0]} />
  ) : (
    <div className="grid place-items-center h-full text-on-dark-dim">no stream</div>
  )}
</InstrumentWell>
```

Repeat for the wrist camera (`cameras[1]`). Add the import:

```tsx
import { InstrumentWell } from "../components/ui/instrument-well";
```

Remove the now-unused placeholder JSX (`<div className="bg-canvas-dark ...">cam · front (placeholder)</div>` etc.).

- [ ] **Step 2: Type-check**

Run: `pnpm --dir frontend exec tsc --noEmit`
Expected: success.

- [ ] **Step 3: Smoke at 1440×900**

Verify the two cameras render inside dark wells with corner ticks, LIVE indicator, and caption strip.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/RecordPage.tsx
git commit -m "feat(record): swap camera placeholders for InstrumentWell"
```

---

### Task 22: Build the telemetry rail (joint sparklines + EE pose)

Replace the right-rail placeholder with two stacked blocks: joint positions (sparklines fed by `useJointHistory`, which subscribes to `/ws/state`) and the current EE pose (subscribed directly to `/ws/state`, the same channel `EEMonitor` already uses). The existing `<EEMonitor />` render inside the rail placeholder is **removed** in this task — `EEBlock` is its replacement.

**Files:**
- Modify: `frontend/src/pages/RecordPage.tsx`

- [ ] **Step 1: Add the imports**

```tsx
import { useRef } from "react";  // add to the existing react import
import { Sparkline } from "../components/ui/sparkline";
import { useJointHistory } from "../hooks/useJointHistory";
import { SectionMark } from "../components/ui/section-mark";
```

- [ ] **Step 2: Remove `EEMonitor` from imports and from the rail placeholder**

The placeholder rail in Task 20 currently renders `<EEMonitor enabled />`. Delete that JSX (and the `EEMonitor` import line).

- [ ] **Step 3: Replace the placeholder right-rail with two sub-blocks**

```tsx
<aside className="row-span-2 flex flex-col gap-sm min-h-0">
  <JointBlock enabled={sessionState !== "idle"} />
  <EEBlock enabled={sessionState !== "idle"} />
</aside>
```

- [ ] **Step 4: Add the two sub-components at the bottom of the file**

```tsx
function JointBlock({ enabled }: { enabled: boolean }) {
  // Initial hint; the hook adapts to the actual sample length on the first
  // WS message and re-allocates buffers if joint count grows.
  const NUM_JOINTS_HINT = 7;
  const history = useJointHistory(enabled, NUM_JOINTS_HINT);
  const numJoints = history.length;
  const latest = (i: number) => {
    const s = history[i];
    return s && s.length > 0 ? s[s.length - 1] : null;
  };

  return (
    <section className="flex-[1.4] min-h-0 bg-canvas border border-hairline rounded-md p-md flex flex-col">
      <header className="mb-xs flex items-baseline gap-xs">
        <SectionMark code="§02.B" name="joint positions" />
        <span className="font-mono text-micro text-stone">rad · 100 Hz</span>
      </header>
      <table className="w-full text-caption">
        <tbody>
          {Array.from({ length: numJoints }).map((_, i) => {
            const v = latest(i);
            return (
              <tr key={i} className="border-b border-dashed border-hairline-soft last:border-b-0">
                <td className="py-1 font-mono text-micro text-steel w-[36px]">J{i + 1}</td>
                <td className="py-1 text-right font-mono text-caption text-ink tabular-nums w-[80px]">
                  {v === null ? "—" : v.toFixed(4)}
                </td>
                <td className="py-1 pl-3">
                  <Sparkline data={history[i] ?? []} tone="ok" />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

interface EeSnapshot {
  pos: number[] | null;
  rotvec: number[] | null;
}

function EEBlock({ enabled }: { enabled: boolean }) {
  const [snap, setSnap] = useState<EeSnapshot>({ pos: null, rotvec: null });
  const connRef = useRef<WsConnection | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const conn = new WsConnection("/ws/state");
    connRef.current = conn;
    conn.onMessage((msg) => {
      const m = msg as { ee_pos?: number[]; ee_rotvec?: number[] };
      setSnap((prev) => ({
        pos: m.ee_pos ?? prev.pos,
        rotvec: m.ee_rotvec ?? prev.rotvec,
      }));
    });
    conn.connect();
    return () => {
      conn.disconnect();
      connRef.current = null;
    };
  }, [enabled]);

  const fmt = (n: number | undefined, d = 4) =>
    typeof n === "number" ? n.toFixed(d) : "—";

  const rows: [string, string, string][] = [
    ["X", fmt(snap.pos?.[0]), "m"],
    ["Y", fmt(snap.pos?.[1]), "m"],
    ["Z", fmt(snap.pos?.[2]), "m"],
    ["rx", fmt(snap.rotvec?.[0], 3), "rad"],
    ["ry", fmt(snap.rotvec?.[1], 3), "rad"],
    ["rz", fmt(snap.rotvec?.[2], 3), "rad"],
  ];

  return (
    <section className="flex-1 min-h-0 bg-canvas border border-hairline rounded-md p-md flex flex-col">
      <header className="mb-xs">
        <SectionMark code="§02.B" name="end-effector pose" />
      </header>
      <table className="w-full text-caption">
        <tbody>
          {rows.map(([k, v, u]) => (
            <tr key={k} className="border-b border-dashed border-hairline-soft last:border-b-0">
              <td className="py-1 font-mono text-micro text-steel w-[44px]">{k}</td>
              <td className="py-1 text-right font-mono text-caption text-ink tabular-nums w-[80px]">{v}</td>
              <td className="py-1 pl-2 font-mono text-micro text-stone">{u}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
```

**Note:** the EE pose row labels are `rx`/`ry`/`rz` (rotation-vector components) rather than `roll/pitch/yaw` — `/ws/state` emits a Rodrigues rotation vector (`ee_rotvec`), not Euler angles. The mock used "roll/pitch/yaw" — adjust the mock terminology in your head; the backend never produced Euler.

- [ ] **Step 5: Type-check + smoke**

```bash
pnpm --dir frontend exec tsc --noEmit
```

Start a session; verify the right rail populates joint values + sparklines + EE pose live. When idle, both blocks render with `—` placeholders.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/RecordPage.tsx
git commit -m "feat(record): telemetry rail with joint sparklines + EE pose (/ws/state)"
```

---

### Task 23: Build the episode-progress block

Replace the bottom-row-col-1 placeholder with a real block: big elapsed time + a small grid of real metrics drawn from the actually-emitted `EpisodeProgress` fields (`num_frames`, `ticks_skipped`, `writer_lag_ms`, `writer_queue_depth`, `stale_sample_count` — see `frontend/src/api/types.ts:43-49`) plus `fps` and the saved-episode count.

**Files:**
- Modify: `frontend/src/pages/RecordPage.tsx`

- [ ] **Step 1: Replace the placeholder with the new block**

```tsx
function EpisodeProgressBlock({
  inProgressIndex,
}: {
  inProgressIndex: number;
}) {
  const progress = useSessionStore((s) => s.episodeProgress);
  const fps = useSessionStore((s) => s.fps);

  // Derive elapsed from frames / fps (the backend doesn't ship an explicit
  // elapsed_sec — keep this consistent with the top-bar RecBadge).
  const elapsedSec =
    progress && fps && fps > 0 ? progress.num_frames / fps : 0;
  const m = Math.floor(elapsedSec / 60).toString().padStart(2, "0");
  const s = Math.floor(elapsedSec % 60).toString().padStart(2, "0");

  return (
    <section className="bg-canvas border border-hairline rounded-md p-md flex flex-col">
      <header className="mb-2 flex items-baseline justify-between">
        <SectionMark code="§02.B" name="episode progress" />
        <span className="font-mono text-micro text-stone">
          capturing ep <span className="text-ink">{inProgressIndex}</span>
        </span>
      </header>
      <div className="flex items-baseline gap-2">
        <span className="text-heading-2 font-semibold tracking-tight tabular-nums">
          {m}:{s}
        </span>
        <span className="text-caption text-steel">elapsed</span>
      </div>
      <div className="grid grid-cols-3 gap-x-md gap-y-1 mt-md text-caption">
        <Cell k="Frames" v={progress?.num_frames ?? "—"} mono />
        <Cell k="FPS tgt." v={fps?.toFixed(2) ?? "—"} mono tone="ok" />
        <Cell k="Ticks skipped" v={progress?.ticks_skipped ?? 0} mono />
        <Cell
          k="Writer lag"
          v={
            typeof progress?.writer_lag_ms === "number"
              ? `${progress.writer_lag_ms.toFixed(0)} ms`
              : "—"
          }
          mono
          tone={(progress?.writer_lag_ms ?? 0) > 50 ? "warn" : "ok"}
        />
        <Cell
          k="Queue"
          v={progress?.writer_queue_depth ?? 0}
          mono
          tone={(progress?.writer_queue_depth ?? 0) > 5 ? "warn" : "ok"}
        />
        <Cell k="Stale samples" v={progress?.stale_sample_count ?? 0} mono />
      </div>
    </section>
  );
}

function Cell({
  k,
  v,
  mono,
  tone,
}: {
  k: string;
  v: React.ReactNode;
  mono?: boolean;
  tone?: "ok" | "warn";
}) {
  const color =
    tone === "ok"
      ? "text-brand-green-deep"
      : tone === "warn"
      ? "text-brand-warn"
      : "text-ink";
  return (
    <>
      <span className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
        {k}
      </span>
      <span
        className={
          (mono ? "font-mono text-caption tabular-nums " : "text-caption ") + color
        }
      >
        {String(v)}
      </span>
    </>
  );
}
```

Then slot the section in place of the placeholder. Compute the in-progress episode index at the page level from the existing `episodes` query result:

```tsx
const inProgressIndex = (episodes?.length ?? 0) + 1;
// ...
<EpisodeProgressBlock inProgressIndex={inProgressIndex} />
```

**Note on the field choices.** "FPS tgt." reflects the *target* fps from the session (the actual achieved frame rate is approximated by `num_frames / elapsed`, which is just `fps` by construction during good operation). "Ticks skipped" / "Writer lag" / "Queue" are the real health signals the backend already emits and are useful to surface to the operator — they replace the speculative "FPS act. / Drops / Auto-save" that didn't exist.

- [ ] **Step 2: Type-check + smoke**

Run: `pnpm --dir frontend exec tsc --noEmit`

Visual: bottom-row col 1 shows the big elapsed time and a 3×2 grid of real metrics. Writer-lag / queue thresholds turn amber when exceeded.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/RecordPage.tsx
git commit -m "feat(record): episode progress block (real EpisodeProgress fields)"
```

---

### Task 24: Build the XY-trajectory plot block

Replace the bottom-row-col-2 placeholder with a small dark `InstrumentWell` plotting EE XY trajectory over the last 8 s.

**Files:**
- Modify: `frontend/src/pages/RecordPage.tsx`

- [ ] **Step 1: Add a small XY plot component and slot it in**

For now, a static placeholder plot until a proper rolling EE buffer hook exists — the structure is the deliverable.

```tsx
function XYPlot() {
  // TODO follow-up: add a rolling EE XY buffer hook similar to useJointHistory.
  // For now, render the well with an empty-state grid so the visual lands.
  return (
    <InstrumentWell
      header="EE · XY TRAJECTORY · LAST 8 s"
      live
    >
      <svg viewBox="0 0 360 110" preserveAspectRatio="none" className="w-full h-full">
        <defs>
          <pattern id="xy-grid" width="24" height="22" patternUnits="userSpaceOnUse">
            <path d="M 24 0 L 0 0 0 22" fill="none" stroke="var(--color-hairline-dark)" strokeWidth="0.5" />
          </pattern>
        </defs>
        <rect width="360" height="110" fill="url(#xy-grid)" />
        {/* Empty — wired up in follow-up */}
      </svg>
    </InstrumentWell>
  );
}
```

Slot it where the xy-plot placeholder is.

- [ ] **Step 2: Type-check + smoke**

Verify the well renders with corner ticks and a faint grid background.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/RecordPage.tsx
git commit -m "feat(record): XY trajectory well (empty state for now)"
```

---

### Task 25: Rebuild the controls bar

Replace the inline `<RecordingControls />` with a controls bar matching the v3 mock. Since `RecordingControls.tsx` is a deep component coupling keyboard / state-machine logic, the bar simply renders it but with a new wrapper providing the prefix label and inline arrangement.

**Files:**
- Modify: `frontend/src/pages/RecordPage.tsx`

- [ ] **Step 1: Replace the controls bar wrapper**

```tsx
<div className="border-t border-hairline bg-canvas px-xl py-2 flex items-center gap-3 flex-shrink-0 min-h-[52px]">
  <span className="font-mono text-caption text-steel">
    capturing episode <span className="text-ink">{inProgressIndex}</span>
  </span>
  <span className="w-px h-5 bg-hairline" />
  <RecordingControls />
</div>
```

(`inProgressIndex` is the page-level constant introduced in Task 23 — `(episodes?.length ?? 0) + 1`.)

If `RecordingControls` rendering produces too much visual weight, that's a follow-up `RecordingControls` refactor — out of scope for this task. The wrapper alone gives the page the new "thin controls bar" footprint.

- [ ] **Step 2: Smoke**

Verify: bottom of viewport has a single thin bar with the prefix label and the existing recording controls.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/RecordPage.tsx
git commit -m "feat(record): wrap RecordingControls in thin controls bar"
```

---

### Task 26: Phase 3 gate — viewport verification

- [ ] **Step 1: Build + serve**

```bash
pnpm --dir frontend build
pnpm --dir frontend preview --port 5173
```

- [ ] **Step 2: In a browser, resize to exactly 1440×900 and start a session**

Verify: no scrollbar. All five body cells visible. Top bar + brief + body + controls fit perfectly.

- [ ] **Step 3: Resize to 1280×900**

Verify: still no scrollbar. Camera cells become noticeably narrower (~304 px). Telemetry rail at 380 px. All readable.

- [ ] **Step 4: Resize to 1200×800**

Verify: layout switches to single-column scrollable layout. Telemetry rail is now below the cameras (or to their right depending on flex behaviour). Nothing overlapping or truncated.

- [ ] **Step 5: Tag**

```bash
git tag ui-modlab-phase-3
```

**Phase 3 complete.** Record page in final form.

---

## Phase 4 — `DatasetsPage` rewrite

### Task 27: Rewrite `DatasetsPage` shell — PageHeader + summary + toolbar skeleton

**Files:**
- Modify: `frontend/src/pages/DatasetsPage.tsx`

- [ ] **Step 1: Replace the page's outer wrapper with PageHeader + the new summary block**

Replace the existing `<header>` and the summary that wraps everything. The body (DatasetCard list) stays for now; we rewrite cards in the next task.

```tsx
import { PageHeader } from "../components/ui/page-header";
// ...
return (
  <>
    <PageHeader
      code="§01"
      title="Catalogue"
      meta={
        <span className="font-mono text-micro text-stone">
          {datasets?.length ?? 0} collections
        </span>
      }
      actions={
        <>
          <HubAuthPill auth={auth} loading={authLoading} onRefresh={refreshAuth} />
          <Button size="sm" onClick={() => setCreating(true)}>+ New dataset</Button>
        </>
      }
    />

    <div className="flex-1 overflow-auto">
      <div className="max-w-[1240px] mx-auto px-xl py-xl">
        {/* Summary stats — to be filled in next task */}
        <SummaryBlock datasets={datasets ?? []} />

        {/* Existing dataset list, untouched for now */}
        {isLoading ? (
          <p className="text-steel">Loading...</p>
        ) : !datasets?.length ? (
          <p className="text-steel">No datasets yet. Click "+ New dataset" to create one.</p>
        ) : (
          <div className="flex flex-col gap-md">
            {datasets.map((ds) => (
              <DatasetCard /* ... existing props ... */ />
            ))}
          </div>
        )}

        {/* existing annotation footer kept */}
      </div>
    </div>
  </>
);

function SummaryBlock({ datasets }: { datasets: Array<{ name: string; num_episodes: number; total_frames: number }> }) {
  const totalEp = datasets.reduce((s, d) => s + d.num_episodes, 0);
  const totalFr = datasets.reduce((s, d) => s + d.total_frames, 0);
  return (
    <div className="flex items-end justify-between gap-xl pb-xl border-b border-hairline mb-xl">
      <div>
        <h2 className="text-heading-2 text-ink leading-tight">Recorded data, sorted by recency.</h2>
        <p className="text-body-sm text-steel mt-2 max-w-[640px]">
          {datasets.length} active datasets — review status, push to Hub, export, or annotate.
        </p>
      </div>
      <div className="flex gap-xl items-baseline text-right">
        <Stat label="datasets" value={datasets.length} />
        <Stat label="episodes" value={totalEp} />
        <Stat label="frames" value={totalFr.toLocaleString()} />
      </div>
    </div>
  );
}
function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col items-end gap-0.5">
      <span className="font-mono text-heading-3 text-ink tabular-nums leading-none">{value}</span>
      <span className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">{label}</span>
    </div>
  );
}
```

(Existing `HubAuthPill` and the rest of `DatasetsPage.tsx` keep their definitions — the wrapper change is the deliverable.)

- [ ] **Step 2: Type-check + smoke**

Run: `pnpm --dir frontend exec tsc --noEmit`
Visual: new top bar, big "Catalogue" heading with stats. Cards still old.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/DatasetsPage.tsx
git commit -m "feat(datasets): PageHeader + Catalogue heading + summary stats"
```

---

### Task 28: Rewrite `DatasetCard` body — new card structure

**Files:**
- Modify: `frontend/src/pages/DatasetsPage.tsx`

- [ ] **Step 1: Add `index` to `DatasetCardProps` and the call site**

Find `interface DatasetCardProps` (currently around lines 198–207) and add a required `index` field:

```tsx
interface DatasetCardProps {
  ds: { name: string; num_episodes: number; total_frames: number };
  index: number;                       // <-- new
  auth: AuthStatus | null;
  isAnnotating: boolean;
  annotatingAny: boolean;
  annotateProgress: AnnotateProgress | null;
  onAnnotate: () => void;
  onExport: () => void;
  onDelete: () => void;
}
```

Update the caller (in `DatasetsPage`'s map over `datasets`) — currently `datasets.map((ds) => <DatasetCard ... />)`:

```tsx
{sorted.map((ds, i) => (
  <DatasetCard
    key={ds.name}
    ds={ds}
    index={i + 1}
    auth={auth}
    isAnnotating={annotating === ds.name}
    annotatingAny={annotating !== null}
    annotateProgress={annotating === ds.name ? progress : null}
    onAnnotate={() => handleAnnotateAll(ds.name)}
    onExport={() => setExportingDataset(ds.name)}
    onDelete={() => {
      if (confirm(`Delete dataset "${ds.name}" and all its episodes?`)) {
        deleteMutation.mutate(ds.name);
      }
    }}
  />
))}
```

(If Task 29's `sorted` is not yet in scope at the time you execute this task, use `datasets.map((ds, i) => ...)` instead — `sorted` is introduced by Task 29.)

Add the destructure in `DatasetCard`'s function signature:

```tsx
function DatasetCard({
  ds,
  index,
  auth,
  isAnnotating,
  annotatingAny,
  annotateProgress,
  onAnnotate,
  onExport,
  onDelete,
}: DatasetCardProps) {
  // ... existing hook calls (useState hub, editing, draft, saving, error) ...
}
```

- [ ] **Step 2: Replace the JSX returned by `DatasetCard`**

The existing `return (...)` has three significant pieces: head/link strip, body with stats + actions + delete, and the conditional edit form / errors / last-pushed footer. The new JSX replaces head + stats + actions, **preserves the conditional `editing` form / error / last-pushed footer verbatim**.

```tsx
return (
  <div className="relative rounded-lg border border-hairline bg-canvas hover:border-stone transition-colors px-xl py-md">
    <CornerTicks tone="light" inset={6} size={8} />

    {/* Head row */}
    <div className="relative flex items-center gap-md mb-1">
      <span className="font-mono text-micro text-stone tracking-wide">
        {String(index).padStart(2, "0")}
      </span>
      <Link to={`/datasets/${ds.name}/episodes`} className="text-heading-5 text-ink hover:text-brand-warn">
        {ds.name}
      </Link>
      <span className="flex-1" />
      <HubStatusBadge hub={hub} />
    </div>

    {/* Fact strip */}
    <div className="relative flex flex-wrap items-baseline gap-x-lg gap-y-1 py-2 border-y border-hairline-soft text-caption">
      <Fact k="Episodes" v={ds.num_episodes} mono />
      <Fact k="Frames" v={ds.total_frames.toLocaleString()} mono />
      {hubConfigured && hub?.config && (
        <Fact k="Hub" v={<CodeInline>{hub.config.repo_id}</CodeInline>} />
      )}
      {hubConfigured && hub?.config?.private && (
        <Fact k="Visibility" v="private" />
      )}
      {hubConfigured && hub?.config?.auto_push && (
        <Fact k="Auto-push" v="on" />
      )}
    </div>

    {/* Actions */}
    <div className="relative flex flex-wrap items-center gap-2 mt-md">
      <Link to={`/datasets/${ds.name}/episodes`}>
        <Button size="sm">Open episodes →</Button>
      </Link>
      {!hubConfigured && (
        <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
          Configure Hub
        </Button>
      )}
      {hubConfigured && (
        <>
          <Button
            variant="secondary"
            size="sm"
            onClick={onPush}
            disabled={!auth?.authenticated || isPushing}
            title={!auth?.authenticated ? "Run huggingface-cli login first" : undefined}
          >
            {isPushing ? "Pushing…" : "↑ Push"}
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
            Edit Hub
          </Button>
        </>
      )}
      <Button variant="secondary" size="sm" onClick={onExport}>Export</Button>
      <Button
        variant="secondary"
        size="sm"
        onClick={onAnnotate}
        disabled={annotatingAny}
      >
        {isAnnotating && annotateProgress
          ? `Annotating ${annotateProgress.done}/${annotateProgress.total}`
          : isAnnotating
          ? "Starting…"
          : "Annotate"}
      </Button>
      <span className="flex-1" />
      <Button variant="destructive" size="sm" onClick={onDelete}>Delete</Button>
    </div>

    {/* === Preserve verbatim from the current file === */}
    {editing && (
      // existing edit form block, unchanged
    )}
    {hub?.state?.last_push_error && !isPushing && (
      // existing last-error block, unchanged
    )}
    {error && (
      // existing error block, unchanged
    )}
    {hubConfigured && hub.state?.last_pushed_at && (
      // existing last-pushed block, unchanged
    )}
  </div>
);
```

**Important:** the four `{... && (...)}` blocks at the bottom (edit form, last-push error, generic error, last-pushed timestamp) must be copied **verbatim** from the current file (today: `DatasetsPage.tsx:392-443`). Do not rewrite them in this task; preserve their existing JSX. Their look will pick up the new Button/Badge styling automatically.

Add the new imports at the top of `DatasetsPage.tsx`:

```tsx
import { CornerTicks } from "../components/ui/corner-ticks";
```

- [ ] **Step 3: Refactor `HubStatusBadge` to use the new `Badge variant="status"`**

```tsx
function HubStatusBadge({ hub }: { hub: HubResponse | null }) {
  if (!hub) return null;
  if (!hub.config) return <Badge variant="status" state="unconfigured" />;
  if (hub.progress.status === "uploading" || hub.progress.status === "queued")
    return <Badge variant="status" state="pushing" />;
  if (hub.progress.status === "error" || hub.state?.last_push_error)
    return <Badge variant="status" state="error" />;
  if (!hub.state?.last_pushed_commit_sha)
    return <Badge variant="status" state="pending" />;
  if (!hub.state.last_pushed_manifest_hash)
    return <Badge variant="status" state="stale" />;
  return <Badge variant="status" state="synced" />;
}
```

- [ ] **Step 4: Add `Fact` helper (local to DatasetsPage)**

```tsx
function Fact({ k, v, mono }: { k: string; v: React.ReactNode; mono?: boolean }) {
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">{k}</span>
      <span className={mono ? "font-mono text-caption text-ink" : "text-ink"}>{v}</span>
    </span>
  );
}
```

- [ ] **Step 5: Type-check + smoke**

Run: `pnpm --dir frontend exec tsc --noEmit`

Visual: each dataset card has corner ticks, mono index, Hub status pill on the right, fact strip, and one primary "Open episodes" button. The edit form / errors / last-pushed footer still appear when relevant.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/DatasetsPage.tsx
git commit -m "feat(datasets): new DatasetCard with corner ticks + status badge + primary CTA"
```

---

### Task 29: Add toolbar (sort / filter / search)

**Files:**
- Modify: `frontend/src/pages/DatasetsPage.tsx`

- [ ] **Step 1: Add the toolbar above the list**

Add local state and the toolbar JSX:

```tsx
const [sort, setSort] = useState<"recency" | "name" | "size">("recency");
const [search, setSearch] = useState("");

const filtered = (datasets ?? []).filter((d) =>
  d.name.toLowerCase().includes(search.toLowerCase()),
);
const sorted = [...filtered].sort((a, b) => {
  if (sort === "name") return a.name.localeCompare(b.name);
  if (sort === "size") return b.num_episodes - a.num_episodes;
  return 0; // recency = preserve API order
});
```

Toolbar JSX (above the list):

```tsx
<div className="flex items-center gap-2 py-2 mb-md border-b border-hairline-soft">
  <ToolbarBtn k="SORT" v={sort} onClick={() =>
    setSort(sort === "recency" ? "name" : sort === "name" ? "size" : "recency")
  } />
  <Input
    placeholder="Search datasets…"
    value={search}
    onChange={(e) => setSearch(e.target.value)}
    className="ml-auto w-[240px]"
  />
</div>
```

Helper:

```tsx
function ToolbarBtn({ k, v, onClick }: { k: string; v: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-caption hover:bg-surface"
    >
      <span className="font-mono text-micro-uppercase text-stone">{k}</span>
      <span className="text-ink font-semibold">{v}</span>
      <span className="text-stone">▾</span>
    </button>
  );
}
```

Replace the `datasets.map(...)` with `sorted.map(...)`.

- [ ] **Step 2: Type-check + smoke**

Verify: clicking SORT cycles values; typing in search filters the list.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/DatasetsPage.tsx
git commit -m "feat(datasets): toolbar with sort cycle + search"
```

---

### Task 30: Polish the annotation progress footer

**Files:**
- Modify: `frontend/src/pages/DatasetsPage.tsx`

- [ ] **Step 1: Replace the existing footer JSX**

```tsx
{annotating && progress && progress.total > 0 && (
  <div className="mt-xl rounded-lg border border-hairline bg-canvas p-md">
    <div className="text-caption-bold text-ink mb-2">Annotation progress</div>
    <div className="flex items-baseline justify-between mb-xs">
      <span className="text-body-sm-medium text-ink">{annotating}</span>
      <span className="text-body-sm text-steel font-mono tabular-nums">
        {progress.done} / {progress.total} episodes
      </span>
    </div>
    <div className="w-full bg-surface rounded-full h-2 overflow-hidden">
      <div
        className="bg-brand-warn h-2 transition-all"
        style={{ width: `${(progress.done / progress.total) * 100}%` }}
      />
    </div>
    {progress.status === "done" && (
      <p className="mt-xs text-body-sm text-brand-green-deep">Complete.</p>
    )}
  </div>
)}
```

- [ ] **Step 2: Type-check + smoke**

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/DatasetsPage.tsx
git commit -m "feat(datasets): polish annotation progress footer"
```

---

### Task 31: Phase 4 gate

- [ ] **Step 1: Full build**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 2: Browser smoke**

Verify Datasets page top bar + Catalogue heading + toolbar + cards + footer all look consistent.

- [ ] **Step 3: Tag**

```bash
git tag ui-modlab-phase-4
```

**Phase 4 complete.**

---

## Phase 5 — `EpisodesPage` rewrite

### Task 32: PageHeader + table polish

**Files:**
- Modify: `frontend/src/pages/EpisodesPage.tsx`

- [ ] **Step 1: Replace the file body**

```tsx
import { useParams, Link, useNavigate } from "react-router-dom";
import { useEpisodes, useDeleteEpisode } from "../api/queries";
import { Button } from "../components/ui/button";
import { CodeInline } from "../components/ui/code-inline";
import { PageHeader } from "../components/ui/page-header";

export default function EpisodesPage() {
  const { ds } = useParams<{ ds: string }>();
  const { data: episodes, isLoading } = useEpisodes(ds || "");
  const deleteMutation = useDeleteEpisode(ds || "");
  const navigate = useNavigate();

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
        actions={
          <Link to="/datasets" className="text-caption text-steel hover:text-ink">
            ← Datasets
          </Link>
        }
      />
      <div className="flex-1 overflow-auto">
        <div className="max-w-[1240px] mx-auto px-xl py-xl">
          {isLoading ? (
            <p className="text-steel">Loading...</p>
          ) : !episodes?.length ? (
            <p className="text-steel">No episodes recorded yet.</p>
          ) : (
            <table className="w-full text-body-sm">
              <thead>
                <tr className="border-b border-hairline text-left text-stone text-micro-uppercase uppercase tracking-[0.18em] font-semibold">
                  <th className="pb-sm">#</th>
                  <th className="pb-sm">Task</th>
                  <th className="pb-sm">Duration</th>
                  <th className="pb-sm">Frames</th>
                  <th className="pb-sm">Success</th>
                  <th className="pb-sm">Mode</th>
                  <th className="pb-sm">Recorded</th>
                  <th className="pb-sm"></th>
                </tr>
              </thead>
              <tbody>
                {episodes.map((ep) => (
                  <tr
                    key={ep.episode_index}
                    className="border-b border-hairline-soft hover:bg-surface-soft cursor-pointer transition-colors group"
                    onClick={() =>
                      navigate(`/datasets/${ds}/episodes/${ep.episode_index}/replay`)
                    }
                    title={`Open replay for episode #${ep.display_index}`}
                  >
                    <td className="py-md font-mono text-caption text-ink tabular-nums">
                      {ep.display_index}
                    </td>
                    <td className="py-md text-slate">{ep.task}</td>
                    <td className="py-md font-mono text-caption text-slate tabular-nums">
                      {ep.duration_sec.toFixed(1)}s
                    </td>
                    <td className="py-md font-mono text-caption text-slate tabular-nums">
                      {ep.num_frames}
                    </td>
                    <td className="py-md">
                      {ep.success === true && (
                        <span className="text-brand-green-deep">Success</span>
                      )}
                      {ep.success === false && (
                        <span className="text-brand-error">Failure</span>
                      )}
                      {ep.success === null && <span className="text-stone">—</span>}
                    </td>
                    <td className="py-md text-slate">{ep.mode}</td>
                    <td className="py-md text-steel text-caption font-mono">
                      {ep.recorded_at || "—"}
                    </td>
                    <td
                      className="py-md text-right"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Button
                        variant="destructive"
                        size="xs"
                        onClick={() => {
                          if (confirm(`Delete episode #${ep.display_index}?`)) {
                            deleteMutation.mutate(ep.episode_index);
                          }
                        }}
                      >
                        Delete
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 2: Type-check + smoke**

Run: `pnpm --dir frontend exec tsc --noEmit`. Visit `/datasets/<name>/episodes`. Verify table renders with mono numerals and the new page header.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/EpisodesPage.tsx
git commit -m "feat(episodes): PageHeader + polished table"
```

---

### Task 33: Phase 5 gate

- [ ] **Step 1: `pnpm --dir frontend build`**
- [ ] **Step 2: Tag**

```bash
git tag ui-modlab-phase-5
```

---

## Phase 6 — `SettingsPage` rewrite

### Task 34: PageHeader + §-numbered sections

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Inspect the real section structure**

```bash
grep -n "section\|<h3\|CONFIG_GROUPS" frontend/src/pages/SettingsPage.tsx | head -30
```

The current `SettingsPage` has two top-level sections:

- **Devices** — a 2-column card listing serial ports + cameras (`SettingsPage.tsx:114-165` at time of writing).
- **Configurations** — a list of `ConfigCard`s grouped by `CONFIG_GROUPS` (currently `["robot", "teleop", "mapper", "cameras"]` per the page's local constant). Each group is rendered as a small `<h4>` with the group name + cards.

There is **no** dedicated Inference or Hub settings section today. The spec's "§04.A Robot / §04.B Cameras / §04.C Inference / §04.D Hub" was aspirational. The plan rewrites against what actually exists.

- [ ] **Step 2: Wrap the page in PageHeader + match the real structure**

Replace the outer `<div>` and `<header>` with the `PageHeader` + two `<section>`s. Inside the Configurations section, keep the `CONFIG_GROUPS` loop unchanged but wrap each group's `<h4>` in a `SectionMark` sub-label for visual consistency.

```tsx
import { PageHeader } from "../components/ui/page-header";
import { SectionMark } from "../components/ui/section-mark";
// ...
return (
  <>
    <PageHeader code="§04" title="Settings" />
    <div className="flex-1 overflow-auto">
      <div className="max-w-[1100px] mx-auto px-xl py-xl flex flex-col gap-xl">

        {/* §04.A · Devices */}
        <section className="flex flex-col gap-md">
          <header className="flex items-baseline gap-md">
            <SectionMark code="§04.A" name="Devices" />
            <span className="flex-1 h-px bg-hairline-soft" />
            <Button variant="secondary" size="sm" onClick={loadDevices} disabled={refreshingDevices}>
              {refreshingDevices ? "Refreshing..." : "Refresh"}
            </Button>
          </header>
          {/* PRESERVE: the existing 2-column Card showing serial ports + cameras
              (today: SettingsPage.tsx:122-164) — copy verbatim. */}
        </section>

        {/* §04.B · Configurations */}
        <section className="flex flex-col gap-md">
          <header className="flex items-baseline gap-md">
            <SectionMark code="§04.B" name="Configurations" />
            <span className="flex-1 h-px bg-hairline-soft" />
            <Button variant="secondary" size="sm" onClick={loadConfigs} disabled={refreshingConfigs}>
              {refreshingConfigs ? "Refreshing..." : "Refresh"}
            </Button>
          </header>
          {CONFIG_GROUPS.map((group, i) => (
            <div key={group} className="flex flex-col gap-xs">
              <SectionMark
                code={`§04.B.${i + 1}`}
                name={group}
                className="capitalize"
              />
              <div className="flex flex-col gap-2">
                {/* PRESERVE: the existing ConfigCard map inside this group
                    (today: SettingsPage.tsx:178-203). */}
              </div>
            </div>
          ))}
        </section>

        {/* §04.C · Calibration */}
        <section className="flex flex-col gap-md">
          <header className="flex items-baseline gap-md">
            <SectionMark code="§04.C" name="Calibration" />
            <span className="flex-1 h-px bg-hairline-soft" />
          </header>
          {/* PRESERVE: the existing Calibration block
              (today: SettingsPage.tsx:254-...end-of-page-ish). Copy verbatim. */}
        </section>

      </div>
    </div>

    {/* PRESERVE: any modals rendered at the page root after the main content
        — the "fixed inset-0" modal divs at lines 207 and 281 carry their own
        z-index. Move them OUT of any nested overflow container so they still
        cover the full viewport. */}
  </>
);
```

**Sub-section codes (`§04.B.1` etc.)** — the secondary `SectionMark` inside the Configurations loop gives each config group its own anchor in mono caps without inventing a new heading style. This matches the spec's §-numbering vocabulary.

**Hub / Inference sections** — explicitly out of scope here. If hub settings need a dedicated home later, that's a follow-up.

- [ ] **Step 3: Type-check + smoke**

Visit `/settings`. Verify:

- New `PageHeader` `§04 · Settings`.
- Three sections: Devices, Configurations (with sub-grouped config cards), Calibration.
- Existing forms still work (refresh buttons, config edit modals).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "feat(settings): §-numbered section structure (Devices / Configurations / Calibration)"
```

---

### Task 35: `ReplayPage` and `InferencePage` PageHeader swap

These two pages otherwise stay as-is (per spec deferral). Just give them the new top bar so the shell is consistent. **Concrete instructions, with what to delete:**

**Files:**
- Modify: `frontend/src/pages/ReplayPage.tsx`
- Modify: `frontend/src/pages/InferencePage.tsx`

- [ ] **Step 1: ReplayPage — replace outer wrapper**

Find the page's outermost `return (...)`. Currently the page starts with `<div>` containing a `<header className="flex items-center justify-between pb-sm mb-lg border-b border-hairline">` block (top of page, around lines 50-90 — confirm by reading the file). Replace that wrapper with:

```tsx
import { PageHeader } from "../components/ui/page-header";
// ...
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
    />
    <div className="flex-1 overflow-auto">
      <div className="max-w-[1100px] mx-auto px-xl py-xl">
        {/* PRESERVE: the rest of the original page body — every section that
            was previously rendered AFTER the deleted <header>. That includes
            the Video section, JointPlot/EndEffectorPlot, SubtaskTimeline, and
            SubtaskAnnotator. None of these change in this task. */}
      </div>
    </div>
  </>
);
```

The exact lines to delete: the old `<header>...</header>` block at the top of the JSX, plus the closing `</div>` that matched the deleted outer wrapper. Confirm by reading the file before editing.

- [ ] **Step 2: InferencePage — replace outer wrapper**

The current `InferencePage` returns `<div className="p-6 max-w-5xl mx-auto space-y-4">` with a `<header>` at the top (lines 56–72 at time of writing). Replace:

```tsx
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
    <div className="flex-1 overflow-auto">
      <div className="max-w-[1100px] mx-auto px-xl py-xl space-y-4">
        {/* PRESERVE: error block, session-blocker block, phase panels,
            etc. — everything after the deleted <header>. */}
      </div>
    </div>
  </>
);
```

Delete the existing `<header>` (containing the `<h1>Inference</h1>` and the destructive E-STOP button — note: the E-STOP delete is Task 17, not this task; if Task 17 already ran, the button is already gone).

- [ ] **Step 3: Type-check + smoke**

Run: `pnpm --dir frontend exec tsc --noEmit`. Both pages render with the new top bar. Bodies (plots, timelines, phase panels) otherwise untouched and still functional.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ReplayPage.tsx frontend/src/pages/InferencePage.tsx
git commit -m "feat(layout): Replay + Inference get PageHeader (body unchanged)"
```

---

### Task 36: Phase 6 gate — final full smoke

- [ ] **Step 1: Full build**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 2: Browser smoke at 1440×900**

Click through every page:

- **Datasets** — top bar, summary, toolbar, cards, footer all in new style.
- **Record** — start a session, verify single-viewport (no scroll). E-Stop visible in sidebar for rebotarm sessions.
- **Episodes** (click into a dataset) — table polished.
- **Replay** (click into an episode) — top bar new; body untouched.
- **Inference** — top bar new; body untouched. No per-page E-Stop.
- **Settings** — §-numbered sections.

- [ ] **Step 3: Resize to 1200×800 on Record**

Verify the degraded layout (scroll allowed; telemetry rail wraps).

- [ ] **Step 4: Final tag**

```bash
git tag ui-modlab-phase-6-final
```

**Phase 6 complete. Plan delivered.**

---

## Notes for the executing engineer

1. **Type-check after every step.** `pnpm --dir frontend exec tsc --noEmit` is ~3–5 s; run it constantly. The full `pnpm --dir frontend build` (which includes Vite bundle) only matters at phase gates.

2. **No tests are added.** Verification is type-check + manual visual smoke. If a step's behaviour is genuinely uncertain (e.g., the `useJointHistory` hook receiving wrong shapes), add a `console.log` while iterating; remove before commit. Do not introduce vitest.

3. **One commit per task.** Even within a phase, commit per task so the diff is reviewable. If a task contains multiple steps and they sit half-finished, do not commit until the task is complete.

4. **If a task's referenced file content has drifted from what this plan assumes** (because the codebase moved): read the current file with the Read tool first, then adapt the diff. Do not blindly paste the snippets.

5. **The brainstorm mocks** (`.superpowers/brainstorm/211843-1778620183/record-c-v3.html` and `datasets-c-v3.html`) are the visual ground truth. When in doubt about a color, spacing, or arrangement, open the mock in the local visual companion at `http://localhost:52970` and compare.

6. **E-Stop is safety-critical.** Phase 2 ships the new E-Stop without yet rewriting `RecordPage`'s body. Verify the global E-Stop fires correctly (the keyboard binding is the actual mechanism — sidebar button is the visual affordance) before merging Phase 2. If anything feels off, open a follow-up issue and pause.

7. **Replay and Inference are intentionally not rewritten.** Resist the urge to "just polish them while you're there." Their full redesigns belong in separate specs.

8. **The visual companion server may have shut down** by the time someone executes this plan (it auto-exits after 30 min of inactivity). To re-render the mocks for reference, restart with `bash /home/takakimaeda/.claude/plugins/cache/superpowers-marketplace/superpowers/5.0.5/skills/brainstorming/scripts/start-server.sh --project-dir /home/takakimaeda/MimicRec`. The HTML files in `.superpowers/brainstorm/211843-1778620183/` are checked in nowhere — see `.gitignore`.

---

## Plan Revisions

This plan was reviewed by two reviewers (Codex gpt-5.5 second-opinion + an internal plan-document reviewer) before being committed. Findings applied:

- **Task 1** — token insertion uses a Read-then-Edit anchor (the prior "after the existing color block" phrasing was imprecise).
- **Task 11** — `useJointHistory` rewritten to subscribe to `/ws/state` (the channel that actually emits `joint_pos`, mirroring `EEMonitor`). The prior draft consumed `episodeProgress.joint_pos` which doesn't exist in `EpisodeProgress` (`frontend/src/api/types.ts:43-49`).
- **Task 14** — `SidebarStatus` now includes GoPro pending (spec line 168 explicitly moves both `SessionBadge` and `GoProPendingBadge` to the sidebar; the prior draft forgot the GoPro half) and uses `fetchAuthStatus` directly (no fictional `useAuthStatus` hook).
- **Task 15** — `main` keeps `overflow-auto` (the prior `overflow-hidden` would have clipped every yet-unrewritten page body in the Phase 2 transitional state).
- **Task 17** — Inference E-Stop is an inline `<Button>` calling `useInferenceStore().emergencyStop()`, not a `<EStopButton />` import. Task rewritten to inspect that function first, then either delete-and-rely-on-global (Case A) or defer if it carries inference-specific cleanup (Case B). The warning banner is addressed too.
- **Task 19** — drop the "Zustand devtools" verification hint (not configured in this codebase); replaced with a hard-coded values + revert approach.
- **Task 20** — derive elapsed time from `num_frames / fps` (the real fields). Introduce `useFitsRecordViewport` JS hook because Tailwind's `max-[Xpx]:` only targets width and the no-scroll requirement is `width ≥ 1280 AND height ≥ 900`.
- **Task 22** — drop the invented `progress.ee_pose`. `EEBlock` now subscribes to `/ws/state` directly and reads `ee_pos` + `ee_rotvec` (Rodrigues vector — labels are `rx/ry/rz`, not `roll/pitch/yaw`). `JointBlock` consumes `useJointHistory` with an `enabled` flag. The placeholder `EEMonitor` render is deleted as part of this task.
- **Task 23** — Episode progress grid uses the actually-emitted fields: `num_frames`, `ticks_skipped`, `writer_lag_ms`, `writer_queue_depth`, `stale_sample_count`. Writer lag and queue depth turn amber over thresholds. The invented `frames` / `drops` / `pre_roll_sec` / `auto_save` / `last_save` are gone.
- **Task 25** — controls bar consumes the new `inProgressIndex` (= `(episodes?.length ?? 0) + 1`) instead of the fictional `progress.episode_index`.
- **Task 28** — `DatasetCard` accepts a new required `index` prop (the prior draft used `index` without declaring or passing it — a hard TS error). The four conditional blocks at the bottom of the existing card (edit form, last-push error, generic error, last-pushed timestamp) are explicitly preserved verbatim — no more "keep existing JSX" hand-waves.
- **Task 34** — Settings sections rewritten against the real page structure (Devices + Configurations + Calibration). The spec's aspirational "Robot / Cameras / Inference / Hub" sections were not in the codebase; the plan tracks reality.
- **Task 35** — Replay/Inference `PageHeader` swap specifies exact `<header>` blocks to delete (with file line ranges to confirm before editing). Includes how `InferencePage`'s isLive badge and robot/mode meta migrate into `PageHeader` slots.

**Pass-2 Codex review** then surfaced one new blocker and one known-acceptable debt:

- **(blocker)** `useFitsRecordViewport()` was placed AFTER the idle-branch early return — a Rules of Hooks violation. Fix: the hook now lives **before** the conditional return in Task 20, so it runs unconditionally and in the same order every render. The value is unused in the idle branch but the hook call is what matters.
- **(known debt)** `EEBlock` (Task 22) and `useJointHistory` (Task 11) each open their own `/ws/state` subscription, so the active recording page holds two connections to the same backend hub. The backend (`state_hub.py`) has no subscriber cap and accepts each independently — this is functionally correct, just slightly wasteful. A follow-up could consolidate into a single shared store; not required for this plan.

This plan represents the state after applying all blocker-level and high-severity reviewer findings across two review rounds. Two medium-severity findings (Task 15 size, Task 20 size) were left as-is because they remain self-contained and reviewable as single commits; if a reviewer at execution time prefers a split, do so locally.
