import { useEffect, useState } from "react";
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
import { apiFetch } from "../api/client";

interface Props {
  ds: string;
  idx: number;
}

const COLORS = [
  "#2563eb", "#dc2626", "#16a34a", "#9333ea",
  "#ea580c", "#0891b2", "#be185d", "#65a30d", "#6d28d9",
];

interface FrameRow {
  timestamp: number;
  "observation.state.joint_pos": number[];
  "observation.state.joint_vel": number[];
  [key: string]: unknown;
}

export default function JointPlot({ ds, idx }: Props) {
  const [data, setData] = useState<Record<string, number>[]>([]);
  const [jointNames, setJointNames] = useState<string[]>([]);
  // hasVelocity is false when the recording is from an adapter that doesn't
  // report joint velocities (e.g. SO-101) — all values are zero. We hide
  // the velocity toggle entirely in that case rather than show a flat line.
  const [hasVelocity, setHasVelocity] = useState(false);
  const [mode, setMode] = useState<"position" | "velocity">("position");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    apiFetch<FrameRow[]>(`/api/datasets/${ds}/episodes/${idx}/frames`)
      .then((rows) => {
        if (!rows.length) return;

        const nJoints = (rows[0]["observation.state.joint_pos"] as number[]).length;
        const names = Array.from({ length: nJoints }, (_, i) => `j${i + 1}`);
        setJointNames(names);

        let nonzeroVel = false;
        const chartData = rows.map((row) => {
          const pos = row["observation.state.joint_pos"] as number[];
          const vel = row["observation.state.joint_vel"] as number[];
          const entry: Record<string, number> = {
            time: Math.round((row.timestamp as number) * 1000) / 1000,
          };
          names.forEach((name, i) => {
            entry[`pos_${name}`] = Math.round(pos[i] * 1000) / 1000;
            const v = vel?.[i] ?? 0;
            entry[`vel_${name}`] = Math.round(v * 1000) / 1000;
            if (v !== 0) nonzeroVel = true;
          });
          return entry;
        });
        setHasVelocity(nonzeroVel);
        if (!nonzeroVel) setMode("position");
        setData(chartData);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [ds, idx]);

  if (loading) return <p className="text-stone p-4">Loading chart...</p>;
  if (!data.length) return <p className="text-stone p-4">No data</p>;

  const prefix = mode === "position" ? "pos_" : "vel_";
  const unit = mode === "position" ? "rad" : "rad/s";

  return (
    <div>
      {hasVelocity && (
        <div className="flex gap-2 mb-3">
          <button
            className={`px-3 py-1 rounded text-sm ${mode === "position" ? "bg-primary text-on-primary" : "bg-surface text-charcoal"}`}
            onClick={() => setMode("position")}
          >
            Position
          </button>
          <button
            className={`px-3 py-1 rounded text-sm ${mode === "velocity" ? "bg-primary text-on-primary" : "bg-surface text-charcoal"}`}
            onClick={() => setMode("velocity")}
          >
            Velocity
          </button>
        </div>
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
