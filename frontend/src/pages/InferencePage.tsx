import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { useInferenceStore } from "../state/inference-store";
import { useSessionStore } from "../state/session-store";
import { subscribeInferenceWS } from "../api/inference";
import { Badge } from "../components/ui/badge";
import { PageHeader } from "../components/ui/page-header";
import { SessionColumn } from "../components/inference/SessionColumn";
import { CameraColumn } from "../components/inference/CameraColumn";
import { TelemetryColumn } from "../components/inference/TelemetryColumn";
import { PhaseActionBar } from "../components/inference/PhaseActionBar";

export function InferencePage() {
  const s = useInferenceStore();
  const sessionState = useSessionStore((x) => x.state);
  const sessionRobot = useSessionStore((x) => x.robot);
  const sessionMode = useSessionStore((x) => x.mode);
  const wsCleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    s.loadConfigs();
    s.rehydrateFromBackend();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (s.phase === "pre-start") {
      wsCleanupRef.current?.();
      wsCleanupRef.current = null;
      return;
    }
    if (wsCleanupRef.current) return;
    wsCleanupRef.current = subscribeInferenceWS((e) => s.handleEvent(e));
    return () => {
      wsCleanupRef.current?.();
      wsCleanupRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.phase]);

  const isLive = s.phase === "ready" || s.phase === "recording";
  const sessionReadyForInference =
    sessionState === "ready" && sessionMode !== "inference";
  const sessionBlocker: string | null = (() => {
    if (sessionState === "idle") return "no-session";
    if (sessionState === "recording") return "recording";
    if (sessionState === "review") return "review";
    if (sessionMode === "inference") return "already-inference";
    return null;
  })();

  return (
    <>
      <PageHeader
        code="§03"
        title={
          <span className="flex items-baseline gap-md">
            Inference
            {isLive && <Badge variant="success">● live</Badge>}
          </span>
        }
        meta={
          sessionRobot && (
            <span className="font-mono text-micro text-stone">
              robot {sessionRobot}{sessionMode && ` · mode ${sessionMode}`}
            </span>
          )
        }
      />

      <div className="flex-1 flex flex-col min-h-0">
        {/* Error banner + session blockers (above 3-column area) */}
        {(s.error || (sessionBlocker && s.phase === "pre-start")) && (
          <div className="flex-shrink-0 px-md pt-sm space-y-2">
            {s.error && (
              <div className="rounded-md border border-brand-error/30 bg-brand-error/10 p-3 flex items-start justify-between gap-3">
                <div className="text-sm text-brand-error break-words">{s.error}</div>
                <button
                  onClick={() => s.setError(null)}
                  className="text-brand-error hover:text-brand-error text-lg leading-none"
                  aria-label="dismiss"
                >
                  ×
                </button>
              </div>
            )}
            {sessionBlocker && s.phase === "pre-start" && (
              <div className="rounded-md border border-brand-warn/30 bg-brand-warn/10 p-3 text-sm text-brand-warn">
                <SessionBlockerMessage kind={sessionBlocker} />
              </div>
            )}
          </div>
        )}

        {/* 3-column body */}
        <div className="flex-1 flex min-h-0">
          <SessionColumn disabled={s.phase === "pre-start" && !sessionReadyForInference} />
          <CameraColumn />
          <TelemetryColumn />
        </div>

        <PhaseActionBar canStartSession={sessionReadyForInference} />
      </div>
    </>
  );
}

function SessionBlockerMessage({ kind }: { kind: string }) {
  return (
    <div>
      <div className="font-medium mb-1">
        {kind === "no-session" && "⚠ No active session"}
        {kind === "recording" && "⚠ Session is recording"}
        {kind === "review" && "⚠ Session is in review"}
        {kind === "already-inference" && "⚠ Already in inference mode"}
      </div>
      <div>
        {kind === "no-session" && (
          <>
            The inference pipeline runs on top of an active robot session. Open the{" "}
            <Link to="/record" className="underline font-medium">Record page</Link> first
            to load a robot adapter, then come back here.
          </>
        )}
        {(kind === "recording" || kind === "review") && (
          <>
            Stop the current episode on the{" "}
            <Link to="/record" className="underline font-medium">Record page</Link> before
            starting an inference session.
          </>
        )}
        {kind === "already-inference" && (
          <>The page is rehydrating from the backend — refresh if it stays stuck.</>
        )}
      </div>
    </div>
  );
}
