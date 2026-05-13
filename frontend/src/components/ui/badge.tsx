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
