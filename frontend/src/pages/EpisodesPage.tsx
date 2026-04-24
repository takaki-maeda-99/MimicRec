import { useParams, Link } from "react-router-dom";
import { useEpisodes, useDeleteEpisode } from "../api/queries";

export default function EpisodesPage() {
  const { ds } = useParams<{ ds: string }>();
  const { data: episodes, isLoading } = useEpisodes(ds || "");
  const deleteMutation = useDeleteEpisode(ds || "");

  if (!ds) return <div className="p-6">No dataset selected</div>;

  return (
    <div className="p-6 max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <Link to="/datasets" className="text-sm text-gray-500 hover:text-gray-700">&larr; Datasets</Link>
          <h2 className="text-2xl font-bold mt-1">Episodes — {ds}</h2>
        </div>
      </div>

      {isLoading ? (
        <p className="text-gray-500">Loading...</p>
      ) : !episodes?.length ? (
        <p className="text-gray-500">No episodes recorded yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-left text-gray-500">
              <th className="pb-2 font-medium">#</th>
              <th className="pb-2 font-medium">Task</th>
              <th className="pb-2 font-medium">Duration</th>
              <th className="pb-2 font-medium">Frames</th>
              <th className="pb-2 font-medium">Success</th>
              <th className="pb-2 font-medium">Mode</th>
              <th className="pb-2 font-medium">Recorded</th>
              <th className="pb-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {episodes.map((ep) => (
              <tr key={ep.episode_index} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="py-3">
                  <Link
                    to={`/datasets/${ds}/episodes/${ep.episode_index}/replay`}
                    className="text-blue-600 hover:underline font-medium"
                  >
                    {ep.episode_index}
                  </Link>
                </td>
                <td className="py-3 text-gray-600">{ep.task}</td>
                <td className="py-3 text-gray-600">{ep.duration_sec.toFixed(1)}s</td>
                <td className="py-3 text-gray-600">{ep.num_frames}</td>
                <td className="py-3">
                  {ep.success === true && <span className="text-green-600">Success</span>}
                  {ep.success === false && <span className="text-red-600">Failure</span>}
                  {ep.success === null && <span className="text-gray-400">—</span>}
                </td>
                <td className="py-3 text-gray-600">{ep.mode}</td>
                <td className="py-3 text-gray-500 text-xs">{ep.recorded_at || "—"}</td>
                <td className="py-3">
                  <button
                    className="text-red-600 hover:text-red-800 text-sm"
                    onClick={() => {
                      if (confirm(`Delete episode ${ep.episode_index}?`)) {
                        deleteMutation.mutate(ep.episode_index);
                      }
                    }}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
