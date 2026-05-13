import { useEffect, useRef, useState } from "react";
import { useSessionStore } from "../state/session-store.ts";
import { useEndSession, useEpisodes, useSessionState } from "../api/queries.ts";
import { WsConnection } from "../api/ws.ts";
import SessionConfigForm from "../components/SessionConfigForm.tsx";
import CameraPreview from "../components/CameraPreview.tsx";
import RecordingControls from "../components/RecordingControls.tsx";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { PageHeader } from "../components/ui/page-header";
import { Badge } from "../components/ui/badge";
import { InstrumentWell } from "../components/ui/instrument-well";
import { Sparkline } from "../components/ui/sparkline";
import { useJointHistory } from "../hooks/useJointHistory";
import { SectionMark } from "../components/ui/section-mark";
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

  const inProgressIndex = (episodes?.length ?? 0) + 1;

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
        {/* Right rail spans both rows — telemetry */}
        <aside className="row-span-2 flex flex-col gap-sm min-h-0">
          <JointBlock enabled />
          <EEBlock enabled />
        </aside>
        {/* Row 2, col 1 — episode progress */}
        <EpisodeProgressBlock inProgressIndex={inProgressIndex} />
        {/* Row 2, col 2 — xy trajectory */}
        <XYPlot />
      </div>

      {/* Controls bar */}
      <div className="border-t border-hairline bg-canvas px-xl py-2 flex items-center gap-3 flex-shrink-0 min-h-[52px]">
        <span className="font-mono text-caption text-steel">
          capturing episode <span className="text-ink">{inProgressIndex}</span>
        </span>
        <span className="w-px h-5 bg-hairline" />
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

function EpisodeProgressBlock({
  inProgressIndex,
}: {
  inProgressIndex: number;
}) {
  const progress = useSessionStore((s) => s.episodeProgress);
  const fps = useSessionStore((s) => s.fps);

  // Derive elapsed from frames / fps (the backend doesn't ship an explicit
  // elapsed_sec — keep this consistent with the top-bar RecBadge).
  const elapsedSec =
    progress && fps && fps > 0 ? progress.num_frames / fps : 0;
  const m = Math.floor(elapsedSec / 60).toString().padStart(2, "0");
  const s = Math.floor(elapsedSec % 60).toString().padStart(2, "0");

  return (
    <section className="bg-canvas border border-hairline rounded-md p-md flex flex-col">
      <header className="mb-2 flex items-baseline justify-between">
        <SectionMark code="§02.B" name="episode progress" />
        <span className="font-mono text-micro text-stone">
          capturing ep <span className="text-ink">{inProgressIndex}</span>
        </span>
      </header>
      <div className="flex items-baseline gap-2">
        <span className="text-heading-2 font-semibold tracking-tight tabular-nums">
          {m}:{s}
        </span>
        <span className="text-caption text-steel">elapsed</span>
      </div>
      <div className="grid grid-cols-3 gap-x-md gap-y-1 mt-md text-caption">
        <Cell k="Frames" v={progress?.num_frames ?? "—"} mono />
        <Cell k="FPS tgt." v={fps?.toFixed(2) ?? "—"} mono tone="ok" />
        <Cell k="Ticks skipped" v={progress?.ticks_skipped ?? 0} mono />
        <Cell
          k="Writer lag"
          v={
            typeof progress?.writer_lag_ms === "number"
              ? `${progress.writer_lag_ms.toFixed(0)} ms`
              : "—"
          }
          mono
          tone={(progress?.writer_lag_ms ?? 0) > 50 ? "warn" : "ok"}
        />
        <Cell
          k="Queue"
          v={progress?.writer_queue_depth ?? 0}
          mono
          tone={(progress?.writer_queue_depth ?? 0) > 5 ? "warn" : "ok"}
        />
        <Cell k="Stale samples" v={progress?.stale_sample_count ?? 0} mono />
      </div>
    </section>
  );
}

function Cell({
  k,
  v,
  mono,
  tone,
}: {
  k: string;
  v: React.ReactNode;
  mono?: boolean;
  tone?: "ok" | "warn";
}) {
  const color =
    tone === "ok"
      ? "text-brand-green-deep"
      : tone === "warn"
      ? "text-brand-warn"
      : "text-ink";
  return (
    <>
      <span className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
        {k}
      </span>
      <span
        className={
          (mono ? "font-mono text-caption tabular-nums " : "text-caption ") + color
        }
      >
        {String(v)}
      </span>
    </>
  );
}

function JointBlock({ enabled }: { enabled: boolean }) {
  // Initial hint; the hook adapts to the actual sample length on the first
  // WS message and re-allocates buffers if joint count grows.
  const NUM_JOINTS_HINT = 7;
  const history = useJointHistory(enabled, NUM_JOINTS_HINT);
  const numJoints = history.length;
  const latest = (i: number) => {
    const s = history[i];
    return s && s.length > 0 ? s[s.length - 1] : null;
  };

  return (
    <section className="flex-[1.4] min-h-0 bg-canvas border border-hairline rounded-md p-md flex flex-col">
      <header className="mb-xs flex items-baseline gap-xs">
        <SectionMark code="§02.B" name="joint positions" />
        <span className="font-mono text-micro text-stone">rad · 100 Hz</span>
      </header>
      <table className="w-full text-caption">
        <tbody>
          {Array.from({ length: numJoints }).map((_, i) => {
            const v = latest(i);
            return (
              <tr key={i} className="border-b border-dashed border-hairline-soft last:border-b-0">
                <td className="py-1 font-mono text-micro text-steel w-[36px]">J{i + 1}</td>
                <td className="py-1 text-right font-mono text-caption text-ink tabular-nums w-[80px]">
                  {v === null ? "—" : v.toFixed(4)}
                </td>
                <td className="py-1 pl-3">
                  <Sparkline data={history[i] ?? []} tone="ok" />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

interface EeSnapshot {
  pos: number[] | null;
  rotvec: number[] | null;
}

function EEBlock({ enabled }: { enabled: boolean }) {
  const [snap, setSnap] = useState<EeSnapshot>({ pos: null, rotvec: null });
  const connRef = useRef<WsConnection | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const conn = new WsConnection("/ws/state");
    connRef.current = conn;
    conn.onMessage((msg) => {
      const m = msg as { ee_pos?: number[]; ee_rotvec?: number[] };
      setSnap((prev) => ({
        pos: m.ee_pos ?? prev.pos,
        rotvec: m.ee_rotvec ?? prev.rotvec,
      }));
    });
    conn.connect();
    return () => {
      conn.disconnect();
      connRef.current = null;
    };
  }, [enabled]);

  const fmt = (n: number | undefined, d = 4) =>
    typeof n === "number" ? n.toFixed(d) : "—";

  const rows: [string, string, string][] = [
    ["X", fmt(snap.pos?.[0]), "m"],
    ["Y", fmt(snap.pos?.[1]), "m"],
    ["Z", fmt(snap.pos?.[2]), "m"],
    ["rx", fmt(snap.rotvec?.[0], 3), "rad"],
    ["ry", fmt(snap.rotvec?.[1], 3), "rad"],
    ["rz", fmt(snap.rotvec?.[2], 3), "rad"],
  ];

  return (
    <section className="flex-1 min-h-0 bg-canvas border border-hairline rounded-md p-md flex flex-col">
      <header className="mb-xs">
        <SectionMark code="§02.B" name="end-effector pose" />
      </header>
      <table className="w-full text-caption">
        <tbody>
          {rows.map(([k, v, u]) => (
            <tr key={k} className="border-b border-dashed border-hairline-soft last:border-b-0">
              <td className="py-1 font-mono text-micro text-steel w-[44px]">{k}</td>
              <td className="py-1 text-right font-mono text-caption text-ink tabular-nums w-[80px]">{v}</td>
              <td className="py-1 pl-2 font-mono text-micro text-stone">{u}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function XYPlot() {
  // TODO follow-up: add a rolling EE XY buffer hook similar to useJointHistory.
  // For now, render the well with an empty-state grid so the visual lands.
  return (
    <InstrumentWell
      header="EE · XY TRAJECTORY · LAST 8 s"
      live
    >
      <svg viewBox="0 0 360 110" preserveAspectRatio="none" className="w-full h-full">
        <defs>
          <pattern id="xy-grid" width="24" height="22" patternUnits="userSpaceOnUse">
            <path d="M 24 0 L 0 0 0 22" fill="none" stroke="var(--color-hairline-dark)" strokeWidth="0.5" />
          </pattern>
        </defs>
        <rect width="360" height="110" fill="url(#xy-grid)" />
        {/* Empty — wired up in follow-up */}
      </svg>
    </InstrumentWell>
  );
}
