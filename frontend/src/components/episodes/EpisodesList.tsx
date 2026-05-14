import type { EpisodeSummary } from "../../api/types";

interface Props {
  episodes: EpisodeSummary[];
  selectedIdx: number | null;
  onSelect: (idx: number) => void;
}

export function EpisodesList({ episodes, selectedIdx, onSelect }: Props) {
  if (episodes.length === 0) {
    return <p className="text-steel p-md">No episodes match the current filter.</p>;
  }

  return (
    <ul className="flex-1 min-h-0 overflow-auto" role="listbox">
      {episodes.map((ep) => {
        const isSel = ep.episode_index === selectedIdx;
        return (
          <li
            key={ep.episode_index}
            role="option"
            aria-selected={isSel}
            onClick={() => onSelect(ep.episode_index)}
            className={
              "grid grid-cols-[56px_1fr_60px_38px_80px] gap-md items-center px-xl py-sm border-b border-hairline-soft cursor-pointer transition-colors " +
              (isSel ? "bg-surface" : "hover:bg-surface-soft")
            }
          >
            <span className="font-mono text-caption text-stone tabular-nums">#{ep.display_index}</span>
            <span className="text-body-sm text-ink truncate">{ep.task}</span>
            <span className="font-mono text-caption text-steel tabular-nums">{ep.duration_sec.toFixed(1)}s</span>
            <StatusGlyph success={ep.success} />
            <span className="text-caption text-steel truncate">{ep.mode}</span>
          </li>
        );
      })}
    </ul>
  );
}

function StatusGlyph({ success }: { success: boolean | null }) {
  if (success === true)  return <span className="text-brand-green-deep font-semibold">✓</span>;
  if (success === false) return <span className="text-brand-error font-semibold">✗</span>;
  return <span className="text-stone">—</span>;
}
