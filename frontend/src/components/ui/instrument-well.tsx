import { cn } from "../../lib/utils";
import { CornerTicks } from "./corner-ticks";

interface InstrumentWellProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Mono uppercase header strip text, e.g. "CAM · 01 · FRONT". */
  header?: React.ReactNode;
  /** When true, shows a pulsing teal LIVE indicator on the header. */
  live?: boolean;
  /** Show corner ticks. Default true. */
  ticks?: boolean;
  /** Optional caption rendered below the body. */
  caption?: React.ReactNode;
  children?: React.ReactNode;
}

export function InstrumentWell({
  header,
  live,
  ticks = true,
  caption,
  children,
  className,
  ...props
}: InstrumentWellProps) {
  return (
    <div
      className={cn(
        "relative bg-canvas-dark text-on-dark rounded-md overflow-hidden",
        "flex flex-col min-h-0",
        "px-sm py-xs",
        className,
      )}
      {...props}
    >
      {ticks && <CornerTicks tone="dark" />}
      {(header || live) && (
        <div className="relative flex items-baseline justify-between mb-xs flex-shrink-0 font-mono text-micro-uppercase uppercase tracking-[0.14em] text-on-dark-dim">
          <span>{header}</span>
          {live && (
            <span className="inline-flex items-center gap-1.5 text-brand-green">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-green animate-pulse" />
              LIVE
            </span>
          )}
        </div>
      )}
      <div className="relative flex-1 min-h-0">{children}</div>
      {caption && (
        <div className="relative mt-xs text-micro text-on-dark-dim flex-shrink-0">
          {caption}
        </div>
      )}
    </div>
  );
}
