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
