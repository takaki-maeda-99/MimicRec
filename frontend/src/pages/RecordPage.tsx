import { useEffect } from "react";
import { useSessionStore } from "../state/session-store.ts";
import { useEndSession, useSessionState } from "../api/queries.ts";
import { WsConnection } from "../api/ws.ts";
import SessionConfigForm from "../components/SessionConfigForm.tsx";
import CameraPreview from "../components/CameraPreview.tsx";
import RecordingControls from "../components/RecordingControls.tsx";
import KeyboardTeleop from "../components/KeyboardTeleop.tsx";
import EEMonitor from "../components/EEMonitor.tsx";
import EStopButton from "../components/EStopButton.tsx";
import type { EpisodeProgress, ReplayProgress } from "../api/types.ts";

export default function RecordPage() {
  const sessionState = useSessionStore((s) => s.state);
  const subState = useSessionStore((s) => s.subState);
  const cameras = useSessionStore((s) => s.cameras);
  const dataset = useSessionStore((s) => s.dataset);
  const robot = useSessionStore((s) => s.robot);
  const teleop = useSessionStore((s) => s.teleop);
  const mode = useSessionStore((s) => s.mode);
  const setSessionState = useSessionStore((s) => s.setSessionState);
  const setEpisodeProgress = useSessionStore((s) => s.setEpisodeProgress);
  const setReplayProgress = useSessionStore((s) => s.setReplayProgress);
  const setError = useSessionStore((s) => s.setError);
  const endSession = useEndSession();

  // Restore session state from API on mount (survives page navigation / refresh)
  const { data: apiState } = useSessionState();
  useEffect(() => {
    if (apiState && apiState.state !== "idle") {
      setSessionState(apiState as unknown as Record<string, unknown>);
    }
  }, [apiState, setSessionState]);

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
      if (msgType === "episode_progress")
        setEpisodeProgress(msgData as unknown as EpisodeProgress);
      if (msgType === "replay_progress")
        setReplayProgress(msgData as unknown as ReplayProgress);
      if (msgType === "error")
        setError(msgData as unknown as { error: string; message: string });
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
      {/* Session info bar */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold">Record</h2>
        <div className="flex items-center gap-3">
          {subState === "replaying" && (
            <span className="bg-purple-100 text-purple-700 px-3 py-1 rounded-full text-sm font-medium">
              Replaying...
            </span>
          )}
          <button
            className="text-sm text-red-600 hover:text-red-800 border border-red-300 px-3 py-1 rounded-md"
            onClick={() => endSession.mutate()}
          >
            End Session
          </button>
        </div>
      </div>

      {/* Active session summary */}
      <div className="bg-gray-100 rounded-lg px-4 py-2 mb-6 flex gap-6 text-sm text-gray-600">
        <span>
          <span className="text-gray-400">Robot:</span>{" "}
          <span className="font-medium text-gray-800">{robot}</span>
        </span>
        <span>
          <span className="text-gray-400">Mode:</span>{" "}
          <span className="font-medium text-gray-800">{mode}</span>
        </span>
        <span>
          <span className="text-gray-400">Teleop:</span>{" "}
          <span className="font-medium text-gray-800">{teleop || "—"}</span>
        </span>
        <span>
          <span className="text-gray-400">Dataset:</span>{" "}
          <span className="font-medium text-gray-800">{dataset}</span>
        </span>
        {cameras.length > 0 && (
          <span>
            <span className="text-gray-400">Cameras:</span>{" "}
            <span className="font-medium text-gray-800">
              {cameras.join(", ")}
            </span>
          </span>
        )}
      </div>

      {/* Camera previews */}
      {cameras.length > 0 && sessionState !== "review" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          {cameras.map((cam) => (
            <CameraPreview key={cam} camName={cam} />
          ))}
        </div>
      )}

      {/* Keyboard teleop (only when web_keyboard adapter is selected) */}
      {teleop === "web_keyboard" && (
        <div className="mb-6">
          <KeyboardTeleop enabled={sessionState !== "review"} />
        </div>
      )}

      {/* Live end-effector pose (shows only if backend sends ee_pos) */}
      <div className="mb-6">
        <EEMonitor enabled />
      </div>

      {/* E-stop button (only for rebotarm adapter) */}
      {robot === "rebotarm" && (
        <div className="mb-6">
          <EStopButton />
        </div>
      )}

      {/* Recording controls */}
      <RecordingControls />
    </div>
  );
}
