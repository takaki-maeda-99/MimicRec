import { useState } from "react";
import { Link } from "react-router-dom";
import { useDatasets, useDeleteDataset } from "../api/queries";
import { apiFetch } from "../api/client";
import { Button } from "../components/ui/button";
import { ExportDatasetModal } from "../components/ExportDatasetModal";
import { CreateDatasetModal } from "../components/CreateDatasetModal";

export default function DatasetsPage() {
  const { data: datasets, isLoading } = useDatasets();
  const deleteMutation = useDeleteDataset();
  const [annotating, setAnnotating] = useState<string | null>(null);
  const [progress, setProgress] = useState<{
    done: number; total: number; current_episode: number | null; status: string;
  } | null>(null);
  const [exportingDataset, setExportingDataset] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const handleAnnotateAll = async (dsName: string) => {
    if (!confirm(`Annotate all episodes in "${dsName}" with Gemma 4?\nThis may take a while.`)) return;
    setAnnotating(dsName);
    setProgress(null);
    try {
      await apiFetch(`/api/datasets/${dsName}/annotate-all`, {
        method: "POST", body: JSON.stringify({}),
      });
      const poll = setInterval(async () => {
        try {
          const p = await apiFetch<{ done: number; total: number; current_episode: number | null; status: string }>(
            `/api/datasets/${dsName}/annotate-progress`,
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

  return (
    <div>
      <header className="flex items-center justify-between pb-sm mb-lg border-b border-hairline">
        <h2 className="text-heading-3 text-ink">Datasets</h2>
        <Button onClick={() => setCreating(true)}>New Dataset</Button>
      </header>

      {isLoading ? (
        <p className="text-steel">Loading...</p>
      ) : !datasets?.length ? (
        <p className="text-steel">No datasets yet. Click "New Dataset" to create one.</p>
      ) : (
        <table className="w-full text-body-sm">
          <thead>
            <tr className="border-b border-hairline text-left text-steel text-micro-uppercase uppercase tracking-[0.5px]">
              <th className="pb-sm font-semibold">Name</th>
              <th className="pb-sm font-semibold">Episodes</th>
              <th className="pb-sm font-semibold">Frames</th>
              <th className="pb-sm font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((ds) => (
              <tr key={ds.name} className="border-b border-hairline-soft">
                <td className="py-md">
                  <Link
                    to={`/datasets/${ds.name}/episodes`}
                    className="text-ink text-body-sm-medium hover:underline"
                  >
                    {ds.name}
                  </Link>
                </td>
                <td className="py-md text-slate">{ds.num_episodes}</td>
                <td className="py-md text-slate">{ds.total_frames}</td>
                <td className="py-md flex gap-md">
                  <Button variant="link" onClick={() => setExportingDataset(ds.name)}>
                    Export
                  </Button>
                  <Button
                    variant="link"
                    onClick={() => handleAnnotateAll(ds.name)}
                    disabled={annotating !== null}
                    className={annotating === ds.name ? "!text-brand-tag" : ""}
                  >
                    {annotating === ds.name && progress
                      ? `${progress.done}/${progress.total} (ep ${progress.current_episode ?? "..."})`
                      : annotating === ds.name
                      ? "Starting..."
                      : "Annotate"}
                  </Button>
                  <Button
                    variant="link"
                    className="!text-brand-error"
                    onClick={() => {
                      if (confirm(`Delete dataset "${ds.name}" and all its episodes?`)) {
                        deleteMutation.mutate(ds.name);
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

      {annotating && progress && progress.total > 0 && (
        <div className="mt-xl rounded-lg border border-hairline bg-canvas p-md">
          <div className="flex items-center justify-between mb-xs">
            <span className="text-body-sm-medium text-ink">Annotating {annotating}</span>
            <span className="text-body-sm text-steel">
              {progress.done} / {progress.total} episodes
              {progress.current_episode !== null && ` (processing ep ${progress.current_episode})`}
            </span>
          </div>
          <div className="w-full bg-surface rounded-full h-2 overflow-hidden">
            <div
              className="bg-brand-tag h-2 transition-all"
              style={{ width: `${(progress.done / progress.total) * 100}%` }}
            />
          </div>
          {progress.status === "done" && (
            <p className="mt-xs text-body-sm text-brand-green-deep">Complete!</p>
          )}
        </div>
      )}

      {creating && <CreateDatasetModal onClose={() => setCreating(false)} />}
      {exportingDataset && (
        <ExportDatasetModal ds={exportingDataset} onClose={() => setExportingDataset(null)} />
      )}
    </div>
  );
}
