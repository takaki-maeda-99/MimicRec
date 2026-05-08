import { apiFetch } from "./client";
import { WsConnection } from "./ws";


// ===== Types matching backend Pydantic models =====

export interface ContractItem {
  name: string;            // file stem — the identifier load endpoints expect
  title?: string;          // human-readable spec name from the YAML
  description: string;
  error?: string;          // present when the YAML failed to parse
}

export interface ContractSpecDump {
  name: string;
  description: string;
  endpoint: { url: string; method: string; timeout_s: number; retry: { max_attempts: number } };
  request: {
    images: Record<string, { field: string; encoding: string; resize: [number, number]; jpeg_quality: number }>;
    state: { field: string; components: string[]; normalization: { method: string } };
    instruction: { field: string };
    extra_fields?: Record<string, string | number | boolean>;
  };
  response: {
    actions_path: string;
    chunk: { expected_size: number; on_size_mismatch: string };
    action: {
      type: string; frame: string;
      pose: { units: string };
      gripper: { kind: string; units: string };
      components: string[];
      normalization: { method: string; stats_ref?: { type: string; dataset?: string; path?: string } };
    };
    done?: { path: string; type: string; threshold: number; scope: string; action_on_done: string };
  };
  loop: { prefetch_threshold: number; max_inflight: number };
}

export interface StartInferenceBody {
  session_config_ref: string;
  inference_config_ref: string;
  dataset_ref: string;
  instruction: string;
}

export interface InferenceState {
  phase: "pre_start" | "ready" | "recording" | "review";
  instruction?: string | null;
  locked_instruction?: string | null;
  buffer_depth?: number;
  buffer_origin?: number;
  chunks_consumed?: number;
  last_inference_latency_ms?: number | null;
  inference_errors?: number;
  last_safety_event?: { kind: string } | null;
}

// Discriminated union of WS event types per spec §8.4.
export type InferenceEvent =
  | { type: "buffer_state"; depth: number; origin_size: number; generation: number }
  | { type: "inference_started"; instruction: string }
  | { type: "inference_done"; latency_ms: number; chunk_size: number }
  | { type: "inference_error"; kind: string; message: string }
  | { type: "inference_chunk_dropped_stale"; generation_was: number; current_generation: number }
  | { type: "safety_event"; kind: string; step_index?: number; joint?: string }
  | { type: "clamps_per_chunk"; count: number; chunk_size: number }
  | { type: "instruction_updated"; instruction: string; flushed_steps: number }
  | { type: "instruction_locked"; instruction: string }
  | { type: "instruction_released" }
  | { type: "next_action_preview"; ee_delta: number[]; gripper: number }
  | { type: "episode_phase"; phase: "ready" | "recording" | "review" }
  | { type: "model_done"; received: boolean }
  | { type: "watchdog_timeout"; elapsed_sec: number };


// ===== REST =====

export const inferenceApi = {
  listConfigs: () =>
    apiFetch<{ items: ContractItem[] }>("/api/configs/inference"),
  getConfig: (name: string) =>
    apiFetch<ContractSpecDump>(`/api/configs/inference/${encodeURIComponent(name)}`),
  start: (body: StartInferenceBody) =>
    apiFetch<{ session_id: string; state: string }>(
      "/api/session/inference/start",
      { method: "POST", body: JSON.stringify(body) },
    ),
  stop: () =>
    apiFetch<{ ok: boolean }>("/api/session/inference/stop", { method: "POST", body: JSON.stringify({}) }),
  updateInstruction: (instruction: string) =>
    apiFetch<{ instruction: string; flushed_steps: number }>(
      "/api/session/inference/instruction",
      { method: "PUT", body: JSON.stringify({ instruction }) },
    ),
  state: () =>
    apiFetch<InferenceState>("/api/session/inference/state"),
  estop: () =>
    apiFetch<unknown>("/api/robot/estop", { method: "POST", body: JSON.stringify({}) }),
};


// ===== WebSocket =====

export function subscribeInferenceWS(
  onEvent: (e: InferenceEvent) => void,
): () => void {
  const conn = new WsConnection("/ws/inference");
  conn.onMessage((msg) => onEvent(msg as unknown as InferenceEvent));
  conn.connect();
  return () => conn.disconnect();
}
