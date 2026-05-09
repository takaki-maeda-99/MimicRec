import React, { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useDatasets, useDeleteDataset } from "../api/queries";
import { apiFetch } from "../api/client";
import { fetchAuthStatus, fetchHub, putHub, postHubPush } from "../api/cloud";
import type { HubResponse, AuthStatus, HubConfig } from "../api/cloud";
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
  const [expandedHub, setExpandedHub] = useState<Record<string, boolean>>({});

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
              <React.Fragment key={ds.name}>
                <tr className="border-b border-hairline-soft">
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
                    <Button
                      variant="link"
                      onClick={() => setExpandedHub((s) => ({ ...s, [ds.name]: !s[ds.name] }))}
                    >
                      {expandedHub[ds.name] ? "▾ Hub" : "▸ Hub"}
                    </Button>
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
                {expandedHub[ds.name] && (
                  <tr className="border-b border-hairline-soft bg-surface">
                    <td colSpan={4} className="py-md px-lg">
                      <HubSection ds={ds.name} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
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

function HubSection({ ds }: { ds: string }) {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [hub, setHub] = useState<HubResponse | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<HubConfig>({ repo_id: "", private: true, auto_push: false });
  const [saving, setSaving] = useState(false);
  const [pushing, setPushing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    fetchAuthStatus()
      .then((s) => { if (mounted) setAuth(s); })
      .catch(() => { if (mounted) setAuth(null); });
    fetchHub(ds)
      .then((r) => {
        if (!mounted) return;
        setHub(r);
        if (r.config) setDraft(r.config);
      })
      .catch(() => { if (mounted) setHub(null); });
    return () => { mounted = false; };
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
