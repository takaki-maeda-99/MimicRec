import { useMemo, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import { useEpisodes, useReplayStart, useReplayStop } from "../api/queries";
import { useSessionStore } from "../state/session-store";
import VideoPlayer from "../components/VideoPlayer";
import JointPlot from "../components/JointPlot";
import EndEffectorPlot from "../components/EndEffectorPlot";
import { Scrubber } from "../components/Scrubber";
import { Button } from "../components/ui/button";
import { PageHeader } from "../components/ui/page-header";
import { useEpisodeTimeline } from "../hooks/useEpisodeTimeline";
import { useSecondaryVideoSync } from "../hooks/useSecondaryVideoSync";

export default function ReplayPage() {
  const { ds, idx } = useParams<{ ds: string; idx: string }>();
  const episodeIdx = Number(idx);
  const { data: episodes } = useEpisodes(ds || "");
  const episode = episodes?.find((e) => e.episode_index === episodeIdx);
  const replayStart = useReplayStart();
  const replayStop = useReplayStop();
  const sessionState = useSessionStore((s) => s.state);
  const subState = useSessionStore((s) => s.subState);
  const replayProgress = useSessionStore((s) => s.replayProgress);

  const allCameras = episode?.cameras ?? ["front"];
  // Hard cap: master + 3 secondaries = 4 total. If a session exposes more, we
  // only render 4 and drop the rest (rather than rendering unsynced extras that
  // are forced into the no-controls state). Most adapters expose ≤ 2 cameras.
  const cameras = allCameras.slice(0, 4);
  if (allCameras.length > 4) {
    // eslint-disable-next-line no-console
    console.warn(`Replay: ${allCameras.length} cameras present, only first 4 rendered (sync limit).`);
  }

  const masterRef = useRef<HTMLVideoElement>(null);
  const sec1Ref = useRef<HTMLVideoElement>(null);
  const sec2Ref = useRef<HTMLVideoElement>(null);
  const sec3Ref = useRef<HTMLVideoElement>(null);
  const secondaryRefs = [sec1Ref, sec2Ref, sec3Ref] as const;

  const { currentTimeSec, seek } = useEpisodeTimeline(masterRef);
  const fps = (episode?.num_frames ?? 1) / Math.max(0.001, episode?.duration_sec ?? 1);

  // Always call all 3 sync hooks (rules-of-hooks). Each hook no-ops when its
  // ref is null (no secondary at that slot).
  useSecondaryVideoSync(sec1Ref, masterRef, currentTimeSec, fps);
  useSecondaryVideoSync(sec2Ref, masterRef, currentTimeSec, fps);
  useSecondaryVideoSync(sec3Ref, masterRef, currentTimeSec, fps);

  const cursorFrameIdx = useMemo(
    () => Math.min(Math.round(currentTimeSec * fps), (episode?.num_frames ?? 1) - 1),
    [currentTimeSec, fps, episode?.num_frames],
  );

  if (!ds || !idx) return <div className="p-6">Invalid URL</div>;

  return (
    <>
      <PageHeader
        code="§01.C"
        title={
          <span className="flex items-baseline gap-md">
            Replay
            <span className="text-steel">·</span>
            <span className="font-mono text-caption text-ink">{ds} / ep {idx}</span>
          </span>
        }
        meta={episode && (
          <span className="font-mono text-micro text-stone">
            {episode.duration_sec.toFixed(1)}s · {episode.num_frames} frames
          </span>
        )}
      />

      {/* Control row */}
      <div className="flex-shrink-0 flex items-center gap-md px-xl py-sm border-b border-hairline bg-canvas">
        <Link to={`/datasets/${ds}/episodes`} className="text-caption text-stone hover:text-ink">
          ← Episodes
        </Link>
        <span className="text-hairline">|</span>
        {replayProgress && subState === "replaying" && (
          <span className="text-body-sm text-slate font-mono">
            HW replay {replayProgress.frame_index} / {replayProgress.total_frames}
          </span>
        )}
        <span className="flex-1" />
        {subState === "replaying" ? (
          <Button variant="destructive" onClick={() => replayStop.mutate()}>Stop Replay</Button>
        ) : (
          <Button
            onClick={() => replayStart.mutate({ dataset: ds, episode_idx: episodeIdx })}
            disabled={sessionState !== "ready" || replayStart.isPending}
          >
            {sessionState !== "ready"
              ? "Start a session first"
              : replayStart.isPending
              ? "Starting…"
              : "▶ Replay on Robot"}
          </Button>
        )}
      </div>

      {/* Meta strip */}
      {episode && (
        <div className="flex-shrink-0 flex flex-wrap items-baseline gap-x-lg gap-y-1 px-xl py-sm border-b border-hairline-soft bg-surface-soft text-body-sm">
          <MetaItem k="Task"     v={episode.task} />
          <MetaItem k="Duration" v={`${episode.duration_sec.toFixed(1)}s`} />
          <MetaItem k="Frames"   v={String(episode.num_frames)} />
          <MetaItem k="Success"  v={episode.success === true ? "Yes" : episode.success === false ? "No" : "—"}
                    color={episode.success === true ? "text-brand-green-deep" : episode.success === false ? "text-brand-error" : "text-stone"} />
          <MetaItem k="Mode"     v={episode.mode} />
          <MetaItem k="Robot"    v={episode.robot} />
        </div>
      )}

      {/* Body: left video / right plots */}
      <div className="flex-1 flex min-h-0 gap-sm p-sm">
        <div className="flex-[1.5] min-w-0 grid gap-sm" style={{ gridTemplateColumns: `repeat(${Math.min(cameras.length, 2)}, minmax(0, 1fr))` }}>
          {cameras.map((cam, i) => {
            const ref = i === 0 ? masterRef : (secondaryRefs[i - 1] ?? null);
            return (
              <VideoPlayer
                key={cam}
                ds={ds}
                idx={episodeIdx}
                cam={cam}
                isMaster={i === 0}
                ref={ref ?? undefined}
              />
            );
          })}
        </div>

        <div className="flex-1 min-w-0 flex flex-col gap-sm">
          <div className="flex-1 min-h-0 flex flex-col border border-hairline rounded-sm bg-canvas overflow-hidden">
            <div className="flex-shrink-0 px-md py-sm border-b border-hairline-soft text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold flex items-center justify-between">
              <span>Joint trajectory</span>
              <span className="font-mono text-[10px] text-muted">click to seek</span>
            </div>
            <div className="flex-1 min-h-0">
              <JointPlot ds={ds} idx={episodeIdx} cursorTimeSec={currentTimeSec} onSeek={seek} />
            </div>
          </div>
          <div className="flex-1 min-h-0 flex flex-col border border-hairline rounded-sm bg-canvas overflow-hidden">
            <div className="flex-shrink-0 px-md py-sm border-b border-hairline-soft text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
              End-Effector
            </div>
            <div className="flex-1 min-h-0">
              <EndEffectorPlot ds={ds} idx={episodeIdx} cursorFrameIdx={cursorFrameIdx} />
            </div>
          </div>
        </div>
      </div>

      <Scrubber
        durationSec={episode?.duration_sec ?? 0}
        currentTimeSec={currentTimeSec}
        onSeek={seek}
      />
    </>
  );
}

function MetaItem({ k, v, color = "text-ink" }: { k: string; v: string; color?: string }) {
  return (
    <div className="flex items-baseline gap-1">
      <span className="text-caption-bold text-steel uppercase tracking-[0.5px]">{k}</span>
      <span className={`text-body-sm-medium ${color}`}>{v}</span>
    </div>
  );
}
