import { useMemo } from "react";
import { useEpisodeFrames } from "../../hooks/useEpisodeFrames";

interface Props {
  ds: string;
  idx: number;
}

const TRACE_COLORS = ["#3772cf", "#d45656", "#00b48a", "#5a5a5c", "#c37d0d", "#888888"];

export function MiniJointPlot({ ds, idx }: Props) {
  const { data: rows = [] } = useEpisodeFrames(ds, idx);

  const { traces, gripper, n } = useMemo(() => {
    if (!rows.length) return { traces: [] as number[][], gripper: [] as number[], n: 0 };
    const nJoints = (rows[0]["observation.state.joint_pos"] as number[] | undefined)?.length ?? 0;
    const out: number[][] = Array.from({ length: Math.min(nJoints, 6) }, () => []);
    const grip: number[] = [];
    for (const r of rows) {
      const pos = r["observation.state.joint_pos"] as number[] | undefined;
      if (!pos) continue;
      for (let i = 0; i < out.length; i++) out[i].push(pos[i]);
      const g = (r["action.gripper_pos"] ?? r["observation.gripper_pos"]) as number | undefined;
      grip.push(typeof g === "number" ? g : NaN);
    }
    return { traces: out, gripper: grip, n: rows.length };
  }, [rows]);

  if (n === 0) return <Empty />;

  return (
    <svg viewBox="0 0 200 44" preserveAspectRatio="none" className="w-full h-[44px] block">
      {traces.map((tr, i) => (
        <polyline key={i} points={pathPoints(tr, n)} stroke={TRACE_COLORS[i % TRACE_COLORS.length]} strokeWidth="0.9" fill="none" />
      ))}
      {gripper.some((g) => !Number.isNaN(g)) && (
        <polyline points={pathPoints(gripper, n)} stroke="var(--color-ink)" strokeWidth="0.9" strokeDasharray="2 2" fill="none" />
      )}
    </svg>
  );
}

function pathPoints(values: number[], n: number): string {
  if (!values.length) return "";
  const min = Math.min(...values.filter(Number.isFinite));
  const max = Math.max(...values.filter(Number.isFinite));
  const range = max - min || 1;
  const out: string[] = [];
  for (let i = 0; i < values.length; i++) {
    const x = (i / Math.max(1, n - 1)) * 200;
    const v = Number.isFinite(values[i]) ? values[i] : (min + max) / 2;
    const y = 42 - ((v - min) / range) * 38 - 2;
    out.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  return out.join(" ");
}

function Empty() {
  return <div className="h-[44px] flex items-center justify-center text-stone text-caption">—</div>;
}
