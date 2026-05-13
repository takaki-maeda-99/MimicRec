import { useParams, Link, useNavigate } from "react-router-dom";
import { useEpisodes, useDeleteEpisode } from "../api/queries";
import { Button } from "../components/ui/button";
import { CodeInline } from "../components/ui/code-inline";
import { PageHeader } from "../components/ui/page-header";

export default function EpisodesPage() {
  const { ds } = useParams<{ ds: string }>();
  const { data: episodes, isLoading } = useEpisodes(ds || "");
  const deleteMutation = useDeleteEpisode(ds || "");
  const navigate = useNavigate();

  if (!ds) return <div className="p-xl">No dataset selected</div>;

  return (
    <>
      <PageHeader
        code="§01.B"
        title={
          <span className="flex items-baseline gap-md">
            Episodes
            <span className="text-steel">·</span>
            <CodeInline>{ds}</CodeInline>
          </span>
        }
        actions={
          <Link to="/datasets" className="text-caption text-steel hover:text-ink">
            ← Datasets
          </Link>
        }
      />
      <div className="flex-1 overflow-auto">
        <div className="max-w-[1240px] mx-auto px-xl py-xl">
          {isLoading ? (
            <p className="text-steel">Loading...</p>
          ) : !episodes?.length ? (
            <p className="text-steel">No episodes recorded yet.</p>
          ) : (
            <table className="w-full text-body-sm">
              <thead>
                <tr className="border-b border-hairline text-left text-stone text-micro-uppercase uppercase tracking-[0.18em] font-semibold">
                  <th className="pb-sm">#</th>
                  <th className="pb-sm">Task</th>
                  <th className="pb-sm">Duration</th>
                  <th className="pb-sm">Frames</th>
                  <th className="pb-sm">Success</th>
                  <th className="pb-sm">Mode</th>
                  <th className="pb-sm">Recorded</th>
                  <th className="pb-sm"></th>
                </tr>
              </thead>
              <tbody>
                {episodes.map((ep) => (
                  <tr
                    key={ep.episode_index}
                    className="border-b border-hairline-soft hover:bg-surface-soft cursor-pointer transition-colors group"
                    onClick={() =>
                      navigate(`/datasets/${ds}/episodes/${ep.episode_index}/replay`)
                    }
                    title={`Open replay for episode #${ep.display_index}`}
                  >
                    <td className="py-md font-mono text-caption text-ink tabular-nums">
                      {ep.display_index}
                    </td>
                    <td className="py-md text-slate">{ep.task}</td>
                    <td className="py-md font-mono text-caption text-slate tabular-nums">
                      {ep.duration_sec.toFixed(1)}s
                    </td>
                    <td className="py-md font-mono text-caption text-slate tabular-nums">
                      {ep.num_frames}
                    </td>
                    <td className="py-md">
                      {ep.success === true && (
                        <span className="text-brand-green-deep">Success</span>
                      )}
                      {ep.success === false && (
                        <span className="text-brand-error">Failure</span>
                      )}
                      {ep.success === null && <span className="text-stone">—</span>}
                    </td>
                    <td className="py-md text-slate">{ep.mode}</td>
                    <td className="py-md text-steel text-caption font-mono">
                      {ep.recorded_at || "—"}
                    </td>
                    <td
                      className="py-md text-right"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Button
                        variant="destructive"
                        size="xs"
                        onClick={() => {
                          if (confirm(`Delete episode #${ep.display_index}?`)) {
                            deleteMutation.mutate(ep.episode_index);
                          }
                        }}
                      >
                        Delete
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  );
}
