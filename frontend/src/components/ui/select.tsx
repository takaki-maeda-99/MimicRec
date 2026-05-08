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
