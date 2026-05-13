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
 * we draw it on the vertical midline. The `strokeWidth` is baked
 * into a top/bottom padding so the line never clips at the viewBox
 * edges (half the stroke would otherwise extend outside).
 */
function pointsFor(
  data: number[],
  width: number,
  height: number,
  strokeWidth: number,
): string {
  if (data.length === 0) return "";
  const pad = strokeWidth / 2;
  const drawableH = height - 2 * pad;
  if (data.length === 1) {
    const mid = pad + drawableH / 2;
    return `0,${mid} ${width},${mid}`;
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min;
  const step = width / (data.length - 1);

  return data
    .map((v, i) => {
      const x = i * step;
      const y =
        range === 0
          ? pad + drawableH / 2
          : pad + drawableH - ((v - min) / range) * drawableH;
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
  const pts = pointsFor(data, width, height, strokeWidth);

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
