import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useDatasets, useDeleteDataset } from "../api/queries";
import { apiFetch } from "../api/client";
import { fetchAuthStatus, fetchHub, putHub, postHubPush } from "../api/cloud";
import type { HubResponse, AuthStatus, HubConfig } from "../api/cloud";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
import { CodeInline } from "../components/ui/code-inline";
import { ExportDatasetModal } from "../components/ExportDatasetModal";
import { CreateDatasetModal } from "../components/CreateDatasetModal";

interface AnnotateProgress {
  done: number;
  total: number;
  current_episode: number | null;
  status: string;
}

export default function DatasetsPage() {
  const { data: datasets, isLoading } = useDatasets();
  const deleteMutation = useDeleteDataset();
  const [annotating, setAnnotating] = useState<string | null>(null);
  const [progress, setProgress] = useState<AnnotateProgress | null>(null);
  const [exportingDataset, setExportingDataset] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [authLoading, setAuthLoading] = useState(true);

  // Page-level HF auth (always visible at top)
  useEffect(() => {
    let mounted = true;
    fetchAuthStatus()
      .then((s) => {
        if (mounted) {
          setAuth(s);
          setAuthLoading(false);
        }
      })
      .catch(() => {
        if (mounted) {
          setAuth(null);
          setAuthLoading(false);
        }
      });
    return () => {
      mounted = false;
    };
  }, []);

  const refreshAuth = async () => {
    setAuthLoading(true);
    try {
      const s = await fetchAuthStatus(true);
      setAuth(s);
    } catch {
      setAuth(null);
    } finally {
      setAuthLoading(false);
    }
  };

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
          const p = await apiFetch<AnnotateProgress>(
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
      <header className="flex items-center justify-between pb-sm mb-lg border-b border-hairline gap-md">
        <div className="flex items-center gap-md">
          <h2 className="text-heading-3 text-ink">Datasets</h2>
          <HubAuthPill auth={auth} loading={authLoading} onRefresh={refreshAuth} />
        </div>
        <Button onClick={() => setCreating(true)}>+ New Dataset</Button>
      </header>

      {isLoading ? (
        <p className="text-steel">Loading...</p>
      ) : !datasets?.length ? (
        <p className="text-steel">No datasets yet. Click "+ New Dataset" to create one.</p>
      ) : (
        <div className="flex flex-col gap-md">
          {datasets.map((ds) => (
            <DatasetCard
              key={ds.name}
              ds={ds}
              auth={auth}
              isAnnotating={annotating === ds.name}
              annotatingAny={annotating !== null}
              annotateProgress={annotating === ds.name ? progress : null}
              onAnnotate={() => handleAnnotateAll(ds.name)}
              onExport={() => setExportingDataset(ds.name)}
              onDelete={() => {
                if (confirm(`Delete dataset "${ds.name}" and all its episodes?`)) {
                  deleteMutation.mutate(ds.name);
                }
              }}
            />
          ))}
        </div>
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

function HubAuthPill({
  auth,
  loading,
  onRefresh,
}: {
  auth: AuthStatus | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  if (loading) {
    return <Badge variant="outline">HF: checking…</Badge>;
  }
  if (auth?.authenticated) {
    return (
      <button onClick={onRefresh} title="Click to refresh" className="cursor-pointer">
        <Badge variant="success">HF: @{auth.username ?? "(unknown)"}</Badge>
      </button>
    );
  }
  return (
    <button onClick={onRefresh} title="Click to refresh" className="cursor-pointer">
      <Badge variant="warning">HF: not logged in — run <CodeInline>huggingface-cli login</CodeInline></Badge>
    </button>
  );
}

interface DatasetCardProps {
  ds: { name: string; num_episodes: number; total_frames: number };
  auth: AuthStatus | null;
  isAnnotating: boolean;
  annotatingAny: boolean;
  annotateProgress: AnnotateProgress | null;
  onAnnotate: () => void;
  onExport: () => void;
  onDelete: () => void;
}

function DatasetCard({
  ds,
  auth,
  isAnnotating,
  annotatingAny,
  annotateProgress,
  onAnnotate,
  onExport,
  onDelete,
}: DatasetCardProps) {
  const [hub, setHub] = useState<HubResponse | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<HubConfig>({ repo_id: "", private: true, auto_push: false });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    fetchHub(ds.name)
      .then((r) => {
        if (!mounted) return;
        setHub(r);
        if (r.config) setDraft(r.config);
      })
      .catch(() => {
        if (mounted) setHub(null);
      });
    return () => {
      mounted = false;
    };
  }, [ds.name]);

  // Poll while pushing
  useEffect(() => {
    if (hub?.progress.status !== "uploading" && hub?.progress.status !== "queued") return;
    const t = setInterval(async () => {
      try {
        const r = await fetchHub(ds.name);
        setHub(r);
        if (r.progress.status === "done" || r.progress.status === "error") {
          clearInterval(t);
        }
      } catch (e) {
        setError(String(e));
      }
    }, 2000);
    return () => clearInterval(t);
  }, [ds.name, hub?.progress.status]);

  const onSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const r = await putHub(ds.name, draft);
      setHub(r);
      setEditing(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const onPush = async () => {
    setError(null);
    try {
      await postHubPush(ds.name);
      const r = await fetchHub(ds.name);
      setHub(r);
    } catch (e) {
      setError(String(e));
    }
  };

  const hubConfigured = !!hub?.config;
  const isPushing =
    hub?.progress.status === "uploading" || hub?.progress.status === "queued";

  return (
    <div className="rounded-lg border border-hairline bg-canvas p-lg hover:border-stone transition-colors">
      <div className="flex items-start justify-between gap-md mb-sm">
        <div className="flex items-center gap-sm flex-wrap">
          <Link
            to={`/datasets/${ds.name}/episodes`}
            className="text-heading-5 text-ink hover:underline"
          >
            {ds.name}
          </Link>
          <HubStatusBadge hub={hub} />
        </div>
      </div>

      <div className="text-body-sm text-slate mb-md flex flex-wrap items-center gap-sm">
        <span>
          {ds.num_episodes} episode{ds.num_episodes === 1 ? "" : "s"} ·{" "}
          {ds.total_frames.toLocaleString()} frames
        </span>
        {hubConfigured && hub.config && (
          <span className="flex items-center gap-1">
            · <CodeInline>{hub.config.repo_id}</CodeInline>
            {hub.config.private && (
              <span className="text-caption text-stone">private</span>
            )}
            {hub.config.auto_push && (
              <Badge variant="tag">auto-push</Badge>
            )}
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-sm">
        <Link to={`/datasets/${ds.name}/episodes`}>
          <Button variant="primary" size="sm">Episodes →</Button>
        </Link>

        {!hubConfigured && (
          <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
            ☁ Configure Hub
          </Button>
        )}
        {hubConfigured && (
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={onPush}
              disabled={!auth?.authenticated || isPushing}
              title={!auth?.authenticated ? "Run huggingface-cli login first" : undefined}
            >
              {isPushing ? "Pushing…" : "↑ Push to Hub"}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
              Edit Hub
            </Button>
          </>
        )}

        <Button variant="ghost" size="sm" onClick={onExport}>
          Export
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onAnnotate}
          disabled={annotatingAny}
          className={isAnnotating ? "!text-brand-tag" : ""}
        >
          {isAnnotating && annotateProgress
            ? `Annotating ${annotateProgress.done}/${annotateProgress.total}`
            : isAnnotating
            ? "Starting…"
            : "Annotate"}
        </Button>

        <div className="grow" />

        <Button variant="destructive" size="sm" onClick={onDelete}>
          Delete
        </Button>
      </div>

      {editing && (
        <div className="mt-md pt-md border-t border-hairline-soft">
          <div className="flex flex-wrap items-end gap-sm">
            <div className="flex flex-col">
              <label className="text-caption text-steel mb-1">Repo ID</label>
              <Input
                placeholder="user/dataset_name"
                value={draft.repo_id}
                onChange={(e) => setDraft({ ...draft, repo_id: e.target.value })}
                className="w-64"
              />
            </div>
            <label className="flex items-center gap-1 text-body-sm text-ink h-9">
              <input
                type="checkbox"
                checked={draft.private}
                onChange={(e) => setDraft({ ...draft, private: e.target.checked })}
              />
              Private
            </label>
            <label className="flex items-center gap-1 text-body-sm text-ink h-9">
              <input
                type="checkbox"
                checked={draft.auto_push}
                onChange={(e) => setDraft({ ...draft, auto_push: e.target.checked })}
              />
              Auto-push
            </label>
            <Button variant="primary" size="sm" onClick={onSave} disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {hub?.state?.last_push_error && !isPushing && (
        <div className="mt-sm text-caption text-brand-error">
          last error: {hub.state.last_push_error}
        </div>
      )}
      {error && <div className="mt-sm text-caption text-brand-error">{error}</div>}
      {hubConfigured && hub.state?.last_pushed_at && (
        <div className="mt-sm text-caption text-stone">
          last pushed: {new Date(hub.state.last_pushed_at).toLocaleString()}
          {hub.state.last_pushed_commit_sha && (
            <> · commit <CodeInline>{hub.state.last_pushed_commit_sha.slice(0, 7)}</CodeInline></>
          )}
        </div>
      )}
    </div>
  );
}

function HubStatusBadge({ hub }: { hub: HubResponse | null }) {
  if (!hub) return null;
  if (!hub.config) {
    return <Badge variant="outline">Hub: not configured</Badge>;
  }
  if (hub.progress.status === "uploading") {
    return <Badge variant="tag">Pushing…</Badge>;
  }
  if (hub.progress.status === "queued") {
    return <Badge variant="tag">Queued</Badge>;
  }
  if (hub.progress.status === "error" || hub.state?.last_push_error) {
    return <Badge variant="destructive">Push failed</Badge>;
  }
  if (!hub.state?.last_pushed_commit_sha) {
    return <Badge variant="outline">Not pushed</Badge>;
  }
  if (!hub.state.last_pushed_manifest_hash) {
    return <Badge variant="warning">Stale</Badge>;
  }
  return <Badge variant="success">✓ Synced</Badge>;
}
