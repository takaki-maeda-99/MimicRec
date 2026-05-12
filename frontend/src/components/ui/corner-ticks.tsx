import { cn } from "../../lib/utils";

interface CornerTicksProps {
  /**
   * "light" → uses brand-warn (visible against canvas / surface).
   * "dark"  → uses on-dark-mark (visible against canvas-dark).
   */
  tone?: "light" | "dark";
  /** px from each corner. Default 6. */
  inset?: number;
  /** px length of each L arm. Default 8. */
  size?: number;
  className?: string;
}

export function CornerTicks({
  tone = "light",
  inset = 6,
  size = 8,
  className,
}: CornerTicksProps) {
  const color =
    tone === "dark" ? "border-on-dark-mark" : "border-brand-warn";
  const common = cn("absolute pointer-events-none", color);
  const style = { width: size, height: size };
  return (
    <div className={cn("absolute inset-0 pointer-events-none", className)} aria-hidden>
      <span
        className={cn(common, "border-t border-l")}
        style={{ ...style, top: inset, left: inset }}
      />
      <span
        className={cn(common, "border-t border-r")}
        style={{ ...style, top: inset, right: inset }}
      />
      <span
        className={cn(common, "border-b border-l")}
        style={{ ...style, bottom: inset, left: inset }}
      />
      <span
        className={cn(common, "border-b border-r")}
        style={{ ...style, bottom: inset, right: inset }}
      />
    </div>
  );
}
