import { useParams, Link } from "react-router-dom";
import { useEpisodes, useReplayStart, useReplayStop } from "../api/queries";
import { useSessionStore } from "../state/session-store";
import VideoPlayer from "../components/VideoPlayer";
import JointPlot from "../components/JointPlot";
import EndEffectorPlot from "../components/EndEffectorPlot";
import SubtaskAnnotator from "../components/SubtaskAnnotator";
import SubtaskTimeline from "../components/SubtaskTimeline";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { PageHeader } from "../components/ui/page-header";

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
      />
      <div className="flex-1 overflow-auto">
        <div className="max-w-[1100px] mx-auto px-xl py-xl">

          {/* Replay controls */}
          <div className="flex items-center justify-between mb-md">
            <Link to={`/datasets/${ds}/episodes`} className="text-caption text-stone hover:text-ink">
              &larr; Episodes — {ds}
            </Link>
            <div className="flex items-center gap-md">
              {subState === "replaying" ? (
                <>
                  <Button
                    className="!bg-brand-error !text-on-dark hover:!bg-brand-error/90"
                    onClick={() => replayStop.mutate()}
                  >
                    Stop Replay
                  </Button>
                  {replayProgress && (
                    <span className="text-body-sm text-slate">
                      Frame {replayProgress.frame_index} / {replayProgress.total_frames}
                    </span>
                  )}
                </>
              ) : (
                <Button
                  onClick={() => replayStart.mutate({ dataset: ds, episode_idx: episodeIdx })}
                  disabled={sessionState !== "ready" || replayStart.isPending}
                >
                  {sessionState !== "ready"
                    ? "Start a session first"
                    : replayStart.isPending
                    ? "Starting..."
                    : "▶ Replay on Robot"}
                </Button>
              )}
            </div>
          </div>

          {/* Metadata strip — horizontal header */}
          {episode && (
            <div className="flex flex-wrap items-center gap-x-lg gap-y-xs mb-lg pb-md border-b border-hairline-soft text-body-sm">
              <MetaItem label="Task" value={episode.task} />
              <MetaItem label="Duration" value={`${episode.duration_sec.toFixed(1)}s`} />
              <MetaItem label="Frames" value={String(episode.num_frames)} />
              <MetaItem
                label="Success"
                value={episode.success === true ? "Yes" : episode.success === false ? "No" : "—"}
                color={
                  episode.success === true ? "text-brand-green-deep" :
                  episode.success === false ? "text-brand-error" : "text-stone"
                }
              />
              <MetaItem label="Mode" value={episode.mode} />
              <MetaItem label="Robot" value={episode.robot} />
            </div>
          )}

          {replayStart.isError && (
            <p className="text-brand-error text-body-sm mb-md">
              {(replayStart.error as Error).message}
            </p>
          )}

          {/* Video grid — fixed square thumbnails */}
          <Card className="mb-md">
            <h3 className="text-heading-5 text-ink mb-md">Video</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-md max-w-4xl">
              {(episode?.cameras || ["front"]).map((cam: string) => (
                <VideoPlayer key={cam} ds={ds} idx={episodeIdx} cam={cam} />
              ))}
            </div>
          </Card>

          {/* Joint angle plot */}
          <Card className="mb-md">
            <h3 className="text-heading-5 text-ink mb-md">Joint trajectory</h3>
            <JointPlot ds={ds} idx={episodeIdx} />
          </Card>

          {/* End-effector plot */}
          <Card className="mb-md">
            <h3 className="text-heading-5 text-ink mb-md">End-Effector</h3>
            <EndEffectorPlot ds={ds} idx={episodeIdx} />
          </Card>

          {/* Subtask timeline */}
          <Card className="mb-md">
            <h3 className="text-heading-5 text-ink mb-md">Subtask Timeline</h3>
            <SubtaskTimeline ds={ds} idx={episodeIdx} />
          </Card>

          {/* Subtask annotation */}
          <Card>
            <h3 className="text-heading-5 text-ink mb-md">Subtask Annotation</h3>
            <SubtaskAnnotator ds={ds} idx={episodeIdx} cameras={episode?.cameras || ["front"]} />
          </Card>

        </div>
      </div>
    </>
  );
}

function MetaItem({
  label,
  value,
  color = "text-ink",
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="flex items-baseline gap-1">
      <span className="text-caption-bold text-steel uppercase tracking-[0.5px]">{label}</span>
      <span className={`text-body-sm-medium ${color}`}>{value}</span>
    </div>
  );
}
