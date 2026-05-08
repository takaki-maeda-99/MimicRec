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
