import { useMemo, useRef, useState } from "react";
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
  ReferenceLine,
} from "recharts";
import { useEpisodeFrames } from "../hooks/useEpisodeFrames";

interface Props {
  ds: string;
  idx: number;
  cursorTimeSec?: number;
  onSeek?: (timeSec: number) => void;
}

const COLORS = [
  "#2563eb", "#dc2626", "#16a34a", "#9333ea",
  "#ea580c", "#0891b2", "#be185d", "#65a30d", "#6d28d9",
];

export default function JointPlot({ ds, idx, cursorTimeSec, onSeek }: Props) {
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

  // Derive activeMode to avoid flicker when velocity becomes unavailable.
  // User preference (mode) is preserved; activeMode ensures the chart never
  // renders with an unavailable series.
  const activeMode: "position" | "velocity" = hasVelocity ? mode : "position";

  if (loading) return <p className="text-stone p-4">Loading chart...</p>;
  if (!data.length) return <p className="text-stone p-4">No data</p>;

  const prefix = activeMode === "position" ? "pos_" : "vel_";
  const unit = activeMode === "position" ? "rad" : "rad/s";

  const tMin = data[0]?.time ?? 0;
  const tMax = data[data.length - 1]?.time ?? 0;
  const overlayRef = useRef<HTMLDivElement | null>(null);

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!onSeek || tMax <= tMin) return;
    const rect = overlayRef.current?.getBoundingClientRect();
    if (!rect) return;
    // Recharts 3.x default LineChart left margin is 20 / right is 30. If you've
    // overridden margins on the LineChart, mirror those here. With unchanged
    // defaults this gives accurate click-anywhere seek.
    const LEFT = 20;
    const RIGHT = 30;
    const plotWidth = Math.max(1, rect.width - LEFT - RIGHT);
    const px = e.clientX - rect.left - LEFT;
    const fraction = Math.min(1, Math.max(0, px / plotWidth));
    onSeek(tMin + fraction * (tMax - tMin));
  };

  return (
    <div>
      {hasVelocity && (
        <SegmentedTabBar className="mb-3">
          <SegmentedTab active={activeMode === "position"} onClick={() => setMode("position")}>
            Position
          </SegmentedTab>
          <SegmentedTab active={activeMode === "velocity"} onClick={() => setMode("velocity")}>
            Velocity
          </SegmentedTab>
        </SegmentedTabBar>
      )}
      <div className="relative w-full h-full">
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-hairline)" opacity={0.6} />
            <XAxis
              dataKey="time"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(t: number) => `${t.toFixed(1)}s`}
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
            {typeof cursorTimeSec === "number" && (
              <ReferenceLine
                x={cursorTimeSec}
                stroke="var(--color-ink)"
                strokeOpacity={0.7}
                ifOverflow="visible"
              />
            )}
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
        {onSeek && (
          <div
            ref={overlayRef}
            className="absolute inset-0 cursor-crosshair"
            onClick={handleClick}
            aria-hidden
          />
        )}
      </div>
    </div>
  );
}
