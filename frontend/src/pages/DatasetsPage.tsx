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
import { PageHeader } from "../components/ui/page-header";

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
    <>
      <PageHeader
        code="§01"
        title="Catalogue"
        meta={
          <span className="font-mono text-micro text-stone">
            {datasets?.length ?? 0} collections
          </span>
        }
        actions={
          <>
            <HubAuthPill auth={auth} loading={authLoading} onRefresh={refreshAuth} />
            <Button size="sm" onClick={() => setCreating(true)}>+ New dataset</Button>
          </>
        }
      />

      <div className="flex-1 overflow-auto">
        <div className="max-w-[1240px] mx-auto px-xl py-xl">
          <SummaryBlock datasets={datasets ?? []} />

          {isLoading ? (
            <p className="text-steel">Loading...</p>
          ) : !datasets?.length ? (
            <p className="text-steel">No datasets yet. Click "+ New dataset" to create one.</p>
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
        </div>
      </div>

      {creating && <CreateDatasetModal onClose={() => setCreating(false)} />}
      {exportingDataset && (
        <ExportDatasetModal ds={exportingDataset} onClose={() => setExportingDataset(null)} />
      )}
    </>
  );
}

function SummaryBlock({ datasets }: { datasets: Array<{ name: string; num_episodes: number; total_frames: number }> }) {
  const totalEp = datasets.reduce((s, d) => s + d.num_episodes, 0);
  const totalFr = datasets.reduce((s, d) => s + d.total_frames, 0);
  return (
    <div className="flex items-end justify-between gap-xl pb-xl border-b border-hairline mb-xl">
      <div>
        <h2 className="text-heading-2 text-ink leading-tight">Recorded data, sorted by recency.</h2>
        <p className="text-body-sm text-steel mt-2 max-w-[640px]">
          {datasets.length} active datasets — review status, push to Hub, export, or annotate.
        </p>
      </div>
      <div className="flex gap-xl items-baseline text-right">
        <Stat label="datasets" value={datasets.length} />
        <Stat label="episodes" value={totalEp} />
        <Stat label="frames" value={totalFr.toLocaleString()} />
      </div>
    </div>
  );
}
function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col items-end gap-0.5">
      <span className="font-mono text-heading-3 text-ink tabular-nums leading-none">{value}</span>
      <span className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">{label}</span>
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
  const base =
    "inline-flex items-center gap-1 h-9 px-md rounded-full text-button-md transition-colors cursor-pointer";
  if (loading) {
    return (
      <span className={`${base} border border-hairline text-steel`}>
        HF: checking…
      </span>
    );
  }
  if (auth?.authenticated) {
    return (
      <button
        onClick={onRefresh}
        title="Click to refresh"
        className={`${base} bg-brand-green text-primary hover:opacity-90`}
      >
        HF: @{auth.username ?? "(unknown)"}
      </button>
    );
  }
  return (
    <button
      onClick={onRefresh}
      title="Click to refresh"
      className={`${base} bg-brand-warn/15 text-brand-warn hover:bg-brand-warn/25`}
    >
      HF: not logged in — run&nbsp;<CodeInline>huggingface-cli login</CodeInline>
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
    <div className="rounded-lg border border-hairline bg-canvas hover:border-stone transition-colors overflow-hidden">
      <Link
        to={`/datasets/${ds.name}/episodes`}
        className="flex items-center gap-sm flex-wrap px-lg py-md bg-surface/40 hover:bg-surface transition-colors border-b border-hairline-soft group"
        title={`Open episodes for ${ds.name}`}
      >
        <span className="text-heading-5 text-ink group-hover:underline">
          {ds.name}
        </span>
        <span className="text-stone group-hover:text-ink transition-colors">→</span>
        <HubStatusBadge hub={hub} />
      </Link>
      <div className="p-lg">

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
          <Button variant="primary" size="lg">Episodes →</Button>
        </Link>

        {!hubConfigured && (
          <Button
            variant="secondary"
            size="lg"
            className="!bg-surface hover:!bg-hairline"
            onClick={() => setEditing(true)}
          >
            ☁ Configure Hub
          </Button>
        )}
        {hubConfigured && (
          <>
            <Button
              variant="secondary"
              size="lg"
              className="!bg-surface hover:!bg-hairline"
              onClick={onPush}
              disabled={!auth?.authenticated || isPushing}
              title={!auth?.authenticated ? "Run huggingface-cli login first" : undefined}
            >
              {isPushing ? "Pushing…" : "↑ Push to Hub"}
            </Button>
            <Button
              variant="secondary"
              size="lg"
              className="!bg-surface hover:!bg-hairline"
              onClick={() => setEditing(true)}
            >
              Edit Hub
            </Button>
          </>
        )}

        <Button
          variant="secondary"
          size="lg"
          className="!bg-surface hover:!bg-hairline"
          onClick={onExport}
        >
          Export
        </Button>
        <Button
          variant="secondary"
          size="lg"
          onClick={onAnnotate}
          disabled={annotatingAny}
          className={`!bg-surface hover:!bg-hairline ${isAnnotating ? "!text-brand-tag" : ""}`}
        >
          {isAnnotating && annotateProgress
            ? `Annotating ${annotateProgress.done}/${annotateProgress.total}`
            : isAnnotating
            ? "Starting…"
            : "Annotate"}
        </Button>

        <div className="grow" />

        <Button
          variant="secondary"
          size="lg"
          className="!bg-brand-error/10 !text-brand-error hover:!bg-brand-error/20"
          onClick={onDelete}
        >
          🗑 Delete
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
