import { setupWorker } from "msw/browser";
import { restHandlers } from "./rest-handlers";
import { wsHandlers } from "./ws-handlers";
import { WsConnection } from "../api/ws";
import { useSessionStore } from "../state/session-store";
import type { EpisodeProgress, ReplayProgress } from "../api/types";

// Open a permanent /ws/session subscriber so progress messages reach the
// global session-store regardless of which page is mounted. RecordPage
// also opens its own connection; multiple subscribers are fine.
function startGlobalSessionWs() {
  const conn = new WsConnection("/ws/session");
  conn.onMessage((raw) => {
    const m = raw as { type?: string; data?: unknown };
    const store = useSessionStore.getState();
    if (m.type === "session_state" && m.data) {
      store.setSessionState(m.data as Record<string, unknown>);
    } else if (m.type === "episode_progress" && m.data) {
      store.setEpisodeProgress(m.data as EpisodeProgress);
    } else if (m.type === "replay_progress" && m.data) {
      store.setReplayProgress(m.data as ReplayProgress);
    }
  });
  conn.connect();
}

export async function start() {
  const worker = setupWorker(...restHandlers, ...wsHandlers);
  await worker.start({
    serviceWorker: {
      url: `${import.meta.env.BASE_URL}mockServiceWorker.js`,
      options: { scope: import.meta.env.BASE_URL },
    },
    onUnhandledRequest: "bypass",
  });
  startGlobalSessionWs();
}
