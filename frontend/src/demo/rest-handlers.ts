import { http, HttpResponse } from "msw";
import {
  demoStore,
  emit,
  pushFakeEpisode,
  setSession,
} from "./store";
import { CONFIG_NAMES, SEED_DATASETS, SEED_TASKS } from "./seed";

const FPS = 30;

export const lifecycleHandlers = [
  http.get("/api/session/state", () => HttpResponse.json(demoStore.session)),

  http.post("/api/session/start", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    setSession({
      state: "ready",
      sub_state: null,
      mode: (body.mode as string) ?? "teleop",
      dataset: (body.dataset as string) ?? "demo_dataset",
      task: (body.task as string) ?? "demo_task",
      robot: (body.robot as string) ?? "so101",
      teleop: (body.teleop as string) ?? "so_leader",
      mapper: (body.mapper as string) ?? "identity",
      cameras: (body.cameras as string[]) ?? ["front"],
      gopros: [],
      fps: FPS,
      preview_enabled: true,
    });
    return HttpResponse.json(demoStore.session);
  }),

  http.post("/api/session/end", () => {
    setSession({
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
    });
    return HttpResponse.json(demoStore.session);
  }),

  http.post("/api/episode/start", () => {
    demoStore.recordingStartedAtMs = performance.now();
    setSession({ state: "recording", sub_state: null });
    emit("recording-start");
    return HttpResponse.json(demoStore.session);
  }),

  http.post("/api/episode/stop", () => {
    demoStore.recordingStartedAtMs = null;
    setSession({ state: "review", sub_state: null });
    emit("recording-stop");
    return HttpResponse.json(demoStore.session);
  }),

  http.post("/api/episode/save", () => {
    pushFakeEpisode();
    setSession({ state: "ready", sub_state: null });
    return HttpResponse.json(demoStore.session);
  }),

  http.post("/api/episode/discard", () => {
    setSession({ state: "ready", sub_state: null });
    return HttpResponse.json(demoStore.session);
  }),

  http.post("/api/replay/start", () => {
    demoStore.replayFrameIndex = 0;
    setSession({ state: "recording", sub_state: "replaying" });
    emit("replay-start");
    return HttpResponse.json(demoStore.session);
  }),

  http.post("/api/replay/stop", () => {
    demoStore.replayFrameIndex = null;
    setSession({ state: "ready", sub_state: null });
    emit("replay-stop");
    return HttpResponse.json(demoStore.session);
  }),

  http.post("/api/robot/estop", () => {
    demoStore.estopActive = true;
    return HttpResponse.json({ ok: true });
  }),

  http.post("/api/robot/clear_estop", () => {
    demoStore.estopActive = false;
    return HttpResponse.json({ ok: true });
  }),
];

const FIXTURE_URL = `${import.meta.env.BASE_URL}demo/episode_0`;

async function loadMeta() {
  const res = await fetch(`${FIXTURE_URL}/meta.json`);
  return res.json() as Promise<{
    frames: Array<{
      t: number;
      joint_pos: number[];
      joint_vel: number[];
      joint_effort: number[];
      gripper_pos: number;
      ee_pos: number[];
      ee_rotvec: number[];
    }>;
    fps: number;
    num_frames: number;
    cameras: string[];
    joint_names: string[];
    robot: string;
  }>;
}

let metaCachePromise: ReturnType<typeof loadMeta> | null = null;
export function getMeta() {
  if (!metaCachePromise) metaCachePromise = loadMeta();
  return metaCachePromise;
}

export const dataHandlers = [
  http.get("/api/datasets", () => {
    const list = SEED_DATASETS.map((d) => ({
      ...d,
      num_episodes: demoStore.episodes.length,
      total_frames: demoStore.episodes.length * 240,
    }));
    return HttpResponse.json(list);
  }),

  http.get("/api/datasets/:ds/tasks", () => HttpResponse.json(SEED_TASKS)),

  http.get("/api/datasets/:ds/episodes", ({ request }) => {
    const url = new URL(request.url);
    const includeDeleted = url.searchParams.get("include_deleted") === "true";
    const visible = demoStore.episodes.filter(
      (e) => includeDeleted || !demoStore.tombstones.has(e.episode_index),
    );
    return HttpResponse.json(visible);
  }),

  http.delete("/api/datasets/:ds/episodes/:idx", ({ params }) => {
    const idx = Number(params.idx);
    if (demoStore.tombstones.has(idx)) demoStore.tombstones.delete(idx);
    else demoStore.tombstones.add(idx);
    return HttpResponse.json({ ok: true });
  }),

  http.get("/api/datasets/:ds/schema", async () => {
    const meta = await getMeta();
    return HttpResponse.json({
      fps: meta.fps,
      robot: meta.robot,
      cameras: meta.cameras,
      joint_names: meta.joint_names,
      image_keys: meta.cameras.map((c) => `observation.images.${c}`),
    });
  }),

  http.get("/api/datasets/:ds/episodes/:idx/frames", async () => {
    const meta = await getMeta();
    const rows = meta.frames.map((f, i) => ({
      frame_index: i,
      timestamp: f.t,
      ...Object.fromEntries(
        meta.joint_names.flatMap((n, j) => [
          [`observation.state.${n}`, f.joint_pos[j]],
          [`action.${n}`, f.joint_pos[j]],
        ]),
      ),
      "observation.state.gripper": f.gripper_pos,
      "observation.ee.pos.x": f.ee_pos[0],
      "observation.ee.pos.y": f.ee_pos[1],
      "observation.ee.pos.z": f.ee_pos[2],
    }));
    return HttpResponse.json(rows);
  }),

  http.get("/api/datasets/:ds/episodes/:idx/video/:cam", async () => {
    const res = await fetch(`${FIXTURE_URL}/cam_front.mp4`);
    const buf = await res.arrayBuffer();
    return new HttpResponse(buf, {
      status: 200,
      headers: { "Content-Type": "video/mp4" },
    });
  }),

  http.get("/api/configs/camera_roles", () => HttpResponse.json({ roles: ["front", "wrist"] })),

  http.get("/api/configs/:group", ({ params }) => {
    const group = String(params.group);
    return HttpResponse.json(CONFIG_NAMES[group] ?? []);
  }),

  http.get("/api/settings/configs/:group", ({ params }) => {
    const group = String(params.group);
    if (group === "gopros") {
      return new HttpResponse(null, { status: 404 });
    }
    const names = CONFIG_NAMES[group] ?? [];
    return HttpResponse.json(names.map((name) => ({ name, content: {} })));
  }),

  http.get("/api/session/gopro_pending", () => HttpResponse.json({ pending: 0 })),
];

function demoUnsupported() {
  return HttpResponse.json(
    { detail: "Not available in demo" },
    { status: 503 },
  );
}

export const stubHandlers = [
  http.post("/api/datasets", demoUnsupported),
  http.delete("/api/datasets/:ds", demoUnsupported),
  http.post("/api/datasets/:ds/export", demoUnsupported),
  http.post("/api/datasets/:ds/annotate-all", demoUnsupported),
  http.get("/api/datasets/:ds/annotate-progress", demoUnsupported),
  http.post("/api/datasets/:ds/episodes/:idx/annotate", demoUnsupported),

  http.get("/api/cloud/auth-status", demoUnsupported),
  http.get("/api/datasets/:ds/hub", demoUnsupported),
  http.put("/api/datasets/:ds/hub", demoUnsupported),
  http.post("/api/datasets/:ds/hub/push", demoUnsupported),

  http.get("/api/settings/devices/serial", demoUnsupported),
  http.get("/api/settings/devices/cameras", () => HttpResponse.json([])),
  http.get("/api/settings/devices/cameras/:id/capabilities", () => HttpResponse.json([])),
  http.get("/api/settings/calibration", demoUnsupported),
  http.put("/api/settings/calibration", demoUnsupported),
  http.put("/api/settings/configs/:group/:name", demoUnsupported),
  http.post("/api/settings/configs/:group/:name", demoUnsupported),
  http.delete("/api/settings/configs/:group/:name", demoUnsupported),
];

export const restHandlers = [...lifecycleHandlers, ...dataHandlers, ...stubHandlers];
