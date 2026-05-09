import { useParams, Link, useNavigate } from "react-router-dom";
import { useEpisodes, useDeleteEpisode } from "../api/queries";
import { Button } from "../components/ui/button";
import { CodeInline } from "../components/ui/code-inline";

export default function EpisodesPage() {
  const { ds } = useParams<{ ds: string }>();
  const { data: episodes, isLoading } = useEpisodes(ds || "");
  const deleteMutation = useDeleteEpisode(ds || "");
  const navigate = useNavigate();

  if (!ds) return <div className="p-6">No dataset selected</div>;

  return (
    <div>
      <header className="flex items-center justify-between pb-sm mb-lg border-b border-hairline">
        <div>
          <Link to="/datasets" className="text-caption text-stone hover:text-ink">&larr; Datasets</Link>
          <h2 className="mt-1 text-heading-3 text-ink">Episodes — <CodeInline>{ds}</CodeInline></h2>
        </div>
      </header>

      {isLoading ? (
        <p className="text-steel">Loading...</p>
      ) : !episodes?.length ? (
        <p className="text-steel">No episodes recorded yet.</p>
      ) : (
        <table className="w-full text-body-sm">
          <thead>
            <tr className="border-b border-hairline text-left text-steel text-micro-uppercase uppercase tracking-[0.5px]">
              <th className="pb-sm font-semibold">#</th>
              <th className="pb-sm font-semibold">Task</th>
              <th className="pb-sm font-semibold">Duration</th>
              <th className="pb-sm font-semibold">Frames</th>
              <th className="pb-sm font-semibold">Success</th>
              <th className="pb-sm font-semibold">Mode</th>
              <th className="pb-sm font-semibold">Recorded</th>
              <th className="pb-sm font-semibold"></th>
            </tr>
          </thead>
          <tbody>
            {episodes.map((ep) => (
              <tr
                key={ep.episode_index}
                className="border-b border-hairline-soft hover:bg-surface cursor-pointer transition-colors group"
                onClick={() => navigate(`/datasets/${ds}/episodes/${ep.episode_index}/replay`)}
                title={`Open replay for episode #${ep.display_index}`}
              >
                <td className="py-md">
                  <span className="inline-flex items-center gap-1 text-ink text-body-sm-medium group-hover:underline">
                    {ep.display_index}
                    <span className="text-stone group-hover:text-ink">→</span>
                  </span>
                </td>
                <td className="py-md text-slate">{ep.task}</td>
                <td className="py-md text-slate">{ep.duration_sec.toFixed(1)}s</td>
                <td className="py-md text-slate">{ep.num_frames}</td>
                <td className="py-md">
                  {ep.success === true && <span className="text-brand-green-deep">Success</span>}
                  {ep.success === false && <span className="text-brand-error">Failure</span>}
                  {ep.success === null && <span className="text-stone">—</span>}
                </td>
                <td className="py-md text-slate">{ep.mode}</td>
                <td className="py-md text-steel text-caption">{ep.recorded_at || "—"}</td>
                <td className="py-md text-right" onClick={(e) => e.stopPropagation()}>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="!bg-brand-error/10 !text-brand-error hover:!bg-brand-error/20"
                    onClick={() => {
                      if (confirm(`Delete episode #${ep.display_index}?`)) {
                        deleteMutation.mutate(ep.episode_index);
                      }
                    }}
                  >
                    🗑 Delete
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
