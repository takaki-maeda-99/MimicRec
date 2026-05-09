// Shared sample data for the layout-comparison mocks.
// Numbers are deliberately textured so each design has variety to render.

export interface MockDataset {
  name: string;
  episodes: number;
  frames: number;
  durationMin: number;
  cameras: string[];
  robot: string;
  hubRepo?: string;
  hubState: "synced" | "stale" | "pushing" | "not-pushed" | "not-configured" | "error";
  lastTouched: string;
  taskHint: string;
}

export const SAMPLE_DATASETS: MockDataset[] = [
  {
    name: "learn-data-bottle",
    episodes: 124,
    frames: 184_312,
    durationMin: 51.2,
    cameras: ["front", "wrist"],
    robot: "so101",
    hubRepo: "TakakiMaeda/learn-data-bottle",
    hubState: "synced",
    lastTouched: "2 min ago",
    taskHint: "pick the green bottle and place on tray",
  },
  {
    name: "withnewrenz",
    episodes: 38,
    frames: 56_204,
    durationMin: 15.8,
    cameras: ["front", "wrist", "overhead"],
    robot: "so101",
    hubRepo: "TakakiMaeda/withnewrenz",
    hubState: "stale",
    lastTouched: "yesterday",
    taskHint: "stack the renz cubes",
  },
  {
    name: "REBOT",
    episodes: 6,
    frames: 8_120,
    durationMin: 2.3,
    cameras: ["overhead"],
    robot: "rebotarm",
    hubState: "not-configured",
    lastTouched: "5 days ago",
    taskHint: "rebotarm hand-teach trial",
  },
  {
    name: "camera_test",
    episodes: 12,
    frames: 17_900,
    durationMin: 4.9,
    cameras: ["front"],
    robot: "mock",
    hubState: "pushing",
    hubRepo: "TakakiMaeda/camera-test",
    lastTouched: "now",
    taskHint: "calibration sweep",
  },
  {
    name: "test-export",
    episodes: 22,
    frames: 31_004,
    durationMin: 9.1,
    cameras: ["front", "wrist"],
    robot: "so101",
    hubState: "error",
    hubRepo: "TakakiMaeda/test-export",
    lastTouched: "3 hours ago",
    taskHint: "vla-compat export rehearsal",
  },
];

export const MOCK_USER = "TakakiMaeda";
