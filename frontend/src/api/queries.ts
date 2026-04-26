import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client.ts";
import type { DatasetSummary, EpisodeSummary, SessionStatePayload, TaskSummary } from "./types.ts";

// --------------- Datasets ---------------

export function useDeleteDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      fetch(`/api/datasets/${name}`, { method: "DELETE" }).then((r) => {
        if (!r.ok) throw new Error("delete failed");
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["datasets"] }),
  });
}

export function useDatasets() {
  return useQuery({
    queryKey: ["datasets"],
    queryFn: () => apiFetch<DatasetSummary[]>("/api/datasets"),
  });
}

export function useCreateDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      name: string;
      fps?: number;
      joint_names?: string[];
      camera_names?: string[];
    }) =>
      apiFetch<DatasetSummary>("/api/datasets", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["datasets"] }),
  });
}

export function useTasks(ds: string) {
  return useQuery({
    queryKey: ["tasks", ds],
    queryFn: () => apiFetch<TaskSummary[]>(`/api/datasets/${ds}/tasks`),
    enabled: !!ds,
  });
}

// --------------- Episodes ---------------

export function useEpisodes(ds: string, includeDeleted = false) {
  return useQuery({
    queryKey: ["episodes", ds, includeDeleted],
    queryFn: () =>
      apiFetch<EpisodeSummary[]>(
        `/api/datasets/${ds}/episodes?include_deleted=${includeDeleted}`,
      ),
    enabled: !!ds,
  });
}

export function useDeleteEpisode(ds: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (idx: number) =>
      fetch(`/api/datasets/${ds}/episodes/${idx}`, {
        method: "DELETE",
      }).then((r) => {
        if (!r.ok) throw new Error("delete failed");
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["episodes", ds] }),
  });
}

// --------------- Configs ---------------

export function useConfigs(group: string) {
  return useQuery({
    queryKey: ["configs", group],
    queryFn: () => apiFetch<string[]>(`/api/configs/${group}`),
  });
}

// --------------- Session ---------------

export function useSessionState() {
  return useQuery({
    queryKey: ["session-state"],
    queryFn: () => apiFetch<SessionStatePayload>("/api/session/state"),
    refetchInterval: 2000,
  });
}

export function useStartSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiFetch<SessionStatePayload>("/api/session/start", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session-state"] }),
  });
}

export function useEndSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<SessionStatePayload>("/api/session/end", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session-state"] }),
  });
}

// --------------- Episode control ---------------

export function useEpisodeStart() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<SessionStatePayload>("/api/episode/start", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session-state"] }),
  });
}

export function useEpisodeStop() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<SessionStatePayload>("/api/episode/stop", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session-state"] }),
  });
}

export function useEpisodeSave() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body?: { success?: boolean | null; comment?: string | null }) =>
      apiFetch<SessionStatePayload>("/api/episode/save", {
        method: "POST",
        body: JSON.stringify(body ?? {}),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session-state"] }),
  });
}

export function useEpisodeDiscard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<SessionStatePayload>("/api/episode/discard", {
        method: "POST",
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session-state"] }),
  });
}

// --------------- Robot ---------------

export function useEstop() {
  return useMutation({
    mutationFn: () =>
      apiFetch("/api/robot/estop", { method: "POST" }),
  });
}

export function useClearEstop() {
  return useMutation({
    mutationFn: () =>
      apiFetch<{ ok: boolean; reason?: string }>("/api/robot/clear_estop", { method: "POST" }),
  });
}

// --------------- Replay ---------------

export function useReplayStart() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      dataset: string;
      episode_idx: number;
      speed?: number;
    }) =>
      apiFetch<SessionStatePayload>("/api/replay/start", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session-state"] }),
  });
}

export function useReplayStop() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<SessionStatePayload>("/api/replay/stop", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session-state"] }),
  });
}
