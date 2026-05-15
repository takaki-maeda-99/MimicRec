import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";

export interface FrameRow {
  timestamp: number;
  "observation.state.joint_pos"?: number[];
  "observation.state.joint_vel"?: number[];
  [key: string]: unknown;
}

/**
 * Fetches the frames parquet for a single episode and caches it under the
 * stable key ["episode-frames", ds, idx]. Multiple consumers (JointPlot,
 * EndEffectorPlot, MiniJointPlot, MiniEePlot) share the cache so each
 * episode is fetched at most once until it becomes stale.
 */
export function useEpisodeFrames(
  ds: string,
  idx: number,
  enabled = true,
  version?: string | null,
) {
  return useQuery<FrameRow[]>({
    queryKey: ["episode-frames", ds, idx, version ?? null],
    queryFn: () =>
      apiFetch<FrameRow[]>(`/api/datasets/${ds}/episodes/${idx}/frames`),
    enabled: enabled && !!ds && Number.isFinite(idx),
    staleTime: 5 * 60_000,
  });
}
