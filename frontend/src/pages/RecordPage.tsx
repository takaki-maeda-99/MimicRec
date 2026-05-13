import { useEffect, useState } from "react";
import { useSessionStore } from "../state/session-store.ts";
import { useEndSession, useEpisodes, useSessionState } from "../api/queries.ts";
import { WsConnection } from "../api/ws.ts";
import SessionConfigForm from "../components/SessionConfigForm.tsx";
import CameraPreview from "../components/CameraPreview.tsx";
import RecordingControls from "../components/RecordingControls.tsx";
import KeyboardTeleop from "../components/KeyboardTeleop.tsx";
import EEMonitor from "../components/EEMonitor.tsx";
import IdlePoseCaptureButton from "../components/IdlePoseCaptureButton.tsx";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { PageHeader } from "../components/ui/page-header";
import { Badge } from "../components/ui/badge";
import { InstrumentWell } from "../components/ui/instrument-well";
import type { EpisodeProgress, ReplayProgress } from "../api/types.ts";

function RecBadge({ elapsedSec }: { elapsedSec: number }) {
  const m = Math.floor(elapsedSec / 60).toString().padStart(2, "0");
  const s = Math.floor(elapsedSec % 60).toString().padStart(2, "0");
  return (
    <span className="inline-flex items-center gap-2 px-2.5 py-1 rounded-sm border border-brand-error/40 bg-brand-error/10 text-brand-error font-mono text-micro tracking-[0.08em]">
      <span className="w-1.5 h-1.5 rounded-full bg-brand-error animate-pulse" />
      REC {m}:{s}
    </span>
  );
}

/**
 * Detect whether the viewport is large enough for the no-scroll RecordPage
 * layout (width ≥ 1280 AND height ≥ 900). Tailwind's `max-[Xpx]:` only
 * targets width, so we resolve this in JS and conditionally apply classes.
 */
function useFitsRecordViewport() {
  const [fits, setFits] = useState(() =>
    typeof window === "undefined"
      ? true
      : window.innerWidth >= 1280 && window.innerHeight >= 900,
  );
  useEffect(() => {
    const check = () =>
      setFits(window.innerWidth >= 1280 && window.innerHeight >= 900);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);
  return fits;
}

export default function RecordPage() {
  const sessionState = useSessionStore((s) => s.state);
  // Pre-wired for task 25 (review-mode display).
  const _subState = useSessionStore((s) => s.subState);
  void _subState;
  const cameras = useSessionStore((s) => s.cameras);
  const gopros = useSessionStore((s) => s.gopros);
  const previewEnabled = useSessionStore((s) => s.previewEnabled);
  const dataset = useSessionStore((s) => s.dataset);
  const task = useSessionStore((s) => s.task);
  const robot = useSessionStore((s) => s.robot);
  const teleop = useSessionStore((s) => s.teleop);
  const mode = useSessionStore((s) => s.mode);
  const fps = useSessionStore((s) => s.fps);
  const progress = useSessionStore((s) => s.episodeProgress);
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
      if (msgType === "episode_progress") setEpisodeProgress(msgData as unknown as EpisodeProgress);
      if (msgType === "replay_progress") setReplayProgress(msgData as unknown as ReplayProgress);
      if (msgType === "error")
        setError(msgData as unknown as { error: string; message: string });
    });
    conn.connect();
    return () => conn.disconnect();
  }, [isIdle, setSessionState, setEpisodeProgress, setReplayProgress, setError]);

  // CRITICAL — hooks must be called unconditionally and in the same order
  // every render. `useFitsRecordViewport` lives BEFORE the idle-branch
  // early return below; the value is unused in the idle branch but the
  // hook still runs (Rules of Hooks compliance).
  const fits = useFitsRecordViewport();

  // Idle branch
  if (sessionState === "idle") {
    return (
      <>
        <PageHeader code="§02" title="Configure session" />
        <div className="p-xl overflow-auto">
          <Card variant="feature">
            <SessionConfigForm onStarted={() => {}} />
          </Card>
        </div>
      </>
    );
  }

  // EpisodeProgress only carries num_frames + writer counters
  // (frontend/src/api/types.ts:43-49). Derive elapsed from frames / fps;
  // when fps is unknown, fall back to showing —.
  const elapsedSec =
    progress && fps && fps > 0 ? progress.num_frames / fps : 0;

  // Merge cameras + gopros so GoPro previews are included in the two cells.
  const previewSources = [...cameras, ...gopros];

  return (
    <>
      <PageHeader
        code="§02"
        title={
          task ? (
            <>
              Live capture <span className="text-steel">— {task}</span>
            </>
          ) : (
            "Live capture"
          )
        }
        state={
          sessionState === "recording" ? (
            <RecBadge elapsedSec={elapsedSec} />
          ) : (
            <Badge variant="outline">{sessionState}</Badge>
          )
        }
        actions={
          <Button variant="secondary" size="sm" onClick={() => endSession.mutate()}>
            End session
          </Button>
        }
      />

      {/* Brief strip (one row, key-value pills) */}
      <div className="flex flex-wrap items-center gap-md px-xl py-2 border-b border-hairline bg-canvas text-caption flex-shrink-0">
        <Brief k="Dataset" v={dataset ?? "—"} mono />
        <Brief k="Robot" v={robot ?? "—"} />
        <Brief k="Mode" v={mode ?? "—"} />
        <Brief k="Teleop" v={teleop ?? "—"} />
        <Brief k="Cameras" v={[...cameras, ...gopros].join(" · ") || "—"} mono />
        <Brief k="Episodes" v={`${episodes?.length ?? 0} saved`} />
      </div>

      {/* Body grid — placeholders for now; subsequent tasks slot real
          InstrumentWell / telemetry rail / episode progress / xy plot.
          Viewport-fit is detected in JS (`useFitsRecordViewport`) because
          Tailwind's max-[Xpx]: only targets width — we need width *and*
          height. */}
      <div
        className={
          "flex-1 min-h-0 p-xl grid gap-sm " +
          (fits
            ? "grid-cols-[1fr_1fr_380px] grid-rows-[1.35fr_1fr] overflow-hidden"
            : "grid-cols-1 overflow-auto")
        }
      >
        {/* Row 1, col 1 — cam 01 */}
        <InstrumentWell
          header={`CAM · 01 · ${previewSources[0] ?? "—"}`}
          live={!!previewSources[0] && previewEnabled}
          caption={
            previewSources[0] && (
              <div className="flex justify-between">
                <span>{cameras.includes(previewSources[0]) ? "fixed" : "gopro"}</span>
                <span className="font-mono text-brand-green">live</span>
              </div>
            )
          }
        >
          {previewSources[0] && previewEnabled ? (
            <CameraPreview camName={previewSources[0]} />
          ) : (
            <div className="grid place-items-center h-full text-on-dark-dim">no stream</div>
          )}
        </InstrumentWell>

        {/* Row 1, col 2 — cam 02 */}
        <InstrumentWell
          header={`CAM · 02 · ${previewSources[1] ?? "—"}`}
          live={!!previewSources[1] && previewEnabled}
          caption={
            previewSources[1] && (
              <div className="flex justify-between">
                <span>{cameras.includes(previewSources[1]) ? "wrist" : "gopro"}</span>
                <span className="font-mono text-brand-green">live</span>
              </div>
            )
          }
        >
          {previewSources[1] && previewEnabled ? (
            <CameraPreview camName={previewSources[1]} />
          ) : (
            <div className="grid place-items-center h-full text-on-dark-dim">no stream</div>
          )}
        </InstrumentWell>
        {/* Right rail spans both rows — telemetry placeholder */}
        <div className="row-span-2 bg-canvas border border-hairline rounded-md p-md flex flex-col gap-md">
          <div className="text-caption text-steel">telemetry (placeholder)</div>
          <EEMonitor enabled />
          {teleop === "web_keyboard" && (
            <KeyboardTeleop enabled={sessionState !== "review"} />
          )}
          <IdlePoseCaptureButton />
        </div>
        {/* Row 2, col 1 — episode progress placeholder */}
        <div className="bg-canvas border border-hairline rounded-md p-md text-caption text-steel">
          episode progress (placeholder)
        </div>
        {/* Row 2, col 2 — xy plot placeholder */}
        <div className="bg-canvas-dark rounded-md min-h-[140px] grid place-items-center text-on-dark-dim text-caption">
          xy trajectory (placeholder)
        </div>
      </div>

      {/* Controls bar */}
      <div className="border-t border-hairline bg-canvas px-xl py-2 flex items-center gap-2 flex-shrink-0">
        <RecordingControls />
      </div>
    </>
  );
}

function Brief({ k, v, mono }: { k: string; v: React.ReactNode; mono?: boolean }) {
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
        {k}
      </span>
      <span className={mono ? "font-mono text-caption text-ink" : "text-ink"}>{v}</span>
    </span>
  );
}
