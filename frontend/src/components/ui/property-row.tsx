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
