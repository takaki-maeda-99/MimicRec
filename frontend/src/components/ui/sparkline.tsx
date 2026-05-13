import { cn } from "../../lib/utils";

interface SparklineProps {
  data: number[];
  /** "ok" → brand-green-deep; "warn" → brand-warn. */
  tone?: "ok" | "warn";
  width?: number;
  height?: number;
  strokeWidth?: number;
  className?: string;
}

/**
 * Pure: map numeric series → SVG polyline points string.
 * Min / max are inferred from the data; if the series is flat,
 * we draw it on the vertical midline.
 */
function pointsFor(data: number[], width: number, height: number): string {
  if (data.length === 0) return "";
  if (data.length === 1) return `0,${height / 2} ${width},${height / 2}`;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min;
  const step = width / (data.length - 1);

  return data
    .map((v, i) => {
      const x = i * step;
      const y =
        range === 0 ? height / 2 : height - ((v - min) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

export function Sparkline({
  data,
  tone = "ok",
  width = 160,
  height = 14,
  strokeWidth = 1,
  className,
}: SparklineProps) {
  const stroke =
    tone === "warn" ? "var(--color-brand-warn)" : "var(--color-brand-green-deep)";
  const pts = pointsFor(data, width, height);

  return (
    <svg
      className={cn("block", className)}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden
    >
      <polyline points={pts} fill="none" stroke={stroke} strokeWidth={strokeWidth} />
    </svg>
  );
}

// exported for ad-hoc reuse / spot-checking; not part of the rendered API
export const __testing__ = { pointsFor };
