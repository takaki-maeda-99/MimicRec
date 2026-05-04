import { create } from "zustand";
import { apiFetch } from "../api/client";
import { inferenceApi, type InferenceEvent, type ContractSpecDump } from "../api/inference";

export type InferencePhase = "pre-start" | "ready" | "recording" | "review";

interface SafetyEventLog {
  kind: string;
  at: number;  // epoch ms
}

export interface InferenceStoreState {
  phase: InferencePhase;
  configs: { name: string; description: string }[];
  selectedConfig: string;
  selectedDataset: string;
  configSpec: ContractSpecDump | null;
  instruction: string;
  lockedInstruction: string | null;
  telemetry: {
    bufferDepth: number;
    bufferOrigin: number;
    lastLatencyMs: number | null;
    chunksConsumed: number;
    inferenceErrors: number;
    safetyEvents: SafetyEventLog[];
    nextAction: { ee_delta: number[]; gripper: number } | null;
    modelDoneSignal: "waiting" | "received" | "unsupported";
    clampsLastChunk: number | null;
  };
  episodeElapsedSec: number;
  reviewEpisode: { index: number; durationSec: number } | null;
  // actions
  loadConfigs: () => Promise<void>;
  selectConfig: (name: string) => Promise<void>;
  selectDataset: (name: string) => void;
  setInstruction: (text: string) => void;
  startSession: () => Promise<void>;
  stopSession: () => Promise<void>;
  updateInstruction: () => Promise<void>;
  startEpisode: () => Promise<void>;
  stopEpisode: () => Promise<void>;
  commitEpisode: (success: boolean | null) => Promise<void>;
  discardEpisode: () => Promise<void>;
  emergencyStop: () => Promise<void>;
  handleEvent: (e: InferenceEvent) => void;
}


export const useInferenceStore = create<InferenceStoreState>((set, get) => ({
  phase: "pre-start",
  configs: [],
  selectedConfig: "",
  selectedDataset: "",
  configSpec: null,
  instruction: "",
  lockedInstruction: null,
  telemetry: {
    bufferDepth: 0,
    bufferOrigin: 0,
    lastLatencyMs: null,
    chunksConsumed: 0,
    inferenceErrors: 0,
    safetyEvents: [],
    nextAction: null,
    modelDoneSignal: "waiting",
    clampsLastChunk: null,
  },
  episodeElapsedSec: 0,
  reviewEpisode: null,

  loadConfigs: async () => {
    const r = await inferenceApi.listConfigs();
    set({ configs: r.items });
  },

  selectConfig: async (name) => {
    set({ selectedConfig: name });
    if (!name) return;
    try {
      const spec = await inferenceApi.getConfig(name);
      const hasDone = !!spec.response.done;
      set({
        configSpec: spec,
        telemetry: { ...get().telemetry, modelDoneSignal: hasDone ? "waiting" : "unsupported" },
      });
    } catch {
      set({ configSpec: null });
    }
  },

  selectDataset: (name) => set({ selectedDataset: name }),

  setInstruction: (text) => set({ instruction: text }),

  startSession: async () => {
    const { selectedConfig, selectedDataset, instruction } = get();
    await inferenceApi.start({
      session_config_ref: "default",
      inference_config_ref: selectedConfig,
      dataset_ref: selectedDataset,
      instruction,
    });
    set({ phase: "ready" });
  },

  stopSession: async () => {
    await inferenceApi.stop();
    set({ phase: "pre-start", lockedInstruction: null, reviewEpisode: null });
  },

  updateInstruction: async () => {
    await inferenceApi.updateInstruction(get().instruction);
  },

  startEpisode: async () => {
    await apiFetch<unknown>("/api/episode/start", { method: "POST", body: JSON.stringify({}) });
  },

  stopEpisode: async () => {
    await apiFetch<unknown>("/api/episode/stop", { method: "POST", body: JSON.stringify({}) });
  },

  commitEpisode: async (success) => {
    await apiFetch<unknown>("/api/episode/save", {
      method: "POST",
      body: JSON.stringify({ success, comment: null }),
    });
  },

  discardEpisode: async () => {
    await apiFetch<unknown>("/api/episode/discard", { method: "POST", body: JSON.stringify({}) });
  },

  emergencyStop: async () => {
    await inferenceApi.estop();
  },

  handleEvent: (e) => {
    const t = get().telemetry;
    switch (e.type) {
      case "buffer_state":
        set({ telemetry: { ...t, bufferDepth: e.depth, bufferOrigin: e.origin_size } });
        break;
      case "inference_done":
        set({ telemetry: { ...t, lastLatencyMs: e.latency_ms } });
        break;
      case "inference_error":
        set({ telemetry: { ...t, inferenceErrors: t.inferenceErrors + 1 } });
        break;
      case "clamps_per_chunk":
        set({ telemetry: { ...t, clampsLastChunk: e.count } });
        break;
      case "safety_event":
        set({
          telemetry: {
            ...t,
            safetyEvents: [...t.safetyEvents.slice(-49), { kind: e.kind, at: Date.now() }],
          },
        });
        break;
      case "instruction_updated":
        set({ instruction: e.text });
        break;
      case "instruction_locked":
        set({ lockedInstruction: e.text });
        break;
      case "instruction_released":
        set({ lockedInstruction: null });
        break;
      case "next_action_preview":
        set({ telemetry: { ...t, nextAction: { ee_delta: e.ee_delta, gripper: e.gripper } } });
        break;
      case "episode_phase":
        set({ phase: e.phase as InferencePhase });
        break;
      case "model_done":
        set({ telemetry: { ...t, modelDoneSignal: "received" } });
        break;
      case "watchdog_timeout":
        set({ phase: "review" });
        break;
      case "inference_chunk_dropped_stale":
      case "inference_started":
        // No store update needed; surface via toast/log if desired.
        break;
    }
  },
}));
