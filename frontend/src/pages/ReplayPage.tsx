import { useParams, Link } from "react-router-dom";
import { useEpisodes, useReplayStart, useReplayStop } from "../api/queries";
import { useSessionStore } from "../state/session-store";
import VideoPlayer from "../components/VideoPlayer";
import JointPlot from "../components/JointPlot";

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
    <div className="p-6 max-w-5xl">
      <div className="mb-6">
        <Link to={`/datasets/${ds}/episodes`} className="text-sm text-gray-500 hover:text-gray-700">
          &larr; Episodes — {ds}
        </Link>
        <h2 className="text-2xl font-bold mt-1">Episode {idx}</h2>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Metadata panel */}
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <h3 className="text-sm font-medium text-gray-500 mb-3">Metadata</h3>
          {episode ? (
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-gray-500">Task</dt>
                <dd className="font-medium">{episode.task}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Duration</dt>
                <dd className="font-medium">{episode.duration_sec.toFixed(1)}s</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Frames</dt>
                <dd className="font-medium">{episode.num_frames}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Success</dt>
                <dd className="font-medium">
                  {episode.success === true ? "Yes" : episode.success === false ? "No" : "—"}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Mode</dt>
                <dd className="font-medium">{episode.mode}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Robot</dt>
                <dd className="font-medium">{episode.robot}</dd>
              </div>
            </dl>
          ) : (
            <p className="text-gray-400">Loading...</p>
          )}
        </div>

        {/* Video + replay controls */}
        <div className="lg:col-span-2 space-y-4">
          {/* Video players — show cameras that were used in this episode */}
          <div className="space-y-4">
            {(episode?.cameras || ["front"]).map((cam: string) => (
              <VideoPlayer key={cam} ds={ds} idx={episodeIdx} cam={cam} />
            ))}
          </div>

          {/* Replay controls */}
          <div className="flex items-center gap-4">
            {subState === "replaying" ? (
              <>
                <button
                  className="bg-red-600 text-white px-6 py-2 rounded-md font-medium hover:bg-red-700"
                  onClick={() => replayStop.mutate()}
                >
                  Stop Replay
                </button>
                {replayProgress && (
                  <span className="text-sm text-gray-600">
                    Frame {replayProgress.frame_index} / {replayProgress.total_frames}
                  </span>
                )}
              </>
            ) : (
              <button
                className="bg-blue-600 text-white px-6 py-2 rounded-md font-medium hover:bg-blue-700 disabled:opacity-50"
                onClick={() => replayStart.mutate({ dataset: ds, episode_idx: episodeIdx })}
                disabled={sessionState !== "ready" || replayStart.isPending}
              >
                {sessionState !== "ready"
                  ? "Start a session first"
                  : replayStart.isPending
                  ? "Starting..."
                  : "Replay on Robot"}
              </button>
            )}
          </div>
          {replayStart.isError && (
            <p className="text-red-600 text-sm">{(replayStart.error as Error).message}</p>
          )}
        </div>
      </div>

      {/* Joint angle plot */}
      <div className="mt-8 bg-white rounded-lg border border-gray-200 p-4">
        <h3 className="text-sm font-medium text-gray-500 mb-3">Joint Data</h3>
        <JointPlot ds={ds} idx={episodeIdx} />
      </div>
    </div>
  );
}
