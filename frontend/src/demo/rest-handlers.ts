import { http, HttpResponse } from "msw";
import {
  demoStore,
  emit,
  pushFakeEpisode,
  setSession,
} from "./store";

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

export const restHandlers = [...lifecycleHandlers];
