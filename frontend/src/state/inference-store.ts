import { create } from "zustand";
import { apiFetch, ApiError } from "../api/client";
import { inferenceApi, type InferenceEvent, type ContractSpecDump } from "../api/inference";

export type InferencePhase = "pre-start" | "ready" | "recording" | "review";

interface SafetyEventLog {
  kind: string;
  at: number;
}

export interface ContractItem {
  name: string;
  title?: string;
  description: string;
  error?: string;
}

export interface InferenceStoreState {
  phase: InferencePhase;
  configs: ContractItem[];
  selectedConfig: string;
  selectedDataset: string;
  configSpec: ContractSpecDump | null;
  instruction: string;
  lockedInstruction: string | null;
  error: string | null;
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
  loadConfigs: () => Promise<void>;
  selectConfig: (name: string) => Promise<void>;
  selectDataset: (name: string) => void;
  setInstruction: (text: string) => void;
  setError: (msg: string | null) => void;
  startSession: () => Promise<void>;
  stopSession: () => Promise<void>;
  rehydrateFromBackend: () => Promise<void>;
  updateInstruction: () => Promise<void>;
  startEpisode: () => Promise<void>;
  stopEpisode: () => Promise<void>;
  commitEpisode: (success: boolean | null) => Promise<void>;
  discardEpisode: () => Promise<void>;
  emergencyStop: () => Promise<void>;
  handleEvent: (e: InferenceEvent) => void;
}


function formatError(e: unknown): string {
  if (e instanceof ApiError) return `HTTP ${e.status}: ${e.message}`;
  if (e instanceof Error) return e.message;
  return String(e);
}

async function guard<T>(set: (msg: string | null) => void, fn: () => Promise<T>): Promise<T | undefined> {
  try {
    set(null);
    return await fn();
  } catch (e) {
    set(formatError(e));
    return undefined;
  }
}


export const useInferenceStore = create<InferenceStoreState>((set, get) => ({
  phase: "pre-start",
  configs: [],
  selectedConfig: "",
  selectedDataset: "",
  configSpec: null,
  instruction: "",
  lockedInstruction: null,
  error: null,
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

  setError: (msg) => set({ error: msg }),

  loadConfigs: async () => {
    await guard(
      (msg) => set({ error: msg }),
      async () => {
        const r = await inferenceApi.listConfigs();
        set({ configs: r.items ?? [] });
      },
    );
  },

  selectConfig: async (name) => {
    set({ selectedConfig: name, configSpec: null });
    if (!name) return;
    const item = get().configs.find((c) => c.name === name);
    if (item?.error) {
      set({ error: `Config "${name}" failed to load: ${item.error}` });
      return;
    }
    await guard(
      (msg) => set({ error: msg }),
      async () => {
        const spec = await inferenceApi.getConfig(name);
        const hasDone = !!spec.response.done;
        set({
          configSpec: spec,
          telemetry: { ...get().telemetry, modelDoneSignal: hasDone ? "waiting" : "unsupported" },
        });
      },
    );
  },

  selectDataset: (name) => set({ selectedDataset: name }),

  setInstruction: (text) => set({ instruction: text }),

  startSession: async () => {
    const { selectedConfig, selectedDataset, instruction } = get();
    const ok = await guard(
      (msg) => set({ error: msg }),
      async () => {
        await inferenceApi.start({
          session_config_ref: "default",
          inference_config_ref: selectedConfig,
          dataset_ref: selectedDataset,
          instruction,
        });
        return true;
      },
    );
    if (ok) set({ phase: "ready" });
  },

  stopSession: async () => {
    const ok = await guard(
      (msg) => set({ error: msg }),
      async () => {
        await inferenceApi.stop();
        return true;
      },
    );
    // Only tear down UI state on success — if the backend rejected the stop
    // (e.g. mid-transition), keep the live phase so the operator can retry
    // or hit E-STOP rather than losing the WS subscription / live controls.
    if (ok) set({ phase: "pre-start", lockedInstruction: null, reviewEpisode: null });
  },

  rehydrateFromBackend: async () => {
    await guard(
      (msg) => set({ error: msg }),
      async () => {
        const st = await inferenceApi.state();
        // Backend uses underscore form; store uses hyphen.
        const backendPhase = st.phase;
        const phase: InferencePhase =
          backendPhase === "pre_start" ? "pre-start" : backendPhase;
        const next: Partial<InferenceStoreState> = { phase };
        if (st.instruction != null) next.instruction = st.instruction;
        if (st.locked_instruction != null) next.lockedInstruction = st.locked_instruction;
        set(next as InferenceStoreState);
      },
    );
  },

  updateInstruction: async () => {
    await guard(
      (msg) => set({ error: msg }),
      () => inferenceApi.updateInstruction(get().instruction),
    );
  },

  startEpisode: async () => {
    await guard(
      (msg) => set({ error: msg }),
      () => apiFetch<unknown>("/api/episode/start", { method: "POST", body: JSON.stringify({}) }),
    );
  },

  stopEpisode: async () => {
    await guard(
      (msg) => set({ error: msg }),
      () => apiFetch<unknown>("/api/episode/stop", { method: "POST", body: JSON.stringify({}) }),
    );
  },

  commitEpisode: async (success) => {
    await guard(
      (msg) => set({ error: msg }),
      () => apiFetch<unknown>("/api/episode/save", {
        method: "POST",
        body: JSON.stringify({ success, comment: null }),
      }),
    );
  },

  discardEpisode: async () => {
    await guard(
      (msg) => set({ error: msg }),
      () => apiFetch<unknown>("/api/episode/discard", { method: "POST", body: JSON.stringify({}) }),
    );
  },

  emergencyStop: async () => {
    await guard(
      (msg) => set({ error: msg }),
      () => inferenceApi.estop(),
    );
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
        set({ instruction: e.instruction });
        break;
      case "instruction_locked":
        set({ lockedInstruction: e.instruction });
        break;
      case "instruction_released":
        set({ lockedInstruction: null });
        break;
      case "next_action_preview":
        if (Array.isArray(e.ee_delta) && typeof e.gripper === "number") {
          set({ telemetry: { ...t, nextAction: { ee_delta: e.ee_delta, gripper: e.gripper } } });
        }
        break;
      case "episode_phase":
        if (e.phase === "ready" || e.phase === "recording" || e.phase === "review") {
          set({ phase: e.phase });
        }
        break;
      case "model_done":
        set({ telemetry: { ...t, modelDoneSignal: "received" } });
        break;
      case "watchdog_timeout":
        set({ phase: "review" });
        break;
      case "inference_chunk_dropped_stale":
      case "inference_started":
        break;
    }
  },
}));
