import { cn } from "../../lib/utils";
import { SectionMark } from "./section-mark";

interface PageHeaderProps {
  /** Section code, e.g. "§02". */
  code: string;
  /** Title, e.g. "Live capture — pick & place, blue cube". */
  title: React.ReactNode;
  /** Right-aligned state slot, e.g. a REC badge. */
  state?: React.ReactNode;
  /** Right-aligned meta slot, e.g. "pp. 047 – 061". */
  meta?: React.ReactNode;
  /** Right-aligned action slot, e.g. "+ New dataset" button (Datasets). */
  actions?: React.ReactNode;
  className?: string;
}

export function PageHeader({
  code,
  title,
  state,
  meta,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <header
      className={cn(
        "flex items-center gap-md px-xl py-sm border-b border-hairline bg-canvas",
        "flex-shrink-0 min-h-[52px]",
        className,
      )}
    >
      <SectionMark code={code} />
      <h1 className="text-heading-5 text-ink truncate">{title}</h1>
      <span className="flex-1" />
      {state}
      {meta && <span className="font-mono text-micro text-stone">{meta}</span>}
      {actions}
    </header>
  );
}
