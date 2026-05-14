import { useEffect, useMemo, useState } from "react";
import { SegmentedTab, SegmentedTabBar } from "./ui/segmented-tab";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { useEpisodeFrames } from "../hooks/useEpisodeFrames";

interface Props {
  ds: string;
  idx: number;
}

const COLORS = [
  "#2563eb", "#dc2626", "#16a34a", "#9333ea",
  "#ea580c", "#0891b2", "#be185d", "#65a30d", "#6d28d9",
];

export default function JointPlot({ ds, idx }: Props) {
  const { data: rows = [], isLoading: loading } = useEpisodeFrames(ds, idx);
  const [mode, setMode] = useState<"position" | "velocity">("position");

  const { data, jointNames, hasVelocity } = useMemo(() => {
    if (!rows.length) {
      return { data: [] as Record<string, number>[], jointNames: [] as string[], hasVelocity: false };
    }
    const firstPos = rows[0]["observation.state.joint_pos"];
    if (!Array.isArray(firstPos) || firstPos.length === 0) {
      return { data: [] as Record<string, number>[], jointNames: [] as string[], hasVelocity: false };
    }
    const nJoints = firstPos.length;
    const names = Array.from({ length: nJoints }, (_, i) => `j${i + 1}`);
    let nonzeroVel = false;
    const chartData = rows.map((row) => {
      const pos = row["observation.state.joint_pos"];
      const vel = row["observation.state.joint_vel"];
      const entry: Record<string, number> = {
        time: Math.round((row.timestamp as number) * 1000) / 1000,
      };
      if (Array.isArray(pos)) {
        names.forEach((name, i) => {
          entry[`pos_${name}`] = Math.round(((pos[i] as number) ?? 0) * 1000) / 1000;
          const v = (Array.isArray(vel) ? (vel[i] as number) : 0) ?? 0;
          entry[`vel_${name}`] = Math.round(v * 1000) / 1000;
          if (v !== 0) nonzeroVel = true;
        });
      }
      return entry;
    });
    return { data: chartData, jointNames: names, hasVelocity: nonzeroVel };
  }, [rows]);

  // Clamp mode to position when velocity becomes unavailable. Effect, not
  // render-phase setState — render-phase writes are an anti-pattern under
  // React 18+ concurrent rendering.
  useEffect(() => {
    if (!hasVelocity && mode !== "position") setMode("position");
  }, [hasVelocity, mode]);

  if (loading) return <p className="text-stone p-4">Loading chart...</p>;
  if (!data.length) return <p className="text-stone p-4">No data</p>;

  const prefix = mode === "position" ? "pos_" : "vel_";
  const unit = mode === "position" ? "rad" : "rad/s";

  return (
    <div>
      {hasVelocity && (
        <SegmentedTabBar className="mb-3">
          <SegmentedTab active={mode === "position"} onClick={() => setMode("position")}>
            Position
          </SegmentedTab>
          <SegmentedTab active={mode === "velocity"} onClick={() => setMode("velocity")}>
            Velocity
          </SegmentedTab>
        </SegmentedTabBar>
      )}
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-hairline)" opacity={0.6} />
          <XAxis
            dataKey="time"
            label={{ value: "Time (s)", position: "insideBottom", offset: -5, fill: "var(--color-steel)" }}
            tick={{ fontSize: 11, fill: "var(--color-steel)" }}
          />
          <YAxis
            label={{ value: unit, angle: -90, position: "insideLeft", fill: "var(--color-steel)" }}
            tick={{ fontSize: 11, fill: "var(--color-steel)" }}
          />
          <Tooltip
            contentStyle={{ fontSize: 12, borderColor: "var(--color-hairline)", color: "var(--color-charcoal)" }}
            formatter={(value) => `${Number(value).toFixed(3)} ${unit}`}
          />
          <Legend wrapperStyle={{ fontSize: 11, color: "var(--color-steel)" }} />
          {jointNames.map((name, i) => (
            <Line
              key={name}
              type="monotone"
              dataKey={`${prefix}${name}`}
              name={name}
              stroke={COLORS[i % COLORS.length]}
              dot={false}
              strokeWidth={1.5}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
