import { useMemo } from "react";
import { useEpisodeFrames } from "../../hooks/useEpisodeFrames";

interface Props {
  ds: string;
  idx: number;
  version?: string | null;
}

export function MiniEePlot({ ds, idx, version }: Props) {
  const { data: rows = [] } = useEpisodeFrames(ds, idx, true, version);

  // Backend writes EE position as a 3-vector under "observation.state.ee_pos"
  // (see backend/mimicrec/recording/parquet_row.py). Element 0 = x, 1 = y, 2 = z.
  const points = useMemo(() => {
    const xs: number[] = [];
    const ys: number[] = [];
    for (const r of rows) {
      const ee = r["observation.state.ee_pos"];
      if (Array.isArray(ee) && typeof ee[0] === "number" && typeof ee[1] === "number") {
        xs.push(ee[0] as number);
        ys.push(ee[1] as number);
      }
    }
    return { xs, ys };
  }, [rows]);

  if (points.xs.length === 0) {
    return <div className="aspect-[1.5] bg-surface-soft border border-hairline-soft rounded-sm flex items-center justify-center text-stone text-caption">—</div>;
  }

  const minX = Math.min(...points.xs);
  const maxX = Math.max(...points.xs);
  const minY = Math.min(...points.ys);
  const maxY = Math.max(...points.ys);
  const rngX = maxX - minX || 1;
  const rngY = maxY - minY || 1;
  const W = 100;
  const H = 70;
  const path = points.xs
    .map((x, i) => {
      const px = ((x - minX) / rngX) * (W - 10) + 5;
      const py = H - (((points.ys[i] - minY) / rngY) * (H - 10) + 5);
      return `${i === 0 ? "M" : "L"}${px.toFixed(1)},${py.toFixed(1)}`;
    })
    .join(" ");
  const start = { x: ((points.xs[0] - minX) / rngX) * (W - 10) + 5, y: H - (((points.ys[0] - minY) / rngY) * (H - 10) + 5) };
  const end = {
    x: ((points.xs.at(-1)! - minX) / rngX) * (W - 10) + 5,
    y: H - (((points.ys.at(-1)! - minY) / rngY) * (H - 10) + 5),
  };

  return (
    <div className="aspect-[1.5] bg-surface-soft border border-hairline-soft rounded-sm relative">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 w-full h-full">
        <line x1={W / 2} y1="0" x2={W / 2} y2={H} stroke="var(--color-hairline-soft)" strokeWidth="0.4" />
        <line x1="0" y1={H / 2} x2={W} y2={H / 2} stroke="var(--color-hairline-soft)" strokeWidth="0.4" />
        <path d={path} stroke="var(--color-brand-tag)" strokeWidth="1.3" fill="none" />
        <circle cx={start.x} cy={start.y} r="2" fill="var(--color-brand-green-deep)" />
        <circle cx={end.x} cy={end.y} r="2" fill="var(--color-brand-error)" />
      </svg>
    </div>
  );
}
