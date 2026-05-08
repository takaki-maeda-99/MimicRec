# UI Refresh — Mintlify Token Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the Mintlify-inspired design system (`.claude/DESIGN.md`) to the MimicRec frontend by setting up Tailwind v4 `@theme` tokens, refactoring the `ui/*` primitive layer, rewriting the Layout shell, and replacing ad-hoc class strings across all pages and domain components.

**Architecture:** Three layers — token foundation in `frontend/src/index.css`, primitive layer in `frontend/src/components/ui/*` (5 refactored + 5 new), and consumer layer (Layout + 6 pages + 13 domain components). No prop / interface changes. Single-sweep delivery, all in light mode.

**Tech Stack:** React 19, Vite, Tailwind CSS v4, Zustand, React Query, `tailwind-merge` via `cn()`, Inter + Geist Mono via Google Fonts CDN.

**Spec:** `docs/superpowers/specs/2026-05-09-ui-mintlify-refresh-design.md`

**Verification model:** The frontend has no unit-test scaffolding today. Each task verifies via `pnpm --dir frontend build` (typecheck + bundle) and (where applicable) a brief browser smoke pass. We do **not** introduce a test framework as part of this plan — that is out of scope.

**Working directory:** All commands assume `/home/tirobot/MimicRec` as cwd unless stated otherwise.

---

## File Structure

**Created:**
- `frontend/src/components/ui/pill-tab.tsx`
- `frontend/src/components/ui/segmented-tab.tsx`
- `frontend/src/components/ui/code-inline.tsx`
- `frontend/src/components/ui/property-row.tsx`
- `frontend/src/components/ui/sidebar-nav-item.tsx`
- `frontend/src/components/CreateDatasetModal.tsx`

**Modified (visual layer rewrites; no API changes):**
- `frontend/src/index.css`
- `frontend/src/components/ui/button.tsx`
- `frontend/src/components/ui/badge.tsx`
- `frontend/src/components/ui/input.tsx`
- `frontend/src/components/ui/select.tsx`
- `frontend/src/components/ui/card.tsx`
- `frontend/src/components/Layout.tsx`
- `frontend/src/pages/{Datasets,Record,Episodes,Replay,Settings,Inference}Page.tsx`
- `frontend/src/components/{CameraConfigForm,CameraPreview,EEMonitor,EndEffectorPlot,EStopButton,ExportDatasetModal,JointPlot,KeyboardTeleop,RecordingControls,SessionConfigForm,SubtaskAnnotator,SubtaskTimeline,VideoPlayer}.tsx`

---

## Task 1: Token foundation — Tailwind v4 `@theme` block

**Files:**
- Modify: `frontend/src/index.css` (currently just `@import "tailwindcss";`)

- [ ] **Step 1: Replace the file with font imports, `@theme` tokens, and base body styling**

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap');
@import "tailwindcss";

@theme {
  /* Fonts */
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'Geist Mono', 'SF Mono', Menlo, Consolas, monospace;

  /* Colors (24) */
  --color-primary: #0a0a0a;
  --color-on-primary: #ffffff;
  --color-brand-green: #00d4a4;
  --color-brand-green-deep: #00b48a;
  --color-brand-green-soft: #7cebcb;
  --color-brand-tag: #3772cf;
  --color-brand-warn: #c37d0d;
  --color-brand-error: #d45656;
  --color-canvas: #ffffff;
  --color-canvas-dark: #0a0a0a;
  --color-surface: #f7f7f7;
  --color-surface-soft: #fafafa;
  --color-surface-code: #1c1c1e;
  --color-hairline: #e5e5e5;
  --color-hairline-soft: #ededed;
  --color-hairline-dark: #1f1f1f;
  --color-ink: #0a0a0a;
  --color-charcoal: #1c1c1e;
  --color-slate: #3a3a3c;
  --color-steel: #5a5a5c;
  --color-stone: #888888;
  --color-muted: #a8a8aa;
  --color-on-dark: #ffffff;
  --color-on-dark-muted: #b3b3b3;

  /* Typography (19) — paired with line-height, font-weight, and letter-spacing per the spec */
  --text-display-lg: 56px;
  --text-display-lg--line-height: 1.10;
  --text-display-lg--font-weight: 600;
  --text-display-lg--letter-spacing: -1.5px;
  --text-heading-1: 48px;
  --text-heading-1--line-height: 1.10;
  --text-heading-1--font-weight: 600;
  --text-heading-1--letter-spacing: -1px;
  --text-heading-2: 36px;
  --text-heading-2--line-height: 1.20;
  --text-heading-2--font-weight: 600;
  --text-heading-2--letter-spacing: -0.5px;
  --text-heading-3: 28px;
  --text-heading-3--line-height: 1.25;
  --text-heading-3--font-weight: 600;
  --text-heading-4: 22px;
  --text-heading-4--line-height: 1.30;
  --text-heading-4--font-weight: 600;
  --text-heading-5: 18px;
  --text-heading-5--line-height: 1.40;
  --text-heading-5--font-weight: 600;
  --text-subtitle: 18px;
  --text-subtitle--line-height: 1.50;
  --text-subtitle--font-weight: 400;
  --text-body-md: 16px;
  --text-body-md--line-height: 1.50;
  --text-body-md--font-weight: 400;
  --text-body-md-medium: 16px;
  --text-body-md-medium--line-height: 1.50;
  --text-body-md-medium--font-weight: 500;
  --text-body-sm: 14px;
  --text-body-sm--line-height: 1.50;
  --text-body-sm--font-weight: 400;
  --text-body-sm-medium: 14px;
  --text-body-sm-medium--line-height: 1.50;
  --text-body-sm-medium--font-weight: 500;
  --text-caption: 13px;
  --text-caption--line-height: 1.40;
  --text-caption--font-weight: 400;
  --text-caption-bold: 13px;
  --text-caption-bold--line-height: 1.40;
  --text-caption-bold--font-weight: 600;
  --text-micro: 12px;
  --text-micro--line-height: 1.40;
  --text-micro--font-weight: 500;
  --text-micro-uppercase: 11px;
  --text-micro-uppercase--line-height: 1.40;
  --text-micro-uppercase--font-weight: 600;
  --text-micro-uppercase--letter-spacing: 0.5px;
  --text-button-md: 14px;
  --text-button-md--line-height: 1.30;
  --text-button-md--font-weight: 500;
  --text-code-md: 14px;
  --text-code-md--line-height: 1.50;
  --text-code-md--font-weight: 400;
  --text-code-sm: 13px;
  --text-code-sm--line-height: 1.40;
  --text-code-sm--font-weight: 400;
  --text-code-inline: 13px;
  --text-code-inline--line-height: 1.30;
  --text-code-inline--font-weight: 500;

  /* Radius (7) */
  --radius-xs: 4px;
  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --radius-xxl: 24px;
  --radius-full: 9999px;

  /* Spacing (12) — coexists with default --spacing scalar */
  --spacing-xxs: 4px;
  --spacing-xs: 8px;
  --spacing-sm: 12px;
  --spacing-md: 16px;
  --spacing-lg: 20px;
  --spacing-xl: 24px;
  --spacing-xxl: 32px;
  --spacing-xxxl: 40px;
  --spacing-section-sm: 48px;
  --spacing-section: 64px;
  --spacing-section-lg: 96px;
}

html, body, #root {
  height: 100%;
}

body {
  font-family: var(--font-sans);
  font-size: var(--text-body-md);
  line-height: var(--text-body-md--line-height);
  color: var(--color-ink);
  background-color: var(--color-surface-soft);
  -webkit-font-smoothing: antialiased;
}
```

- [ ] **Step 2: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: `vite v8.x building for production... ✓ built in <Ns>` with no errors. Tokens that aren't yet referenced won't fail the build — Tailwind v4 only emits utilities that are actually used, but the `@theme` block must parse cleanly.

- [ ] **Step 3: Browser smoke**

Run: `pnpm --dir frontend dev` (background), open `http://localhost:5173`.
Expected: app still loads (existing pages will look slightly different because body font is now Inter instead of system default; that's the only visible change). Check DevTools → Network for `fonts.googleapis.com` request returning 200 with Inter + Geist Mono CSS.
Stop the dev server before continuing (Ctrl+C in its terminal).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/index.css
git commit -m "feat(frontend): add Mintlify @theme tokens and Inter/Geist Mono fonts"
```

---

## Task 2: Refactor `Button` primitive

**Files:**
- Modify: `frontend/src/components/ui/button.tsx`

- [ ] **Step 1: Replace the file with token-based variants**

```tsx
import { cn } from "../../lib/utils";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "link" | "iconCircular";
  size?: "default" | "sm" | "lg";
  // Legacy aliases preserved so existing callers don't break.
  // "default" maps to "primary"; "destructive" maps to "primary" with text-brand-error color
  // applied at the call site via className; "outline" maps to "secondary".
}

export function Button({
  className,
  variant = "primary",
  size = "default",
  ...props
}: ButtonProps & { variant?: ButtonProps["variant"] | "default" | "destructive" | "outline" }) {
  // Normalize legacy variants
  const normalized =
    variant === "default" ? "primary" :
    variant === "outline" ? "secondary" :
    variant === "destructive" ? "primary" :
    variant;

  const base = "inline-flex items-center justify-center font-medium transition-colors disabled:cursor-not-allowed";
  const pillPad =
    size === "sm" ? "px-md py-1.5 text-button-md" :
    size === "lg" ? "px-xl py-3 text-body-md-medium" :
    "px-lg py-2.5 text-button-md";

  const variants: Record<string, string> = {
    primary:
      "rounded-full bg-primary text-on-primary " +
      pillPad +
      " hover:bg-charcoal disabled:bg-hairline disabled:text-muted",
    secondary:
      "rounded-full border border-hairline bg-transparent text-ink " +
      pillPad +
      " hover:bg-surface disabled:text-muted",
    ghost:
      "rounded-md bg-transparent text-ink text-button-md px-3 py-2 hover:bg-surface disabled:text-muted",
    link:
      "bg-transparent text-ink text-body-sm-medium underline-offset-2 hover:underline p-0",
    iconCircular:
      "rounded-full bg-canvas text-ink border border-hairline w-8 h-8 hover:bg-surface",
  };

  // Destructive legacy: tint the text red on top of primary visuals
  const destructiveTint = variant === "destructive" ? "!text-brand-error" : "";

  return (
    <button
      className={cn(base, variants[normalized], destructiveTint, className)}
      {...props}
    />
  );
}
```

- [ ] **Step 2: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success. TypeScript will accept all current callers because `variant` still accepts the old string literals.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/button.tsx
git commit -m "feat(frontend/ui): refactor Button to Mintlify pill variants with legacy aliases"
```

---

## Task 3: Refactor `Badge` primitive (preserve semantic aliases)

**Files:**
- Modify: `frontend/src/components/ui/badge.tsx`

- [ ] **Step 1: Replace the file**

```tsx
import { cn } from "../../lib/utils";

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  // Public semantic API (kept stable). Each maps onto a Mintlify visual.
  variant?: "default" | "success" | "warning" | "destructive" | "outline" | "tag" | "type" | "required";
}

export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  const base = "inline-flex items-center text-caption-bold";
  const variants: Record<NonNullable<BadgeProps["variant"]>, string> = {
    // Default = neutral hairline outline pill
    default: "rounded-full border border-hairline text-steel bg-transparent px-2 py-0.5",
    // Mint pill (active session, ready, complete)
    success: "rounded-full bg-brand-green text-primary px-2 py-0.5",
    // Amber pill — uses brand-warn at low-alpha background
    warning: "rounded-full bg-brand-warn/15 text-brand-warn px-2 py-0.5",
    // Red pill (recording / errors)
    destructive: "rounded-full bg-brand-error text-on-dark px-2 py-0.5",
    // Plain hairline outline (semantic alias for default-with-border-emphasis)
    outline: "rounded-full border border-hairline text-steel bg-transparent px-2 py-0.5",
    // Brand-tag blue tinted (info/review)
    tag: "rounded-sm bg-brand-tag/15 text-brand-tag px-2 py-0.5",
    // API-doc style type chip
    type: "rounded-sm bg-surface text-steel font-mono text-code-sm px-1.5 py-0.5",
    // Red required label (uppercase)
    required: "rounded-sm bg-brand-error text-on-dark text-micro-uppercase px-1.5 py-0.5 uppercase tracking-[0.5px]",
  };
  return <span className={cn(base, variants[variant], className)} {...props} />;
}
```

- [ ] **Step 2: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success. All existing call sites use `default` / `success` / `warning` / `destructive` / `outline` which still exist.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/badge.tsx
git commit -m "feat(frontend/ui): refactor Badge to Mintlify visuals; add tag/type/required variants"
```

---

## Task 4: Refactor `Input` primitive

**Files:**
- Modify: `frontend/src/components/ui/input.tsx`

- [ ] **Step 1: Replace the file**

```tsx
import { cn } from "../../lib/utils";

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

export function Input({ className, ...props }: InputProps) {
  return (
    <input
      className={cn(
        "flex h-10 w-full rounded-md border border-hairline bg-canvas px-md text-body-md text-ink placeholder:text-stone",
        "focus-visible:outline-none focus-visible:border-2 focus-visible:border-ink",
        "disabled:cursor-not-allowed disabled:bg-surface disabled:text-muted",
        className,
      )}
      {...props}
    />
  );
}
```

- [ ] **Step 2: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/input.tsx
git commit -m "feat(frontend/ui): refactor Input to Mintlify tokens with ink focus border"
```

---

## Task 5: Refactor `Select` primitive

**Files:**
- Modify: `frontend/src/components/ui/select.tsx`

- [ ] **Step 1: Replace the file**

```tsx
import { cn } from "../../lib/utils";

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {}

export function Select({ className, children, ...props }: SelectProps) {
  return (
    <select
      className={cn(
        "flex h-10 w-full rounded-md border border-hairline bg-canvas px-md text-body-md text-ink",
        "focus-visible:outline-none focus-visible:border-2 focus-visible:border-ink",
        "disabled:cursor-not-allowed disabled:bg-surface disabled:text-muted",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
}
```

- [ ] **Step 2: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/select.tsx
git commit -m "feat(frontend/ui): refactor Select to Mintlify tokens"
```

---

## Task 6: Refactor `Card` primitive (variant prop)

**Files:**
- Modify: `frontend/src/components/ui/card.tsx`

- [ ] **Step 1: Replace the file**

Current `Card` exports `Card / CardHeader / CardTitle / CardContent`. Keep the sub-components but switch to tokens, and add a `variant` prop on `Card`.

```tsx
import { cn } from "../../lib/utils";

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "base" | "feature";
}

export function Card({ className, variant = "base", ...props }: CardProps) {
  const variants = {
    base: "rounded-lg border border-hairline bg-canvas p-xl",
    feature: "rounded-lg bg-surface p-xxl",
  } as const;
  return <div className={cn(variants[variant], className)} {...props} />;
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-1.5 mb-md", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-heading-5 text-ink", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("text-body-sm text-charcoal", className)} {...props} />;
}
```

- [ ] **Step 2: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/card.tsx
git commit -m "feat(frontend/ui): refactor Card to base/feature variants on Mintlify tokens"
```

---

## Task 7: New `PillTab` primitive

**Files:**
- Create: `frontend/src/components/ui/pill-tab.tsx`

- [ ] **Step 1: Create the file**

```tsx
import { cn } from "../../lib/utils";

interface PillTabProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  active?: boolean;
  // tone="state" colours the active pill mint (used for session-state indicators);
  // tone="nav" colours the active pill black (used for tab navigation).
  tone?: "state" | "nav";
}

export function PillTab({ className, active = false, tone = "nav", children, ...props }: PillTabProps) {
  const base = "inline-flex items-center rounded-full text-body-sm-medium px-md py-1.5 transition-colors";
  const inactive = "bg-canvas border border-hairline text-steel hover:bg-surface";
  const activeNav = "bg-primary text-on-primary border border-primary";
  const activeState = "bg-brand-green text-primary border border-brand-green";

  return (
    <button
      type="button"
      className={cn(base, !active && inactive, active && tone === "nav" && activeNav, active && tone === "state" && activeState, className)}
      {...props}
    >
      {children}
    </button>
  );
}
```

- [ ] **Step 2: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/pill-tab.tsx
git commit -m "feat(frontend/ui): add PillTab primitive with nav/state tones"
```

---

## Task 8: New `SegmentedTab` primitive

**Files:**
- Create: `frontend/src/components/ui/segmented-tab.tsx`

- [ ] **Step 1: Create the file**

```tsx
import { cn } from "../../lib/utils";

interface SegmentedTabProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  active?: boolean;
}

export function SegmentedTab({ className, active = false, children, ...props }: SegmentedTabProps) {
  const base = "inline-flex items-center text-body-sm-medium px-md py-sm border-b-2 transition-colors";
  return (
    <button
      type="button"
      className={cn(base, active ? "text-ink border-ink" : "text-steel border-transparent hover:text-ink", className)}
      {...props}
    >
      {children}
    </button>
  );
}

export function SegmentedTabBar({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex gap-md border-b border-hairline-soft", className)} {...props} />;
}
```

- [ ] **Step 2: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/segmented-tab.tsx
git commit -m "feat(frontend/ui): add SegmentedTab + SegmentedTabBar primitives"
```

---

## Task 9: New `CodeInline` primitive

**Files:**
- Create: `frontend/src/components/ui/code-inline.tsx`

- [ ] **Step 1: Create the file**

```tsx
import { cn } from "../../lib/utils";

interface CodeInlineProps extends React.HTMLAttributes<HTMLElement> {}

export function CodeInline({ className, children, ...props }: CodeInlineProps) {
  return (
    <code
      className={cn(
        "inline-flex items-center rounded-xs border border-hairline bg-surface px-1.5 py-0.5",
        "font-mono text-code-inline text-charcoal",
        className,
      )}
      {...props}
    >
      {children}
    </code>
  );
}
```

- [ ] **Step 2: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/code-inline.tsx
git commit -m "feat(frontend/ui): add CodeInline primitive"
```

---

## Task 10: New `PropertyRow` primitive

**Files:**
- Create: `frontend/src/components/ui/property-row.tsx`

- [ ] **Step 1: Create the file**

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
}

export function PropertyRow({
  className,
  name,
  type,
  required = false,
  description,
  control,
  ...props
}: PropertyRowProps) {
  return (
    <div
      className={cn("py-md border-b border-hairline-soft last:border-b-0", className)}
      {...props}
    >
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

- [ ] **Step 2: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/property-row.tsx
git commit -m "feat(frontend/ui): add PropertyRow primitive for Settings"
```

---

## Task 11: New `SidebarNavItem` primitive

**Files:**
- Create: `frontend/src/components/ui/sidebar-nav-item.tsx`

- [ ] **Step 1: Create the file**

```tsx
import { NavLink } from "react-router-dom";
import { cn } from "../../lib/utils";

interface SidebarNavItemProps {
  to: string;
  children: React.ReactNode;
  className?: string;
}

export function SidebarNavItem({ to, children, className }: SidebarNavItemProps) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "block rounded-sm px-md py-xs transition-colors",
          isActive
            ? "bg-surface text-ink text-body-sm-medium"
            : "text-steel text-body-sm hover:bg-surface-soft hover:text-ink",
          className,
        )
      }
    >
      {children}
    </NavLink>
  );
}
```

- [ ] **Step 2: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ui/sidebar-nav-item.tsx
git commit -m "feat(frontend/ui): add SidebarNavItem primitive"
```

---

## Task 12: Rewrite `Layout.tsx` shell

**Files:**
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Replace the file**

```tsx
import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { useSessionStore } from "../state/session-store";
import { useSessionState } from "../api/queries";
import { Badge } from "./ui/badge";
import { SidebarNavItem } from "./ui/sidebar-nav-item";

const navItems = [
  { to: "/datasets", label: "Datasets" },
  { to: "/record", label: "Record" },
  { to: "/inference", label: "Inference" },
  { to: "/settings", label: "Settings" },
];

function SessionBadge() {
  const state = useSessionStore((s) => s.state);
  const robot = useSessionStore((s) => s.robot);
  const variantMap: Record<string, "outline" | "success" | "destructive" | "tag"> = {
    idle: "outline",
    ready: "success",
    recording: "destructive",
    review: "tag",
  };
  return (
    <div className="flex flex-col items-end gap-0.5">
      <Badge variant={variantMap[state] || "outline"} className="text-micro-uppercase uppercase tracking-[0.5px]">
        {state}
      </Badge>
      {state !== "idle" && robot && (
        <span className="text-caption text-stone">{robot}</span>
      )}
    </div>
  );
}

function ConnectionStatus() {
  // Static pill for now — wire to real WS/API health in a follow-up.
  return (
    <div className="flex items-center gap-xs px-md py-xs text-caption text-steel">
      <span className="w-2 h-2 rounded-full bg-brand-green" aria-hidden />
      <span>Connected</span>
    </div>
  );
}

export default function Layout() {
  const { data: apiState } = useSessionState();
  const setSessionState = useSessionStore((s) => s.setSessionState);

  useEffect(() => {
    if (apiState) {
      setSessionState(apiState as unknown as Record<string, unknown>);
    }
  }, [apiState, setSessionState]);

  return (
    <div className="flex h-screen bg-surface-soft">
      <aside className="w-60 bg-canvas border-r border-hairline-soft flex flex-col">
        <div className="px-md py-md border-b border-hairline-soft flex items-center justify-between">
          <h1 className="text-heading-5 text-ink">MimicRec</h1>
          <SessionBadge />
        </div>
        <nav className="flex-1 p-xs flex flex-col gap-0.5">
          {navItems.map((item) => (
            <SidebarNavItem key={item.to} to={item.to}>
              {item.label}
            </SidebarNavItem>
          ))}
        </nav>
        <div className="border-t border-hairline-soft">
          <ConnectionStatus />
        </div>
      </aside>
      <main className="flex-1 overflow-auto">
        <div className="max-w-[1280px] mx-auto px-xl py-xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
```

- [ ] **Step 2: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 3: Browser smoke**

Run: `pnpm --dir frontend dev`. Visit `/datasets`, `/record`, `/settings`, `/inference`. Confirm:
- Sidebar is 240px, white background, hairline border on the right.
- Active nav item has surface-tinted background.
- "Connected" pill with mint dot is visible at the bottom of the sidebar.
- Each existing page now renders inside a centered max-1280px column with surface-soft background.
- App still functions (you can navigate, no console errors related to imports).

Stop the dev server.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Layout.tsx
git commit -m "feat(frontend): rewrite Layout shell to Mintlify spec (240px sidebar, connection status, centered main)"
```

---

## Task 13: Refactor `DatasetsPage` (page header + create modal + table tokens)

**Files:**
- Create: `frontend/src/components/CreateDatasetModal.tsx`
- Modify: `frontend/src/pages/DatasetsPage.tsx`

- [ ] **Step 1: Create `CreateDatasetModal.tsx`**

Lift the inline create form into a modal that mirrors the styling of `ExportDatasetModal.tsx`.

```tsx
import { useState } from "react";
import { useCreateDataset } from "../api/queries";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

interface Props {
  onClose: () => void;
}

export function CreateDatasetModal({ onClose }: Props) {
  const createMutation = useCreateDataset();
  const [name, setName] = useState("");
  const [fps, setFps] = useState(30);

  const handleCreate = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    createMutation.mutate(
      { name: trimmed, fps, joint_names: [], camera_names: [] },
      {
        onSuccess: () => {
          setName("");
          onClose();
        },
      },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-canvas-dark/40" onClick={onClose}>
      <div
        className="w-[420px] max-w-full bg-canvas rounded-lg border border-hairline p-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-heading-5 text-ink mb-md">New Dataset</h3>
        <div className="flex flex-col gap-md">
          <label className="text-body-sm-medium text-charcoal">
            Name
            <Input
              className="mt-1"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="my_dataset"
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              autoFocus
            />
          </label>
          <label className="text-body-sm-medium text-charcoal">
            FPS
            <Input
              className="mt-1 w-24"
              type="number"
              value={fps}
              onChange={(e) => setFps(Number(e.target.value))}
            />
          </label>
        </div>
        <div className="mt-xl flex justify-end gap-xs">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button onClick={handleCreate} disabled={createMutation.isPending || !name.trim()}>
            Create
          </Button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Replace `DatasetsPage.tsx`**

```tsx
import { useState } from "react";
import { Link } from "react-router-dom";
import { useDatasets, useDeleteDataset } from "../api/queries";
import { apiFetch } from "../api/client";
import { Button } from "../components/ui/button";
import { ExportDatasetModal } from "../components/ExportDatasetModal";
import { CreateDatasetModal } from "../components/CreateDatasetModal";

export default function DatasetsPage() {
  const { data: datasets, isLoading } = useDatasets();
  const deleteMutation = useDeleteDataset();
  const [annotating, setAnnotating] = useState<string | null>(null);
  const [progress, setProgress] = useState<{
    done: number; total: number; current_episode: number | null; status: string;
  } | null>(null);
  const [exportingDataset, setExportingDataset] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const handleAnnotateAll = async (dsName: string) => {
    if (!confirm(`Annotate all episodes in "${dsName}" with Gemma 4?\nThis may take a while.`)) return;
    setAnnotating(dsName);
    setProgress(null);
    try {
      await apiFetch(`/api/datasets/${dsName}/annotate-all`, {
        method: "POST", body: JSON.stringify({}),
      });
      const poll = setInterval(async () => {
        try {
          const p = await apiFetch<{ done: number; total: number; current_episode: number | null; status: string }>(
            `/api/datasets/${dsName}/annotate-progress`,
          );
          setProgress(p);
          if (p.status === "done") {
            clearInterval(poll);
            setAnnotating(null);
          }
        } catch {
          clearInterval(poll);
          setAnnotating(null);
        }
      }, 2000);
    } catch (e) {
      alert(`Error: ${(e as Error).message}`);
      setAnnotating(null);
    }
  };

  return (
    <div>
      <header className="flex items-center justify-between pb-md mb-xl border-b border-hairline-soft">
        <h2 className="text-heading-3 text-ink">Datasets</h2>
        <Button onClick={() => setCreating(true)}>New Dataset</Button>
      </header>

      {isLoading ? (
        <p className="text-steel">Loading...</p>
      ) : !datasets?.length ? (
        <p className="text-steel">No datasets yet. Click "New Dataset" to create one.</p>
      ) : (
        <table className="w-full text-body-sm">
          <thead>
            <tr className="border-b border-hairline text-left text-steel text-micro-uppercase uppercase tracking-[0.5px]">
              <th className="pb-sm font-semibold">Name</th>
              <th className="pb-sm font-semibold">Episodes</th>
              <th className="pb-sm font-semibold">Frames</th>
              <th className="pb-sm font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((ds) => (
              <tr key={ds.name} className="border-b border-hairline-soft">
                <td className="py-md">
                  <Link
                    to={`/datasets/${ds.name}/episodes`}
                    className="text-ink text-body-sm-medium hover:underline"
                  >
                    {ds.name}
                  </Link>
                </td>
                <td className="py-md text-slate">{ds.num_episodes}</td>
                <td className="py-md text-slate">{ds.total_frames}</td>
                <td className="py-md flex gap-md">
                  <Button variant="link" onClick={() => setExportingDataset(ds.name)}>
                    Export
                  </Button>
                  <Button
                    variant="link"
                    onClick={() => handleAnnotateAll(ds.name)}
                    disabled={annotating !== null}
                    className={annotating === ds.name ? "!text-brand-tag" : ""}
                  >
                    {annotating === ds.name && progress
                      ? `${progress.done}/${progress.total} (ep ${progress.current_episode ?? "..."})`
                      : annotating === ds.name
                      ? "Starting..."
                      : "Annotate"}
                  </Button>
                  <Button
                    variant="link"
                    className="!text-brand-error"
                    onClick={() => {
                      if (confirm(`Delete dataset "${ds.name}" and all its episodes?`)) {
                        deleteMutation.mutate(ds.name);
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

      {annotating && progress && progress.total > 0 && (
        <div className="mt-xl rounded-lg border border-hairline bg-canvas p-md">
          <div className="flex items-center justify-between mb-xs">
            <span className="text-body-sm-medium text-ink">Annotating {annotating}</span>
            <span className="text-body-sm text-steel">
              {progress.done} / {progress.total} episodes
              {progress.current_episode !== null && ` (processing ep ${progress.current_episode})`}
            </span>
          </div>
          <div className="w-full bg-surface rounded-full h-2 overflow-hidden">
            <div
              className="bg-brand-tag h-2 transition-all"
              style={{ width: `${(progress.done / progress.total) * 100}%` }}
            />
          </div>
          {progress.status === "done" && (
            <p className="mt-xs text-body-sm text-brand-green-deep">Complete!</p>
          )}
        </div>
      )}

      {creating && <CreateDatasetModal onClose={() => setCreating(false)} />}
      {exportingDataset && (
        <ExportDatasetModal ds={exportingDataset} onClose={() => setExportingDataset(null)} />
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 4: Browser smoke**

Run: `pnpm --dir frontend dev`. Open `/datasets`. Confirm:
- Page header band with title + black "New Dataset" pill button.
- Click "New Dataset": modal opens, can create a dataset.
- Existing dataset rows: link is dark/black with underline on hover; Export / Annotate / Delete render as text links; Delete is red, Annotate goes brand-tag blue while running.
- Annotation progress bar fills with brand-tag blue.

Stop the dev server.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CreateDatasetModal.tsx frontend/src/pages/DatasetsPage.tsx
git commit -m "feat(frontend/datasets): apply Mintlify tokens; extract create form into modal"
```

---

## Task 14: Refactor `RecordPage`

**Files:**
- Modify: `frontend/src/pages/RecordPage.tsx`

- [ ] **Step 1: Replace the file**

```tsx
import { useEffect } from "react";
import { useSessionStore } from "../state/session-store.ts";
import { useEndSession, useEpisodes, useSessionState } from "../api/queries.ts";
import { WsConnection } from "../api/ws.ts";
import SessionConfigForm from "../components/SessionConfigForm.tsx";
import CameraPreview from "../components/CameraPreview.tsx";
import RecordingControls from "../components/RecordingControls.tsx";
import KeyboardTeleop from "../components/KeyboardTeleop.tsx";
import EEMonitor from "../components/EEMonitor.tsx";
import EStopButton from "../components/EStopButton.tsx";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { CodeInline } from "../components/ui/code-inline";
import { PillTab } from "../components/ui/pill-tab";
import type { EpisodeProgress, ReplayProgress } from "../api/types.ts";

export default function RecordPage() {
  const sessionState = useSessionStore((s) => s.state);
  const subState = useSessionStore((s) => s.subState);
  const cameras = useSessionStore((s) => s.cameras);
  const dataset = useSessionStore((s) => s.dataset);
  const robot = useSessionStore((s) => s.robot);
  const teleop = useSessionStore((s) => s.teleop);
  const mode = useSessionStore((s) => s.mode);
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
      if (msgType === "episode_progress")
        setEpisodeProgress(msgData as unknown as EpisodeProgress);
      if (msgType === "replay_progress")
        setReplayProgress(msgData as unknown as ReplayProgress);
      if (msgType === "error")
        setError(msgData as unknown as { error: string; message: string });
    });
    conn.connect();
    return () => conn.disconnect();
  }, [isIdle, setSessionState, setEpisodeProgress, setReplayProgress, setError]);

  if (sessionState === "idle") {
    return (
      <div>
        <header className="flex items-center justify-between pb-md mb-xl border-b border-hairline-soft">
          <h2 className="text-heading-3 text-ink">Record</h2>
        </header>
        <Card variant="feature">
          <SessionConfigForm onStarted={() => {}} />
        </Card>
      </div>
    );
  }

  return (
    <div>
      <header className="flex items-center justify-between pb-md mb-xl border-b border-hairline-soft">
        <h2 className="text-heading-3 text-ink">Record</h2>
        <div className="flex items-center gap-md">
          {subState === "replaying" && (
            <PillTab active tone="state" disabled>Replaying</PillTab>
          )}
          <Button variant="secondary" className="!text-brand-error" onClick={() => endSession.mutate()}>
            End Session
          </Button>
        </div>
      </header>

      <Card className="mb-xl flex gap-xl flex-wrap text-body-sm">
        <span className="flex items-center gap-xs">
          <span className="text-caption text-stone">Robot</span>
          <CodeInline>{robot}</CodeInline>
        </span>
        <span className="flex items-center gap-xs">
          <span className="text-caption text-stone">Mode</span>
          <CodeInline>{mode}</CodeInline>
        </span>
        <span className="flex items-center gap-xs">
          <span className="text-caption text-stone">Teleop</span>
          <CodeInline>{teleop || "—"}</CodeInline>
        </span>
        <span className="flex items-center gap-xs">
          <span className="text-caption text-stone">Dataset</span>
          <CodeInline>{dataset}</CodeInline>
        </span>
        <span className="flex items-center gap-xs">
          <span className="text-caption text-stone">Episodes</span>
          <CodeInline>{episodes?.length ?? "—"}</CodeInline>
        </span>
        {cameras.length > 0 && (
          <span className="flex items-center gap-xs">
            <span className="text-caption text-stone">Cameras</span>
            <CodeInline>{cameras.join(", ")}</CodeInline>
          </span>
        )}
      </Card>

      {cameras.length > 0 && sessionState !== "review" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-md mb-xl">
          {cameras.map((cam) => (
            <CameraPreview key={cam} camName={cam} />
          ))}
        </div>
      )}

      {teleop === "web_keyboard" && (
        <div className="mb-xl">
          <KeyboardTeleop enabled={sessionState !== "review"} />
        </div>
      )}

      <div className="mb-xl">
        <EEMonitor enabled />
      </div>

      {robot === "rebotarm" && (
        <div className="mb-xl">
          <EStopButton />
        </div>
      )}

      <RecordingControls />
    </div>
  );
}
```

- [ ] **Step 2: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 3: Browser smoke**

Run: `pnpm --dir frontend dev`. Open `/record`. Confirm idle state shows the config form inside a feature card. (Active session smoke test happens later; the page should at minimum compile and idle render correctly.)

Stop the dev server.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/RecordPage.tsx
git commit -m "feat(frontend/record): apply Mintlify tokens, CodeInline values, mint Replaying pill"
```

---

## Task 15: Refactor `EpisodesPage`

**Files:**
- Modify: `frontend/src/pages/EpisodesPage.tsx`

- [ ] **Step 1: Read the current file**

Run: `cat frontend/src/pages/EpisodesPage.tsx`
Note: the editor must read this file first before applying targeted Edits.

- [ ] **Step 2: Apply token replacements**

Replace every ad-hoc class string with the equivalent token, mirroring the Datasets table conventions:

| Pattern in current file | Replacement |
|---|---|
| `text-2xl font-bold` (page title) | `text-heading-3 text-ink` |
| `text-blue-600` link styling | `text-ink text-body-sm-medium hover:underline` |
| `text-red-600 hover:text-red-800` | wrap action in `<Button variant="link" className="!text-brand-error">` |
| `bg-gray-50 / hover:bg-gray-50` row hover | drop hover shading; rely on `border-b border-hairline-soft` |
| `border-gray-200` | `border-hairline` |
| `border-gray-100` | `border-hairline-soft` |
| `text-gray-{400,500,600,700}` | `text-stone / text-steel / text-slate / text-charcoal` per Color Resolution Table in spec |
| `bg-gray-100` info bars | `<Card variant="base">` |

Wrap the page top in a `<header>` band identical to Datasets. The current file pulls the dataset name from `useParams<{ ds: string }>()`, so use `ds` (not a hypothetical `datasetName`):

```tsx
<header className="flex items-center justify-between pb-md mb-xl border-b border-hairline-soft">
  <div>
    <Link to="/datasets" className="text-caption text-stone hover:text-ink">&larr; Datasets</Link>
    <h2 className="mt-1 text-heading-3 text-ink">Episodes — <CodeInline>{ds}</CodeInline></h2>
  </div>
</header>
```
(Import `CodeInline` from `../components/ui/code-inline`.)

- [ ] **Step 3: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/EpisodesPage.tsx
git commit -m "feat(frontend/episodes): apply Mintlify tokens to episodes table and header"
```

---

## Task 16: Refactor `ReplayPage`

**Files:**
- Modify: `frontend/src/pages/ReplayPage.tsx`

- [ ] **Step 1: Read the current file**

Run: `cat frontend/src/pages/ReplayPage.tsx`

- [ ] **Step 2: Apply structural + token changes**

Wrap the contents in a header band + a vertical stack where each block (`VideoPlayer`, `JointPlot`, `EndEffectorPlot`, `SubtaskTimeline`, `SubtaskAnnotator` — whichever appear in the file) is wrapped in `<Card>` with a `<h3 className="text-heading-5 text-ink mb-md">` title.

Pattern to apply for each block:
```tsx
<Card className="mb-xl">
  <h3 className="text-heading-5 text-ink mb-md">Joint trajectory</h3>
  <JointPlot ... />
</Card>
```

Replace ad-hoc colors using the Color Resolution Table from the spec.

- [ ] **Step 3: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ReplayPage.tsx
git commit -m "feat(frontend/replay): wrap blocks in Card + apply Mintlify tokens"
```

---

## Task 17: Refactor `SettingsPage`

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

This page has three sections (Devices / Configurations / Calibration) plus a config-edit modal. The structure (state, API calls, useEffect, modal trigger) is preserved verbatim — only JSX class strings, button variants, and the section/modal chrome change. `PropertyRow` does **not** fit this page's layout shape (no name/type/description triplets); we drop it for SettingsPage. Apply the rewrite below in one pass.

- [ ] **Step 1: Read the current file**

Run: `cat frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 2: Replace the JSX returned from `SettingsPage` (everything from `return (` through the closing `)`) with the block below**

Keep the imports and all logic above unchanged. The only addition to imports is `Card` and `Badge`:

```tsx
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { CameraConfigForm } from "../components/CameraConfigForm";
```

Replace the JSX:

```tsx
  return (
    <div>
      <header className="flex items-center justify-between pb-md mb-xl border-b border-hairline-soft">
        <h2 className="text-heading-3 text-ink">Settings</h2>
      </header>

      {/* Devices */}
      <section className="mb-xxl">
        <div className="flex items-center justify-between mb-md">
          <h3 className="text-micro-uppercase uppercase tracking-[0.5px] text-steel">Devices</h3>
          <Button variant="secondary" size="sm" onClick={loadDevices} disabled={refreshingDevices}>
            {refreshingDevices ? "Refreshing..." : "Refresh"}
          </Button>
        </div>
        <Card className="grid grid-cols-2 gap-xl">
          <div>
            <h4 className="text-caption-bold text-steel mb-xs">Serial Ports</h4>
            {serialPorts.length === 0 ? (
              <p className="text-body-sm text-stone">No serial ports found</p>
            ) : (
              <div className="flex flex-col gap-1">
                {serialPorts.map((p) => (
                  <div key={p.port} className="flex items-center gap-xs text-body-sm">
                    <span
                      className={`w-2 h-2 rounded-full ${p.available ? "bg-brand-green" : "bg-brand-error"}`}
                      aria-hidden
                    />
                    <span className="font-mono text-code-sm text-charcoal">{p.port}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div>
            <h4 className="text-caption-bold text-steel mb-xs">Cameras</h4>
            {cameras.length === 0 ? (
              <p className="text-body-sm text-stone">No cameras found</p>
            ) : (
              <div className="flex flex-col gap-1">
                {cameras.map((c) => (
                  <div key={c.path} className="flex items-center gap-xs text-body-sm">
                    <span
                      className={`w-2 h-2 rounded-full ${c.available ? "bg-brand-green" : "bg-brand-error"}`}
                      aria-hidden
                    />
                    <span className="font-mono text-code-sm text-charcoal">{c.path}</span>
                    {c.available && (
                      <span className="text-caption text-stone">
                        {c.width}x{c.height}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
      </section>

      {/* Configurations */}
      <section className="mb-xxl">
        <div className="flex items-center justify-between mb-md">
          <h3 className="text-micro-uppercase uppercase tracking-[0.5px] text-steel">Configurations</h3>
          <Button variant="secondary" size="sm" onClick={loadConfigs} disabled={refreshingConfigs}>
            {refreshingConfigs ? "Refreshing..." : "Refresh"}
          </Button>
        </div>
        {CONFIG_GROUPS.map((group) => (
          <div key={group} className="mb-md">
            <h4 className="text-caption-bold text-steel mb-xs capitalize">{group}</h4>
            <div className="flex flex-col gap-1">
              {(configs[group] || []).map((cfg) => (
                <div
                  key={cfg.name}
                  className="flex items-center justify-between bg-surface rounded-md px-md py-xs"
                >
                  <div className="flex items-center gap-xs">
                    <span className="text-body-sm-medium text-ink">{cfg.name}</span>
                    {(cfg.content as Record<string, unknown>)?._target_ && (
                      <Badge variant="type">
                        {String((cfg.content as Record<string, unknown>)._target_).split(".").pop()}
                      </Badge>
                    )}
                  </div>
                  <Button
                    variant="link"
                    onClick={() => {
                      setEditingConfig({ ...cfg, group });
                      setEditJson(JSON.stringify(cfg.content, null, 2));
                    }}
                  >
                    Edit
                  </Button>
                </div>
              ))}
            </div>
          </div>
        ))}
      </section>

      {/* Config editor modal */}
      {editingConfig && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-canvas-dark/40"
          onClick={() => setEditingConfig(null)}
        >
          <div
            className="bg-canvas rounded-lg border border-hairline p-xl w-[600px] max-h-[80vh] overflow-auto"
            onClick={(e) => e.stopPropagation()}
          >
            {editingConfig.group === "cameras"
              && (editingConfig.content as Record<string, unknown>)._target_
                  === "mimicrec.cameras.opencv_camera.OpenCVCamera" ? (
              <CameraConfigForm
                name={editingConfig.name}
                currentContent={editingConfig.content as Record<string, unknown>}
                onSave={(validationSkipped) => {
                  setEditingConfig(null);
                  if (validationSkipped) {
                    alert(
                      "Saved. Camera was busy so the configured parameters " +
                        "will be validated when the next session starts.",
                    );
                  }
                  loadConfigs();
                }}
                onCancel={() => setEditingConfig(null)}
              />
            ) : (
              <>
                <h3 className="text-heading-5 text-ink mb-xs">
                  Edit {editingConfig.group}/{editingConfig.name}
                </h3>
                <textarea
                  className="w-full h-64 rounded-md border border-hairline bg-canvas p-md font-mono text-code-sm text-charcoal mb-md focus:outline-none focus:border-2 focus:border-ink"
                  value={editJson}
                  onChange={(e) => setEditJson(e.target.value)}
                />
                <div className="flex justify-end gap-xs">
                  <Button variant="secondary" onClick={() => setEditingConfig(null)}>Cancel</Button>
                  <Button onClick={handleSaveConfig}>Save</Button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Calibration */}
      <section>
        <div className="flex items-center justify-between mb-md">
          <h3 className="text-micro-uppercase uppercase tracking-[0.5px] text-steel">Calibration</h3>
          <Button variant="secondary" size="sm" onClick={loadCalibrations} disabled={refreshingCalibrations}>
            {refreshingCalibrations ? "Refreshing..." : "Refresh"}
          </Button>
        </div>
        {Object.entries(calibrations).map(([category, robots]) => (
          <div key={category} className="mb-sm">
            <h4 className="text-caption-bold text-steel mb-xs capitalize">{category}</h4>
            {Object.entries(robots).length === 0 ? (
              <p className="text-body-sm text-stone">No calibrations found</p>
            ) : (
              <div className="flex flex-col gap-1">
                {Object.entries(robots).map(([robotType, ids]) => (
                  <div key={robotType} className="bg-surface rounded-md px-md py-xs text-body-sm">
                    <span className="text-body-sm-medium text-ink">{robotType}</span>
                    <span className="ml-xs text-stone">
                      {ids.length > 0 ? ids.join(", ") : "no calibrations"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        <p className="mt-xs text-caption text-stone">
          Run calibration:{" "}
          <code className="rounded-xs border border-hairline bg-surface px-1.5 py-0.5 font-mono text-code-inline text-charcoal">
            python scripts/calibrate_so101.py --port /dev/ttyACM0 --id my_arm --type follower
          </code>
        </p>
      </section>
    </div>
  );
```

- [ ] **Step 3: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "feat(frontend/settings): apply Mintlify tokens to devices/configs/calibration sections"
```

---

## Task 18: Refactor `InferencePage`

**Files:**
- Modify: `frontend/src/pages/InferencePage.tsx`

- [ ] **Step 1: Read the current file**

Run: `cat frontend/src/pages/InferencePage.tsx`

- [ ] **Step 2: Apply token + state-pill changes**

- Wrap the top in a header band identical to other pages.
- For inference stream / connection status: replace inline status indicators with a `<PillTab active tone="state">Streaming</PillTab>` when active, plain `<span className="text-stone">Stopped</span>` when not.
- Render numerical metrics (latency ms, tokens/s, etc.) with `<CodeInline>{value}</CodeInline>`.
- Replace ad-hoc colors per the Color Resolution Table.

- [ ] **Step 3: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/InferencePage.tsx
git commit -m "feat(frontend/inference): apply Mintlify tokens; PillTab status; CodeInline metrics"
```

---

## Task 19: Refactor camera/recording domain components

**Files:**
- Modify: `frontend/src/components/CameraConfigForm.tsx`
- Modify: `frontend/src/components/CameraPreview.tsx`
- Modify: `frontend/src/components/EStopButton.tsx`
- Modify: `frontend/src/components/KeyboardTeleop.tsx`
- Modify: `frontend/src/components/SessionConfigForm.tsx`

(`RecordingControls.tsx` has its own dedicated Task 19a with explicit code because of its state-branched JSX.)

- [ ] **Step 1: Read each file**

Run: `for f in CameraConfigForm CameraPreview EStopButton KeyboardTeleop SessionConfigForm; do echo "=== $f ==="; cat "frontend/src/components/$f.tsx"; done`

- [ ] **Step 2: Apply token replacements per the Color Resolution Table**

For each file, do a targeted Edit pass:

| Pattern | Replacement |
|---|---|
| `bg-gray-50` | `bg-surface-soft` |
| `bg-gray-100` | `bg-surface` |
| `bg-gray-200` | `bg-surface` |
| `bg-yellow-50` / `bg-amber-50` | `bg-brand-warn/10` |
| `border-yellow-200` / `border-amber-200` | `border-brand-warn/30` |
| `text-yellow-800` / `text-amber-800` | `text-brand-warn` |
| `text-amber-{600,700}` | `text-brand-warn` |
| `border-gray-200` | `border-hairline` |
| `border-gray-100` | `border-hairline-soft` |
| `text-gray-400` | `text-stone` |
| `text-gray-500` | `text-steel` |
| `text-gray-600` | `text-slate` |
| `text-gray-700` | `text-charcoal` |
| `text-gray-{800,900}` | `text-ink` |
| `text-blue-{600,700}` | `text-ink text-body-sm-medium` (links) or `text-brand-tag` (info) |
| `text-red-{600,700,800}` / `bg-red-*` | `text-brand-error` / `bg-brand-error/10` |
| `bg-green-100 text-green-700` | `<Badge variant="success">` |
| inline button styles | `<Button variant="primary|secondary|link|ghost">` |
| literal `rounded-md` / `rounded-lg` border + bg | `<Card>` (where the block is a panel) |

Where a block visually represents a panel (border + padding + bg), wrap it in `<Card>` from `./ui/card`.

For Badge-shaped status pills (e.g., "ACTIVE" / "ERROR" / "PAUSED"): replace with `<Badge variant="success|destructive|warning|outline" className="text-micro-uppercase uppercase tracking-[0.5px]">…</Badge>`.

EStopButton: keep its high-visibility intent — the destructive button is `<Button variant="primary" className="!bg-brand-error !text-on-dark hover:!bg-brand-error/90">` to override the default black with the safety red.

- [ ] **Step 3: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/{CameraConfigForm,CameraPreview,EStopButton,KeyboardTeleop,SessionConfigForm}.tsx
git commit -m "feat(frontend): apply Mintlify tokens to camera config + session config + e-stop + keyboard components"
```

---

## Task 19a: Rewrite `RecordingControls`

**Files:**
- Modify: `frontend/src/components/RecordingControls.tsx`

The component renders three distinct state branches (ready / recording / review) plus the auto-cycle badge. The logic above the JSX (state, callbacks, timers, keyboard handler) is preserved verbatim — only the returned JSX and the `cycleBadge` element change.

- [ ] **Step 1: Replace the `cycleBadge` const, the three `if (sessionState === ...)` JSX returns, and final `return null;` with the block below**

```tsx
  const cycleBadge = cycleActive && (
    <Badge variant="tag" className="gap-2">
      Auto cycle{cycleCountdown !== null ? ` · ${cycleCountdown}s` : ""}
      <button className="ml-2 text-caption underline" onClick={cancelCycle}>
        cancel (Esc)
      </button>
    </Badge>
  );

  if (sessionState === "ready") {
    return (
      <div className="flex flex-col gap-sm">
        {cycleBadge}
        <Button
          size="lg"
          className="!bg-brand-error !text-on-dark hover:!bg-brand-error/90"
          onClick={() => {
            if (autoCycle) setCycleActive(true);
            episodeStart.mutate();
          }}
        >
          Start Recording (Space){autoCycle ? " · cycle ON" : ""}
        </Button>
      </div>
    );
  }

  if (sessionState === "recording") {
    const effectiveFps = fps ?? 30;
    return (
      <div className="flex flex-col gap-sm">
        <div className="flex items-center gap-md">
          <Badge variant="destructive" className="gap-2">
            <span className="w-2 h-2 bg-on-dark rounded-full animate-pulse" />
            Recording
          </Badge>
          {progress && (
            <span className="text-body-sm text-slate">
              {progress.num_frames} frames &middot; {(progress.num_frames / effectiveFps).toFixed(1)}s
            </span>
          )}
          {cycleBadge}
        </div>
        <Button size="lg" onClick={() => episodeStop.mutate()}>
          Stop Recording (Space)
        </Button>
      </div>
    );
  }

  if (sessionState === "review") {
    return (
      <div className="flex flex-col gap-md">
        <div className="flex items-center gap-sm">
          <div className="text-heading-5 text-charcoal">Review Episode</div>
          {cycleBadge}
        </div>
        <div className="flex gap-xs">
          <Button
            size="sm"
            variant={successLabel === true ? "primary" : "secondary"}
            className={successLabel === true ? "!bg-brand-green !text-primary" : ""}
            onClick={() => setSuccessLabel(true)}
          >
            1: Success
          </Button>
          <Button
            size="sm"
            variant={successLabel === false ? "primary" : "secondary"}
            className={successLabel === false ? "!bg-brand-error !text-on-dark" : ""}
            onClick={() => setSuccessLabel(false)}
          >
            2: Failure
          </Button>
          <Button
            size="sm"
            variant={successLabel === null ? "primary" : "secondary"}
            className={successLabel === null ? "!bg-brand-warn !text-on-dark" : ""}
            onClick={() => setSuccessLabel(null)}
          >
            3: Skip
          </Button>
        </div>
        <div className="flex gap-sm">
          <Button className="!bg-brand-green !text-primary hover:!bg-brand-green-deep" onClick={() => saveWith(true)}>
            Save Success (Space)
          </Button>
          <Button className="!bg-brand-warn !text-on-dark" onClick={() => saveWith(false)}>
            Save Failure (F)
          </Button>
          <Button variant="secondary" onClick={handleDiscard}>
            Discard (D)
          </Button>
        </div>
      </div>
    );
  }

  return null;
}
```

- [ ] **Step 2: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/RecordingControls.tsx
git commit -m "feat(frontend): rewrite RecordingControls JSX to Mintlify tokens (state branches preserved)"
```

---

## Task 20: Refactor plot/replay domain components

**Files:**
- Modify: `frontend/src/components/EEMonitor.tsx`
- Modify: `frontend/src/components/EndEffectorPlot.tsx`
- Modify: `frontend/src/components/JointPlot.tsx`
- Modify: `frontend/src/components/VideoPlayer.tsx`

- [ ] **Step 1: Read each file**

Run: `for f in EEMonitor EndEffectorPlot JointPlot VideoPlayer; do echo "=== $f ==="; cat "frontend/src/components/$f.tsx"; done`

- [ ] **Step 2: Apply token replacements**

Apply the same Color Resolution mapping as Task 19. Specifically for Recharts (`JointPlot`, `EndEffectorPlot`):
- Chrome (legend, axes labels, tooltips): use `var(--color-steel)` / `var(--color-charcoal)` / `var(--color-hairline)` via inline styles where Recharts requires raw color strings.
- Series colors: keep existing palette unless they were ad-hoc Tailwind defaults — Recharts series colors are functional, not chrome, so they are out of scope for this refresh. Note this in the commit message.

For `VideoPlayer`:
- Border / controls bg → `border-hairline` / `bg-canvas-dark` (timeline scrubber etc.)
- Captions / metadata → `text-caption text-stone`

- [ ] **Step 3: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/{EEMonitor,EndEffectorPlot,JointPlot,VideoPlayer}.tsx
git commit -m "feat(frontend): apply Mintlify tokens to plot and video components (chart palettes preserved)"
```

---

## Task 21: Refactor subtask + modal domain components

**Files:**
- Modify: `frontend/src/components/SubtaskAnnotator.tsx`
- Modify: `frontend/src/components/SubtaskTimeline.tsx`
- Modify: `frontend/src/components/ExportDatasetModal.tsx`

- [ ] **Step 1: Read each file**

Run: `for f in SubtaskAnnotator SubtaskTimeline ExportDatasetModal; do echo "=== $f ==="; cat "frontend/src/components/$f.tsx"; done`

- [ ] **Step 2: Apply token replacements**

For `ExportDatasetModal.tsx`, the amber warning blocks at lines 117/127/144-145 and surrounding chrome should switch to:
- `bg-amber-50` → `bg-brand-warn/10`
- `text-amber-800` / `text-amber-700` / `text-amber-600` → `text-brand-warn`
- The modal frame itself: backdrop `bg-canvas-dark/40`, panel `bg-canvas rounded-lg border border-hairline p-xl`.
- Buttons inside: `<Button variant="primary">`, `<Button variant="secondary">`.

For `SubtaskAnnotator.tsx` and `SubtaskTimeline.tsx`:
- Apply the same Color Resolution Table mapping as Task 19.
- The subtask category chips in `SubtaskTimeline.tsx` (currently `COLORS = ["bg-blue-200 text-blue-800", …]` at lines 17-26) **must be converted to inline styles** so the Task 22 grep stays clean. Replace the `COLORS` constant and the line that consumes it with:

```tsx
// Functional category palette — these are NOT theme tokens; the
// distinct hues identify subtask categories at a glance.
const SUBTASK_CHIP_PALETTE = [
  { bg: "#dbeafe", fg: "#1e40af" }, // blue
  { bg: "#dcfce7", fg: "#166534" }, // green
  { bg: "#ede9fe", fg: "#5b21b6" }, // purple
  { bg: "#ffedd5", fg: "#9a3412" }, // orange
  { bg: "#fce7f3", fg: "#9d174d" }, // pink
  { bg: "#ccfbf1", fg: "#115e59" }, // teal
  { bg: "#fef9c3", fg: "#854d0e" }, // yellow
  { bg: "#fee2e2", fg: "#991b1b" }, // red
] as const;
```

And the chip render (was `className={\`... ${COLORS[i % COLORS.length]}\`}`) becomes:

```tsx
<div
  className="flex items-center justify-center text-caption-bold truncate px-1"
  style={{
    backgroundColor: SUBTASK_CHIP_PALETTE[i % SUBTASK_CHIP_PALETTE.length].bg,
    color: SUBTASK_CHIP_PALETTE[i % SUBTASK_CHIP_PALETTE.length].fg,
  }}
>
```

This keeps the visual signal but moves the color tokens off Tailwind utilities, so Task 22's grep does not flag them.

- [ ] **Step 3: Verify the build succeeds**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/{SubtaskAnnotator,SubtaskTimeline,ExportDatasetModal}.tsx
git commit -m "feat(frontend): apply Mintlify tokens to subtask + export modal components"
```

---

## Task 22: Verification grep — no surviving ad-hoc colors

**Files:**
- None modified; this is a verification gate.

- [ ] **Step 1: Run the grep that the spec mandates**

Run:
```bash
PALETTE='blue|purple|red|green|gray|yellow|amber|orange|pink|teal|cyan|indigo|violet|fuchsia|rose|sky|emerald|lime|stone|zinc|slate|neutral'
grep -rEn "(text|bg|border|ring|from|to|via|outline|fill|stroke|divide|placeholder|caret|accent|decoration|shadow)-(${PALETTE})-[0-9]+" frontend/src/ --include='*.tsx' --include='*.ts' --exclude=index.css || echo "CLEAN"
```
Expected: `CLEAN` (i.e., grep finds nothing). If any matches remain, fix them by re-applying the Color Resolution Table to the offending file in a follow-up task. The widened regex catches `ring-blue-500`, `border-red-200`, `bg-orange-200`, `text-pink-800`, etc. — patterns that the narrower original regex missed.

- [ ] **Step 2: Run the build one more time**

Run: `pnpm --dir frontend build`
Expected: success.

- [ ] **Step 3: Commit (only if step 1 produced fixes)**

If step 1 needed fixes, commit them:
```bash
git add -u frontend/src
git commit -m "feat(frontend): clean up remaining ad-hoc colors found by grep gate"
```
If step 1 was clean on first run, no commit needed for this task.

---

## Task 23: Manual smoke test — all six pages

**Files:**
- None modified; this is a verification gate.

- [ ] **Step 1: Start the dev server**

Run: `pnpm --dir frontend dev` (in background or a separate terminal). Wait for `http://localhost:5173` to be ready.

- [ ] **Step 2: Walk every page**

Open each of the following routes in a browser. For each, confirm the listed expectations.

| Route | Expectations |
|---|---|
| `/datasets` | Header band; black "New Dataset" pill; click it → modal opens with token-styled inputs; existing rows: Export/Annotate/Delete render as text links; Delete is red. |
| `/record` | Idle: header band; SessionConfigForm inside a feature card. Active (if you can start a session): info bar uses CodeInline values; Replaying state shows a mint pill; End Session is a secondary pill with red text. |
| `/datasets/<some>/episodes` | Header band; episodes table styled identically to Datasets table. |
| `/datasets/<some>/episodes/<idx>/replay` | Each plot/video block wrapped in a card with `text-heading-5` title. |
| `/settings` | Header band; section headings in micro-uppercase steel; entries render as PropertyRow where applicable. |
| `/inference` | Header band; status as PillTab when active; metrics in CodeInline. |

For every page, confirm:
- Inter font on UI text (DevTools → Computed → font-family).
- Geist Mono on values inside CodeInline.
- Sidebar active item has surface background; non-active items are steel-colored.
- Connection pill at the bottom of the sidebar is visible (mint dot + "Connected").

- [ ] **Step 3: Stop the dev server**

Ctrl+C in the dev server terminal. No commit for this task — it is a manual gate.

If any expectation fails, file a follow-up task referencing the specific page + observation; do not amend prior commits unless the failure is a typo.

---

## Done

When Task 23 passes, the refresh is complete on this branch. Final state:
- `frontend/src/index.css` carries every Mintlify token.
- 5 refactored + 5 new primitives in `frontend/src/components/ui/`.
- `Layout.tsx` rewritten as the Mintlify shell.
- All 6 pages and 13 domain components consume tokens / primitives only.
- The grep gate (Task 22) confirms no ad-hoc Tailwind palette colors remain.
