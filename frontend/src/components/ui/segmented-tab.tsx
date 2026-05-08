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
