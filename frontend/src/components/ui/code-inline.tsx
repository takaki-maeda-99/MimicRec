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
