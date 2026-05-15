import { useMemo } from "react";
import { useEpisodeFrames } from "../hooks/useEpisodeFrames";

interface Props {
  ds: string;
  idx: number;
  cursorFrameIdx?: number;
  version?: string | null;
}

// Backend writes EE position as a 3-vector "observation.state.ee_pos"
// (parquet row produced in backend/mimicrec/recording/parquet_row.py).
// We use [0]=x, [1]=y for the top-down trajectory.
const EE_KEY = "observation.state.ee_pos";

export default function EndEffectorPlot({ ds, idx, cursorFrameIdx, version }: Props) {
  const { data: rows = [], isLoading: loading } = useEpisodeFrames(ds, idx, true, version);

  const { xs, ys } = useMemo(() => {
    const xArr: number[] = [];
    const yArr: number[] = [];
    for (const r of rows) {
      const ee = r[EE_KEY];
      if (Array.isArray(ee) && typeof ee[0] === "number" && typeof ee[1] === "number") {
        xArr.push(ee[0] as number);
        yArr.push(ee[1] as number);
      }
    }
    return { xs: xArr, ys: yArr };
  }, [rows]);

  if (loading) return <p className="text-stone p-4">Loading chart...</p>;
  if (xs.length === 0) {
    return <p className="text-stone p-4">No EE position data for this episode.</p>;
  }

  // Domain bounds with 5% padding
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const padX = (maxX - minX) * 0.05 || 0.01;
  const padY = (maxY - minY) * 0.05 || 0.01;
  const xLo = minX - padX, xHi = maxX + padX;
  const yLo = minY - padY, yHi = maxY + padY;
  const rngX = xHi - xLo || 1;
  const rngY = yHi - yLo || 1;

  // ViewBox is fixed; we let the SVG scale via preserveAspectRatio.
  const W = 200;
  const H = 140;
  const project = (x: number, y: number) => ({
    px: ((x - xLo) / rngX) * W,
    // Flip Y so positive Y goes up on screen.
    py: H - ((y - yLo) / rngY) * H,
  });

  const path = xs
    .map((x, i) => {
      const { px, py } = project(x, ys[i]);
      return `${i === 0 ? "M" : "L"}${px.toFixed(2)},${py.toFixed(2)}`;
    })
    .join(" ");

  const start = project(xs[0], ys[0]);
  const end = project(xs[xs.length - 1], ys[ys.length - 1]);

  const cursorIdx =
    typeof cursorFrameIdx === "number"
      ? Math.min(Math.max(cursorFrameIdx, 0), xs.length - 1)
      : null;
  const cursor = cursorIdx != null ? project(xs[cursorIdx], ys[cursorIdx]) : null;

  return (
    <div className="w-full h-full min-h-0 bg-surface-soft rounded-sm relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
        className="absolute inset-0 w-full h-full"
        aria-label="End-effector XY trajectory"
      >
        {/* Origin crosshair (mid-domain) */}
        <line x1={W / 2} y1={0} x2={W / 2} y2={H} stroke="var(--color-hairline-soft)" strokeWidth="0.4" />
        <line x1={0} y1={H / 2} x2={W} y2={H / 2} stroke="var(--color-hairline-soft)" strokeWidth="0.4" />

        {/* Trajectory */}
        <path d={path} stroke="var(--color-brand-tag)" strokeWidth="1.2" fill="none" />

        {/* Start / end markers */}
        <circle cx={start.px} cy={start.py} r="2.4" fill="var(--color-brand-green-deep)" />
        <circle cx={end.px}   cy={end.py}   r="2.4" fill="var(--color-brand-error)" />

        {/* Cursor (current frame position) */}
        {cursor && (
          <circle cx={cursor.px} cy={cursor.py} r="2.6" fill="var(--color-ink)" stroke="var(--color-canvas)" strokeWidth="0.8" />
        )}
      </svg>

      {/* Legend */}
      <div className="absolute bottom-1 right-2 flex items-center gap-2 font-mono text-[10px] text-stone bg-canvas/80 px-1.5 py-0.5 rounded-sm">
        <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-brand-green-deep" /> start</span>
        <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-brand-error" /> end</span>
      </div>
    </div>
  );
}
