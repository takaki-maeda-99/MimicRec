import { useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useEpisodes, useDeleteEpisode } from "../api/queries";
import { CodeInline } from "../components/ui/code-inline";
import { PageHeader } from "../components/ui/page-header";
import { EpisodesFilterBar, type StatusFilter } from "../components/episodes/EpisodesFilterBar";
import { EpisodesList } from "../components/episodes/EpisodesList";
import { EpisodePreviewPane } from "../components/episodes/EpisodePreviewPane";

export default function EpisodesPage() {
  const { ds } = useParams<{ ds: string }>();
  const { data: episodes = [], isLoading } = useEpisodes(ds || "");
  const deleteMutation = useDeleteEpisode(ds || "");

  const [status, setStatus] = useState<StatusFilter>("all");
  const [modes, setModes] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);

  const availableModes = useMemo(
    () => Array.from(new Set(episodes.map((e) => e.mode).filter(Boolean))) as string[],
    [episodes],
  );

  const filtered = useMemo(() => {
    return episodes.filter((e) => {
      if (status === "success" && e.success !== true) return false;
      if (status === "failure" && e.success !== false) return false;
      if (modes.size > 0 && !modes.has(e.mode)) return false;
      if (search && !e.task.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [episodes, status, modes, search]);

  // Auto-select first in filtered list when selection becomes invalid
  const effectiveSel = useMemo(() => {
    if (selectedIdx != null && filtered.some((e) => e.episode_index === selectedIdx)) return selectedIdx;
    return filtered[0]?.episode_index ?? null;
  }, [filtered, selectedIdx]);

  const selectedEpisode = filtered.find((e) => e.episode_index === effectiveSel) ?? null;

  const successCount = episodes.filter((e) => e.success === true).length;
  const failureCount = episodes.filter((e) => e.success === false).length;

  const toggleMode = (m: string) => {
    setModes((prev) => {
      const next = new Set(prev);
      if (next.has(m)) next.delete(m); else next.add(m);
      return next;
    });
  };

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
        meta={
          <span className="font-mono text-micro text-stone">
            {episodes.length} episodes · {successCount} ok / {failureCount} failed
          </span>
        }
        actions={
          <Link to="/datasets" className="text-caption text-steel hover:text-ink">
            ← Datasets
          </Link>
        }
      />

      <EpisodesFilterBar
        total={episodes.length}
        successCount={successCount}
        failureCount={failureCount}
        status={status} onStatusChange={setStatus}
        modes={modes} availableModes={availableModes} onToggleMode={toggleMode}
        search={search} onSearchChange={setSearch}
      />

      <div className="flex-1 flex min-h-0">
        {isLoading ? (
          <p className="text-steel p-md">Loading…</p>
        ) : (
          <>
            <div className="flex-1 min-w-0 flex flex-col border-r border-hairline">
              <EpisodesList
                episodes={filtered}
                selectedIdx={effectiveSel}
                onSelect={setSelectedIdx}
              />
            </div>
            <EpisodePreviewPane
              ds={ds}
              episode={selectedEpisode}
              onDelete={(idx) => {
                if (confirm(`Delete episode #${selectedEpisode?.display_index ?? idx}?`)) {
                  deleteMutation.mutate(idx);
                }
              }}
            />
          </>
        )}
      </div>
    </>
  );
}
