import { useEffect } from "react";
import { useSessionStore } from "../state/session-store.ts";
import { useEndSession } from "../api/queries.ts";
import { WsConnection } from "../api/ws.ts";
import SessionConfigForm from "../components/SessionConfigForm.tsx";
import CameraPreview from "../components/CameraPreview.tsx";
import RecordingControls from "../components/RecordingControls.tsx";
import type { EpisodeProgress, ReplayProgress } from "../api/types.ts";

export default function RecordPage() {
  const sessionState = useSessionStore(s => s.state);
  const subState = useSessionStore(s => s.subState);
  const cameras = useSessionStore(s => s.cameras);
  const setSessionState = useSessionStore(s => s.setSessionState);
  const setEpisodeProgress = useSessionStore(s => s.setEpisodeProgress);
  const setReplayProgress = useSessionStore(s => s.setReplayProgress);
  const setError = useSessionStore(s => s.setError);
  const endSession = useEndSession();

  // Connect to /ws/session when session is active
  const isIdle = sessionState === "idle";
  useEffect(() => {
    if (isIdle) return;
    const conn = new WsConnection("/ws/session");
    conn.onMessage((msg) => {
      const msgType = msg.type as string | undefined;
      const msgData = msg.data as Record<string, unknown> | undefined;
      if (!msgType || !msgData) return;
      if (msgType === "session_state") setSessionState(msgData);
      if (msgType === "episode_progress") setEpisodeProgress(msgData as unknown as EpisodeProgress);
      if (msgType === "replay_progress") setReplayProgress(msgData as unknown as ReplayProgress);
      if (msgType === "error") setError(msgData as unknown as { error: string; message: string });
    });
    conn.connect();
    return () => conn.disconnect();
  }, [isIdle, setSessionState, setEpisodeProgress, setReplayProgress, setError]);

  if (sessionState === "idle") {
    return (
      <div className="p-6">
        <h2 className="text-2xl font-bold mb-6">Record</h2>
        <SessionConfigForm onStarted={() => {}} />
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Record</h2>
        <div className="flex items-center gap-4">
          {subState === "replaying" && (
            <span className="bg-purple-100 text-purple-700 px-3 py-1 rounded-full text-sm font-medium">
              Replaying... leader-arm input ignored
            </span>
          )}
          <button
            className="text-sm text-gray-600 hover:text-gray-900 border border-gray-300 px-3 py-1 rounded-md"
            onClick={() => endSession.mutate()}
          >
            End Session
          </button>
        </div>
      </div>

      {/* Camera previews */}
      {cameras.length > 0 && sessionState !== "review" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          {cameras.map(cam => (
            <CameraPreview key={cam} camName={cam} />
          ))}
        </div>
      )}

      {/* Recording controls */}
      <RecordingControls />
    </div>
  );
}
