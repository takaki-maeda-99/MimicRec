import React, { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useDatasets, useCreateDataset, useDeleteDataset } from "../api/queries";
import { apiFetch } from "../api/client";
import { fetchAuthStatus, fetchHub, putHub, postHubPush } from "../api/cloud";
import type { HubResponse, AuthStatus, HubConfig } from "../api/cloud";
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
  const [expandedHub, setExpandedHub] = useState<Record<string, boolean>>({});

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
              <React.Fragment key={ds.name}>
                <tr className="border-b border-gray-100 hover:bg-gray-50">
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
                      className="text-sm text-blue-600 hover:text-blue-800"
                      onClick={() => setExpandedHub((s) => ({ ...s, [ds.name]: !s[ds.name] }))}
                    >
                      {expandedHub[ds.name] ? "▾ Hub" : "▸ Hub"}
                    </button>
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
                {expandedHub[ds.name] && (
                  <tr className="border-b border-gray-100 bg-gray-50">
                    <td colSpan={4} className="py-3 px-4">
                      <HubSection ds={ds.name} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
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

function HubSection({ ds }: { ds: string }) {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [hub, setHub] = useState<HubResponse | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<HubConfig>({ repo_id: "", private: true, auto_push: false });
  const [saving, setSaving] = useState(false);
  const [pushing, setPushing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAuthStatus().then(setAuth).catch(() => setAuth(null));
    fetchHub(ds).then((r) => {
      setHub(r);
      if (r.config) setDraft(r.config);
    }).catch(() => setHub(null));
  }, [ds]);

  useEffect(() => {
    if (hub?.progress.status !== "uploading" && hub?.progress.status !== "queued") return;
    const t = setInterval(async () => {
      try {
        const r = await fetchHub(ds);
        setHub(r);
        if (r.progress.status === "done" || r.progress.status === "error") {
          clearInterval(t);
        }
      } catch (e) {
        setError(String(e));
      }
    }, 2000);
    return () => clearInterval(t);
  }, [ds, hub?.progress.status]);

  const onSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const r = await putHub(ds, draft);
      setHub(r);
      setEditing(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const onPush = async () => {
    setPushing(true);
    setError(null);
    try {
      await postHubPush(ds);
      const r = await fetchHub(ds);
      setHub(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setPushing(false);
    }
  };

  return (
    <div className="border-t border-gray-200 mt-3 pt-3 text-sm">
      <div className="flex items-center gap-2 mb-2">
        <strong>HF Hub:</strong>
        {auth?.authenticated ? (
          <span className="text-green-700">@{auth.username ?? "(unknown)"}</span>
        ) : (
          <span className="text-amber-600">Not authenticated — run `huggingface-cli login`</span>
        )}
      </div>

      {!hub?.config && !editing && (
        <button onClick={() => setEditing(true)} className="text-blue-600">Configure Hub</button>
      )}

      {editing && (
        <div className="flex gap-2 items-end">
          <input
            placeholder="user/dataset_name"
            value={draft.repo_id}
            onChange={(e) => setDraft({ ...draft, repo_id: e.target.value })}
            className="border px-2 py-1 rounded"
          />
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={draft.private} onChange={(e) => setDraft({ ...draft, private: e.target.checked })} />
            Private
          </label>
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={draft.auto_push} onChange={(e) => setDraft({ ...draft, auto_push: e.target.checked })} />
            Auto-push
          </label>
          <button onClick={onSave} disabled={saving} className="bg-blue-600 text-white px-3 py-1 rounded">
            {saving ? "Saving..." : "Save"}
          </button>
          <button onClick={() => setEditing(false)} className="px-3 py-1">Cancel</button>
        </div>
      )}

      {hub?.config && !editing && (
        <div className="space-y-1">
          <div>
            <code>{hub.config.repo_id}</code>
            {hub.config.private && <span className="ml-2 text-xs text-gray-500">(private)</span>}
            {hub.config.auto_push && <span className="ml-2 text-xs text-blue-600">auto-push</span>}
            <button onClick={() => setEditing(true)} className="ml-2 text-xs text-blue-600">edit</button>
          </div>
          <div className="text-xs text-gray-600">
            {hub.state?.last_pushed_commit_sha ? (
              hub.state.last_pushed_manifest_hash
                ? `Synced (commit ${hub.state.last_pushed_commit_sha.slice(0, 7)})`
                : `Pushed but stale (commit ${hub.state.last_pushed_commit_sha.slice(0, 7)})`
            ) : "Not pushed yet"}
          </div>
          <div>
            <button
              onClick={onPush}
              disabled={!auth?.authenticated || pushing || hub.progress.status === "uploading" || hub.progress.status === "queued"}
              className="bg-blue-600 text-white px-3 py-1 rounded disabled:opacity-50"
            >
              {hub.progress.status === "uploading" ? "Uploading..." : "Push to HF Hub"}
            </button>
            {hub.progress.status === "uploading" && hub.progress.started_at && (
              <span className="ml-2 text-xs text-gray-500">
                started {new Date(hub.progress.started_at).toLocaleTimeString()}
              </span>
            )}
          </div>
          {hub.state?.last_push_error && (
            <div className="text-xs text-red-600">last error: {hub.state.last_push_error}</div>
          )}
          {error && <div className="text-xs text-red-600">{error}</div>}
        </div>
      )}
    </div>
  );
}
