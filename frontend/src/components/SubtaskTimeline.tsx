import { useEffect, useState } from "react";
import { apiFetch } from "../api/client";

interface Props {
  ds: string;
  idx: number;
}

interface Segment {
  name: string;
  startFrame: number;
  endFrame: number;
  startTime: number;
  endTime: number;
}

// Functional category palette — these are NOT theme tokens; the
// distinct hues identify subtask categories at a glance.
const SUBTASK_CHIP_PALETTE = [
  { bg: "#dbeafe", fg: "#1e40af" }, // blue
  { bg: "#dcfce7", fg: "#166534" }, // green
  { bg: "#ede9fe", fg: "#5b21b6" }, // purple
  { bg: "#ffedd5", fg: "#9a3412" }, // orange
  { bg: "#fce7f3", fg: "#9d174d" }, // pink
  { bg: "#ccfbf1", fg: "#115e59" }, // teal
  { bg: "#fef9c3", fg: "#854d0e" }, // yellow
  { bg: "#fee2e2", fg: "#991b1b" }, // red
] as const;

export default function SubtaskTimeline({ ds, idx }: Props) {
  const [segments, setSegments] = useState<Segment[]>([]);
  const [totalFrames, setTotalFrames] = useState(0);

  useEffect(() => {
    apiFetch<Record<string, unknown>[]>(`/api/datasets/${ds}/episodes/${idx}/frames`)
      .then((rows) => {
        if (!rows.length || !("subtask_name" in rows[0])) {
          setSegments([]);
          return;
        }

        setTotalFrames(rows.length);

        // Group consecutive frames by subtask_name
        const segs: Segment[] = [];
        let current: Segment | null = null;

        rows.forEach((row, i) => {
          const name = (row.subtask_name as string) || "unknown";
          const t = (row.timestamp as number) || 0;

          if (!current || current.name !== name) {
            if (current) segs.push(current);
            current = { name, startFrame: i, endFrame: i, startTime: t, endTime: t };
          } else {
            current.endFrame = i;
            current.endTime = t;
          }
        });
        if (current) segs.push(current);
        setSegments(segs);
      })
      .catch(() => setSegments([]));
  }, [ds, idx]);

  if (!segments.length) return null;

  return (
    <div>
      <h3 className="text-sm font-medium text-steel mb-3">Subtask Timeline</h3>

      {/* Visual timeline bar */}
      <div className="flex rounded-lg overflow-hidden h-8 mb-3">
        {segments.map((seg, i) => {
          const width = ((seg.endFrame - seg.startFrame + 1) / totalFrames) * 100;
          return (
            <div
              className="flex items-center justify-center text-caption-bold truncate px-1"
              style={{
                backgroundColor: SUBTASK_CHIP_PALETTE[i % SUBTASK_CHIP_PALETTE.length].bg,
                color: SUBTASK_CHIP_PALETTE[i % SUBTASK_CHIP_PALETTE.length].fg,
                width: `${Math.max(width, 2)}%`,
              }}
              key={i}
              title={`${seg.name} (frame ${seg.startFrame}–${seg.endFrame})`}
            >
              {width > 8 ? seg.name : ""}
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-2">
        {segments.map((seg, i) => (
          <div key={i} className="flex items-center gap-1.5 text-xs">
            <span
              className="w-3 h-3 rounded"
              style={{ backgroundColor: SUBTASK_CHIP_PALETTE[i % SUBTASK_CHIP_PALETTE.length].bg }}
            />
            <span className="font-medium">{seg.name}</span>
            <span className="text-stone">
              {seg.startTime.toFixed(1)}–{seg.endTime.toFixed(1)}s
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
