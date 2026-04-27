import { useState } from "react";
import { Link } from "react-router-dom";
import { useDatasets, useCreateDataset, useDeleteDataset } from "../api/queries";
import { apiFetch } from "../api/client";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { ExportDatasetModal } from "../components/ExportDatasetModal";

export default function DatasetsPage() {
  const { data: datasets, isLoading } = useDatasets();
  const createMutation = useCreateDataset();
  const deleteMutation = useDeleteDataset();
  const [annotating, setAnnotating] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ done: number; total: number; current_episode: number | null; status: string } | null>(null);
  const [exportingDataset, setExportingDataset] = useState<string | null>(null);

  const handleAnnotateAll = async (dsName: string) => {
    if (!confirm(`Annotate all episodes in "${dsName}" with Gemma 4?\nThis may take a while.`)) return;
    setAnnotating(dsName);
    setProgress(null);
    try {
      await apiFetch(`/api/datasets/${dsName}/annotate-all`, {
        method: "POST", body: JSON.stringify({}),
      });
      // Poll progress
      const poll = setInterval(async () => {
        try {
          const p = await apiFetch<{ done: number; total: number; current_episode: number | null; status: string }>(
            `/api/datasets/${dsName}/annotate-progress`
          );
          setProgress(p);
          if (p.status === "done") {
            clearInterval(poll);
            setAnnotating(null);
          }
        } catch {
          clearInterval(poll);
          setAnnotating(null);
        }
      }, 2000);
    } catch (e) {
      alert(`Error: ${(e as Error).message}`);
      setAnnotating(null);
    }
  };
  const [name, setName] = useState("");
  const [fps, setFps] = useState(30);

  const handleCreate = () => {
    if (!name.trim()) return;
    createMutation.mutate(
      { name: name.trim(), fps, joint_names: [], camera_names: [] },
      { onSuccess: () => setName("") }
    );
  };

  return (
    <div className="p-6 max-w-4xl">
      <h2 className="text-2xl font-bold mb-6">Datasets</h2>

      {/* Create form */}
      <div className="flex gap-3 mb-6 items-end">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my_dataset"
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">FPS</label>
          <Input
            type="number"
            className="w-20"
            value={fps}
            onChange={(e) => setFps(Number(e.target.value))}
          />
        </div>
        <Button
          onClick={handleCreate}
          disabled={createMutation.isPending || !name.trim()}
        >
          Create
        </Button>
      </div>

      {/* Dataset list */}
      {isLoading ? (
        <p className="text-gray-500">Loading...</p>
      ) : !datasets?.length ? (
        <p className="text-gray-500">No datasets yet. Create one above.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-left text-gray-500">
              <th className="pb-2 font-medium">Name</th>
              <th className="pb-2 font-medium">Episodes</th>
              <th className="pb-2 font-medium">Frames</th>
              <th className="pb-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((ds) => (
              <tr key={ds.name} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="py-3">
                  <Link
                    to={`/datasets/${ds.name}/episodes`}
                    className="text-blue-600 hover:underline font-medium"
                  >
                    {ds.name}
                  </Link>
                </td>
                <td className="py-3 text-gray-600">{ds.num_episodes}</td>
                <td className="py-3 text-gray-600">{ds.total_frames}</td>
                <td className="py-3 flex gap-3">
                  <button
                    className="text-sm text-gray-600 hover:text-gray-900"
                    onClick={() => setExportingDataset(ds.name)}
                  >
                    Export
                  </button>
                  <button
                    className="text-sm text-purple-600 hover:text-purple-800"
                    onClick={() => handleAnnotateAll(ds.name)}
                    disabled={annotating !== null}
                  >
                    {annotating === ds.name && progress
                      ? `${progress.done}/${progress.total} (ep ${progress.current_episode ?? "..."})`
                      : annotating === ds.name
                      ? "Starting..."
                      : "Annotate"}
                  </button>
                  <button
                    className="text-sm text-red-600 hover:text-red-800"
                    onClick={() => {
                      if (confirm(`Delete dataset "${ds.name}" and all its episodes?`)) {
                        deleteMutation.mutate(ds.name);
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

      {/* Annotation progress bar */}
      {annotating && progress && progress.total > 0 && (
        <div className="mt-4 bg-white border border-gray-200 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">
              Annotating {annotating}
            </span>
            <span className="text-sm text-gray-500">
              {progress.done} / {progress.total} episodes
              {progress.current_episode !== null && ` (processing ep ${progress.current_episode})`}
            </span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className="bg-purple-600 h-2 rounded-full transition-all"
              style={{ width: `${(progress.done / progress.total) * 100}%` }}
            />
          </div>
          {progress.status === "done" && (
            <p className="text-sm text-green-600 mt-2">Complete!</p>
          )}
        </div>
      )}

      {exportingDataset && (
        <ExportDatasetModal
          ds={exportingDataset}
          onClose={() => setExportingDataset(null)}
        />
      )}
    </div>
  );
}
