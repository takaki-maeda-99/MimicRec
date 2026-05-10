import { useEffect } from "react";
import { useSessionStore } from "../state/session-store.ts";
import { useEndSession, useEpisodes, useSessionState } from "../api/queries.ts";
import { WsConnection } from "../api/ws.ts";
import SessionConfigForm from "../components/SessionConfigForm.tsx";
import CameraPreview from "../components/CameraPreview.tsx";
import RecordingControls from "../components/RecordingControls.tsx";
import KeyboardTeleop from "../components/KeyboardTeleop.tsx";
import EEMonitor from "../components/EEMonitor.tsx";
import EStopButton from "../components/EStopButton.tsx";
import IdlePoseCaptureButton from "../components/IdlePoseCaptureButton.tsx";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { CodeInline } from "../components/ui/code-inline";
import { PillTab } from "../components/ui/pill-tab";
import type { EpisodeProgress, ReplayProgress } from "../api/types.ts";

export default function RecordPage() {
  const sessionState = useSessionStore((s) => s.state);
  const subState = useSessionStore((s) => s.subState);
  const cameras = useSessionStore((s) => s.cameras);
  const gopros = useSessionStore((s) => s.gopros);
  const previewEnabled = useSessionStore((s) => s.previewEnabled);
  const dataset = useSessionStore((s) => s.dataset);
  const robot = useSessionStore((s) => s.robot);
  const teleop = useSessionStore((s) => s.teleop);
  const mode = useSessionStore((s) => s.mode);
  const setSessionState = useSessionStore((s) => s.setSessionState);
  const setEpisodeProgress = useSessionStore((s) => s.setEpisodeProgress);
  const setReplayProgress = useSessionStore((s) => s.setReplayProgress);
  const setError = useSessionStore((s) => s.setError);
  const endSession = useEndSession();
  const { data: episodes } = useEpisodes(dataset || "");

  const { data: apiState } = useSessionState();
  useEffect(() => {
    if (apiState && apiState.state !== "idle") {
      setSessionState(apiState as unknown as Record<string, unknown>);
    }
  }, [apiState, setSessionState]);

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
      <div>
        <header className="flex items-center justify-between pb-sm mb-lg border-b border-hairline">
          <h2 className="text-heading-3 text-ink">Record</h2>
        </header>
        <Card variant="feature">
          <SessionConfigForm onStarted={() => {}} />
        </Card>
      </div>
    );
  }

  return (
    <div>
      <header className="flex items-center justify-between pb-sm mb-lg border-b border-hairline">
        <h2 className="text-heading-3 text-ink">Record</h2>
        <div className="flex items-center gap-md">
          {subState === "replaying" && (
            <PillTab active tone="state" disabled>Replaying</PillTab>
          )}
          <Button variant="secondary" className="!text-brand-error" onClick={() => endSession.mutate()}>
            End Session
          </Button>
        </div>
      </header>

      <Card className="mb-md flex gap-lg flex-wrap text-body-sm">
        <span className="flex items-center gap-xs">
          <span className="text-caption text-stone">Robot</span>
          <CodeInline>{robot}</CodeInline>
        </span>
        <span className="flex items-center gap-xs">
          <span className="text-caption text-stone">Mode</span>
          <CodeInline>{mode}</CodeInline>
        </span>
        <span className="flex items-center gap-xs">
          <span className="text-caption text-stone">Teleop</span>
          <CodeInline>{teleop || "—"}</CodeInline>
        </span>
        <span className="flex items-center gap-xs">
          <span className="text-caption text-stone">Dataset</span>
          <CodeInline>{dataset}</CodeInline>
        </span>
        <span className="flex items-center gap-xs">
          <span className="text-caption text-stone">Episodes</span>
          <CodeInline>{episodes?.length ?? "—"}</CodeInline>
        </span>
        {cameras.length > 0 && (
          <span className="flex items-center gap-xs">
            <span className="text-caption text-stone">Cameras</span>
            <CodeInline>{cameras.join(", ")}</CodeInline>
          </span>
        )}
        {gopros.length > 0 && (
          <span className="flex items-center gap-xs">
            <span className="text-caption text-stone">GoPros</span>
            <CodeInline>{gopros.join(", ")}</CodeInline>
          </span>
        )}
      </Card>

      {(cameras.length > 0 || gopros.length > 0) && sessionState !== "review" && (
        previewEnabled ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-md mb-md">
            {[...cameras, ...gopros].map((cam) => (
              <CameraPreview key={cam} camName={cam} />
            ))}
          </div>
        ) : (
          <Card className="mb-md text-stone text-body-sm text-center py-md">
            ライブプレビューはこのセッションでは無効化されています
          </Card>
        )
      )}

      {teleop === "web_keyboard" && (
        <div className="mb-md">
          <KeyboardTeleop enabled={sessionState !== "review"} />
        </div>
      )}

      <div className="mb-md">
        <EEMonitor enabled />
      </div>

      {robot === "rebotarm" && (
        <div className="mb-md">
          <EStopButton />
        </div>
      )}

      <div className="mb-md">
        <IdlePoseCaptureButton />
      </div>

      <RecordingControls />
    </div>
  );
}
