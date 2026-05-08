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
    <div>
      <header className="flex items-center justify-between pb-sm mb-lg border-b border-hairline">
        <div>
          <Link to={`/datasets/${ds}/episodes`} className="text-caption text-stone hover:text-ink">
            &larr; Episodes — {ds}
          </Link>
          <h2 className="mt-1 text-heading-3 text-ink">Episode {idx}</h2>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-lg mb-md">
        {/* Metadata panel */}
        <Card>
          <h3 className="text-heading-5 text-ink mb-md">Metadata</h3>
          {episode ? (
            <dl className="space-y-2 text-body-sm">
              <div className="flex justify-between">
                <dt className="text-steel">Task</dt>
                <dd className="text-ink font-medium">{episode.task}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-steel">Duration</dt>
                <dd className="text-ink font-medium">{episode.duration_sec.toFixed(1)}s</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-steel">Frames</dt>
                <dd className="text-ink font-medium">{episode.num_frames}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-steel">Success</dt>
                <dd className="text-ink font-medium">
                  {episode.success === true ? "Yes" : episode.success === false ? "No" : "—"}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-steel">Mode</dt>
                <dd className="text-ink font-medium">{episode.mode}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-steel">Robot</dt>
                <dd className="text-ink font-medium">{episode.robot}</dd>
              </div>
            </dl>
          ) : (
            <p className="text-stone">Loading...</p>
          )}
        </Card>

        {/* Video + replay controls */}
        <div className="lg:col-span-2 space-y-xl">
          {/* Video players */}
          <Card>
            <h3 className="text-heading-5 text-ink mb-md">Video</h3>
            <div className="space-y-md">
              {(episode?.cameras || ["front"]).map((cam: string) => (
                <VideoPlayer key={cam} ds={ds} idx={episodeIdx} cam={cam} />
              ))}
            </div>
          </Card>

          {/* Replay controls */}
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
                  : "Replay on Robot"}
              </Button>
            )}
          </div>
          {replayStart.isError && (
            <p className="text-brand-error text-body-sm">{(replayStart.error as Error).message}</p>
          )}
        </div>
      </div>

      {/* Subtask timeline */}
      <Card className="mb-md">
        <h3 className="text-heading-5 text-ink mb-md">Subtask Timeline</h3>
        <SubtaskTimeline ds={ds} idx={episodeIdx} />
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

      {/* Subtask annotation */}
      <Card>
        <h3 className="text-heading-5 text-ink mb-md">Subtask Annotation</h3>
        <SubtaskAnnotator ds={ds} idx={episodeIdx} cameras={episode?.cameras || ["front"]} />
      </Card>
    </div>
  );
}
