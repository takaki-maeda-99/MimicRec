import { ws } from "msw";
import { demoEvents, demoStore, emit as emitEvent, setSession } from "./store";
import { getMeta } from "./rest-handlers";
import { subscribeFrames } from "./camera-player";

const STATE_HZ = 30;
const SESSION_HZ = 30;

const sessionWs = ws.link(/.*\/ws\/session$/);
const stateWs   = ws.link(/.*\/ws\/state$/);
const cameraWs  = ws.link(/.*\/ws\/cameras\/[^/]+$/);
const teleopWs  = ws.link(/.*\/ws\/teleop$/);
const inferWs   = ws.link(/.*\/ws\/inference$/);

const sessionHandler = sessionWs.addEventListener("connection", ({ client }) => {
  const sendState = () => client.send(JSON.stringify({ type: "session_state", data: demoStore.session }));
  sendState();

  const onChange = () => sendState();
  demoEvents.addEventListener("session-changed", onChange);

  let progressTimer: number | null = null;
  const startProgress = () => {
    if (progressTimer != null) return;
    progressTimer = window.setInterval(() => {
      if (demoStore.recordingStartedAtMs != null) {
        const elapsedSec = (performance.now() - demoStore.recordingStartedAtMs) / 1000;
        client.send(JSON.stringify({
          type: "episode_progress",
          data: {
            num_frames: Math.floor(elapsedSec * 30),
            stale_sample_count: 0,
            writer_queue_depth: 0,
            writer_lag_ms: 0,
            ticks_skipped: 0,
          },
        }));
      } else if (demoStore.replayFrameIndex != null) {
        client.send(JSON.stringify({
          type: "replay_progress",
          data: {
            frame_index: demoStore.replayFrameIndex,
            total_frames: 240,
            speed: 1.0,
          },
        }));
        demoStore.replayFrameIndex += 1;
        if (demoStore.replayFrameIndex >= 240) {
          autoStopReplay();
        }
      }
    }, 1000 / SESSION_HZ);
  };
  const stopProgress = () => {
    if (progressTimer != null) {
      clearInterval(progressTimer);
      progressTimer = null;
    }
  };
  const autoStopReplay = () => {
    // Replay finished — update store state, emit event, and tell the
    // frontend via session_state so ReplayPage flips back to "ready".
    demoStore.replayFrameIndex = null;
    setSession({ state: "ready", sub_state: null });
    emitEvent("replay-stop");
    stopProgress();
  };

  demoEvents.addEventListener("recording-start", startProgress);
  demoEvents.addEventListener("replay-start", startProgress);
  demoEvents.addEventListener("recording-stop", stopProgress);
  demoEvents.addEventListener("replay-stop", stopProgress);

  client.addEventListener("close", () => {
    demoEvents.removeEventListener("session-changed", onChange);
    demoEvents.removeEventListener("recording-start", startProgress);
    demoEvents.removeEventListener("replay-start", startProgress);
    demoEvents.removeEventListener("recording-stop", stopProgress);
    demoEvents.removeEventListener("replay-stop", stopProgress);
    stopProgress();
  });
});

const stateHandler = stateWs.addEventListener("connection", async ({ client }) => {
  const meta = await getMeta();
  let frameIdx = 0;
  const timer = window.setInterval(() => {
    const f = meta.frames[frameIdx % meta.frames.length];
    client.send(JSON.stringify({
      joint_pos: f.joint_pos,
      joint_vel: f.joint_vel,
      joint_effort: f.joint_effort,
      gripper_pos: f.gripper_pos,
      ee_pos: f.ee_pos,
      ee_rotvec: f.ee_rotvec,
      t_mono_ns: Date.now() * 1_000_000,
    }));
    frameIdx += 1;
  }, 1000 / STATE_HZ);

  client.addEventListener("close", () => clearInterval(timer));
});

const cameraHandler = cameraWs.addEventListener("connection", ({ client }) => {
  const unsubscribe = subscribeFrames((blob) => {
    client.send(blob);
  });
  client.addEventListener("close", () => unsubscribe());
});

const teleopHandler = teleopWs.addEventListener("connection", ({ client }) => {
  // Accept and drop incoming messages.
  client.addEventListener("message", () => {
    /* noop */
  });
});

const inferHandler = inferWs.addEventListener("connection", ({ client }) => {
  client.close(1008, "Demo mode — inference unavailable");
});

export const wsHandlers = [sessionHandler, stateHandler, cameraHandler, teleopHandler, inferHandler];
