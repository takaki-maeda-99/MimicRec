import type {
  DatasetSummary,
  EpisodeSummary,
  SessionStatePayload,
  TaskSummary,
} from "../api/types";

export const SEED_DATASETS: DatasetSummary[] = [
  { name: "demo_dataset", num_episodes: 1, total_frames: 240 },
];

export const SEED_TASKS: TaskSummary[] = [
  { task_index: 0, task: "demo_task", instruction: "Pick the red cube" },
];

export const SEED_EPISODE: EpisodeSummary = {
  episode_index: 0,
  display_index: 0,
  task: "demo_task",
  duration_sec: 8.0,
  num_frames: 240,
  success: true,
  robot: "so101",
  teleop: "so_leader",
  mode: "teleop",
  recorded_at: "2026-05-13T09:00:00Z",
  cameras: ["front"],
};

export const IDLE_SESSION: SessionStatePayload = {
  state: "idle",
  sub_state: null,
  mode: null,
  dataset: null,
  task: null,
  robot: null,
  teleop: null,
  mapper: null,
  cameras: [],
  fps: null,
  preview_enabled: false,
  image_sources: [],
};

export const CONFIG_NAMES: Record<string, string[]> = {
  robot: ["mock", "so101", "rebotarm"],
  teleop: ["mock_leader", "so_leader", "web_keyboard"],
  mapper: ["identity"],
  cameras: ["mock_front"],
  tasks: ["demo_task"],
};
