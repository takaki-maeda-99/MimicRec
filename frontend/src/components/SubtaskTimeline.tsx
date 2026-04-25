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

const COLORS = [
  "bg-blue-200 text-blue-800",
  "bg-green-200 text-green-800",
  "bg-purple-200 text-purple-800",
  "bg-orange-200 text-orange-800",
  "bg-pink-200 text-pink-800",
  "bg-teal-200 text-teal-800",
  "bg-yellow-200 text-yellow-800",
  "bg-red-200 text-red-800",
];

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
      <h3 className="text-sm font-medium text-gray-500 mb-3">Subtask Timeline</h3>

      {/* Visual timeline bar */}
      <div className="flex rounded-lg overflow-hidden h-8 mb-3">
        {segments.map((seg, i) => {
          const width = ((seg.endFrame - seg.startFrame + 1) / totalFrames) * 100;
          return (
            <div
              key={i}
              className={`flex items-center justify-center text-xs font-medium truncate px-1 ${COLORS[i % COLORS.length]}`}
              style={{ width: `${Math.max(width, 2)}%` }}
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
            <span className={`w-3 h-3 rounded ${COLORS[i % COLORS.length].split(" ")[0]}`} />
            <span className="font-medium">{seg.name}</span>
            <span className="text-gray-400">
              {seg.startTime.toFixed(1)}–{seg.endTime.toFixed(1)}s
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
