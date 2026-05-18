export interface SessionStatePayload {
  state: "idle" | "ready" | "recording" | "review";
  sub_state: string | null;
  mode: string | null;
  dataset: string | null;
  task: string | null;
  robot: string | null;
  teleop: string | null;
  mapper: string | null;
  cameras: string[];
  fps: number | null;
  preview_enabled?: boolean;
  image_sources?: ImageSource[];
}

export interface DatasetSummary {
  name: string;
  num_episodes: number;
  total_frames: number;
}

export interface EpisodeSummary {
  episode_index: number;
  display_index: number;
  task: string;
  duration_sec: number;
  num_frames: number;
  success: boolean | null;
  robot: string;
  teleop: string | null;
  mode: string;
  recorded_at: string | null;
  cameras: string[];
}

export interface TaskSummary {
  task_index: number;
  task: string;
  instruction: string | null;
}

export interface EpisodeProgress {
  num_frames: number;
  stale_sample_count: number;
  writer_queue_depth: number;
  writer_lag_ms: number;
  ticks_skipped: number;
}

export interface ReplayProgress {
  frame_index: number;
  total_frames: number;
  speed: number;
}

export interface WsMessage {
  type: "session_state" | "episode_progress" | "replay_progress" | "error";
  data: Record<string, unknown>;
}

export type ExportFormat = "lerobot_v3_native" | "vla_compat";

export type RobotTypeOverride = "so101" | "rebot";

export interface ExportRequest {
  format: ExportFormat;
  instruction_template?: string;
  force?: boolean;
  // Legacy-dataset override for VLA_COMPAT export. Set when info.json
  // declares robot_type='unknown' (datasets recorded before the
  // recording-layer adapter-declarations change).
  robot_type?: RobotTypeOverride;
}

export interface ExportResponse {
  dest_path: string;
  format: ExportFormat;
  num_episodes: number;
  num_frames: number;
  warnings: string[];
}

export interface ConfigEntry {
  name: string;
  file?: string;
  content: Record<string, unknown>;
}

export interface ImageSource {
  slot: string;
  device: string;
  kind: "camera";
}
