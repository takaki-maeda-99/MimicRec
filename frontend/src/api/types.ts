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
}

export interface DatasetSummary {
  name: string;
  num_episodes: number;
  total_frames: number;
}

export interface EpisodeSummary {
  episode_index: number;
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
