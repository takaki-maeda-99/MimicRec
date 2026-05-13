import type { EpisodeSummary, SessionStatePayload } from "../api/types";
import { IDLE_SESSION, SEED_EPISODE } from "./seed";

export const demoStore = {
  episodes: [{ ...SEED_EPISODE }] as EpisodeSummary[],
  tombstones: new Set<number>(),
  session: { ...IDLE_SESSION } as SessionStatePayload,
  recordingStartedAtMs: null as number | null,
  replayFrameIndex: null as number | null,
  estopActive: false,
};

export type DemoEvent =
  | "session-changed"
  | "recording-start"
  | "recording-stop"
  | "replay-start"
  | "replay-stop";

export const demoEvents = new EventTarget();

export function emit(event: DemoEvent) {
  demoEvents.dispatchEvent(new Event(event));
}

export function setSession(patch: Partial<SessionStatePayload>) {
  demoStore.session = { ...demoStore.session, ...patch };
  emit("session-changed");
}

export function pushFakeEpisode(): EpisodeSummary {
  const nextIndex = demoStore.episodes.length;
  const fake: EpisodeSummary = {
    ...SEED_EPISODE,
    episode_index: nextIndex,
    display_index: nextIndex,
    recorded_at: new Date().toISOString(),
  };
  demoStore.episodes = [fake, ...demoStore.episodes];
  return fake;
}
