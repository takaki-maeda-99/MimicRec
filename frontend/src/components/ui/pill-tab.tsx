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
