import { create } from "zustand";
import type { EpisodeProgress, ReplayProgress } from "../api/types.ts";

interface SessionStore {
  state: "idle" | "ready" | "recording" | "review";
  subState: string | null;
  mode: string | null;
  dataset: string | null;
  task: string | null;
  robot: string | null;
  teleop: string | null;
  mapper: string | null;
  cameras: string[];
  gopros: string[];
  fps: number | null;
  episodeProgress: EpisodeProgress | null;
  replayProgress: ReplayProgress | null;
  lastError: { error: string; message: string } | null;
  // Actions
  setSessionState: (data: Record<string, unknown>) => void;
  setEpisodeProgress: (data: EpisodeProgress) => void;
  setReplayProgress: (data: ReplayProgress) => void;
  setError: (data: { error: string; message: string }) => void;
  clearError: () => void;
}

export const useSessionStore = create<SessionStore>((set) => ({
  state: "idle",
  subState: null,
  mode: null,
  dataset: null,
  task: null,
  robot: null,
  teleop: null,
  mapper: null,
  cameras: [],
  gopros: [],
  fps: null,
  episodeProgress: null,
  replayProgress: null,
  lastError: null,

  setSessionState: (data) =>
    set({
      state: (data.state as SessionStore["state"]) ?? "idle",
      subState: (data.sub_state as string) ?? null,
      mode: (data.mode as string) ?? null,
      dataset: (data.dataset as string) ?? null,
      task: (data.task as string) ?? null,
      robot: (data.robot as string) ?? null,
      teleop: (data.teleop as string) ?? null,
      mapper: (data.mapper as string) ?? null,
      cameras: (data.cameras as string[]) ?? [],
      gopros: (data.gopros as string[]) ?? [],
      fps: (data.fps as number) ?? null,
    }),

  setEpisodeProgress: (data) => set({ episodeProgress: data }),
  setReplayProgress: (data) => set({ replayProgress: data }),
  setError: (data) => set({ lastError: data }),
  clearError: () => set({ lastError: null }),
}));
