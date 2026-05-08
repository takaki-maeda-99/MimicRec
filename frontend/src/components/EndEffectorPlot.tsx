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

interface FrameRow {
  timestamp: number;
  [key: string]: unknown;
}

// Each entry describes one EE-related channel pulled from the parquet rows.
// Adding a new EE signal (e.g. force/torque, suction state) means adding an
// entry here, no other code changes needed.
const CHANNELS: Array<{
  key: string;            // column name in the parquet row
  label: string;          // legend label
  color: string;
  unit: string;
}> = [
  {
    key: "observation.state.gripper_pos",
    label: "gripper_pos (obs)",
    color: "#2563eb",
    unit: "rad",
  },
  {
    key: "action.gripper_pos",
    label: "gripper_pos (act)",
    color: "#dc2626",
    unit: "rad",
  },
];

export default function EndEffectorPlot({ ds, idx }: Props) {
  const [data, setData] = useState<Record<string, number>[]>([]);
  const [presentChannels, setPresentChannels] = useState<typeof CHANNELS>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    apiFetch<FrameRow[]>(`/api/datasets/${ds}/episodes/${idx}/frames`)
      .then((rows) => {
        if (!rows.length) {
          setPresentChannels([]);
          setData([]);
          return;
        }
        const present = CHANNELS.filter((c) =>
          rows.some((r) => typeof r[c.key] === "number")
        );
        const chartData = rows.map((row) => {
          const entry: Record<string, number> = {
            time: Math.round((row.timestamp as number) * 1000) / 1000,
          };
          for (const c of present) {
            const v = row[c.key];
            if (typeof v === "number") {
              entry[c.key] = Math.round(v * 1000) / 1000;
            }
          }
          return entry;
        });
        setPresentChannels(present);
        setData(chartData);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [ds, idx]);

  if (loading) return <p className="text-stone p-4">Loading chart...</p>;
  if (!presentChannels.length) {
    return (
      <p className="text-stone text-sm p-4">
        No end-effector signals recorded for this episode.
      </p>
    );
  }

  // All current channels share a unit; if mixed units appear later, split
  // into per-unit subplots instead of cramming them onto one Y axis.
  const unit = presentChannels[0].unit;

  return (
    <ResponsiveContainer width="100%" height={200}>
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
        {presentChannels.map((c) => (
          <Line
            key={c.key}
            type="monotone"
            dataKey={c.key}
            name={c.label}
            stroke={c.color}
            dot={false}
            strokeWidth={1.5}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
