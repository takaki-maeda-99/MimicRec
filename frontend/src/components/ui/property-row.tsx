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
