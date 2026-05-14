import { useNavigate } from "react-router-dom";
import type { EpisodeSummary } from "../../api/types";
import { Button } from "../ui/button";
import { useEpisodeThumbnail } from "../../hooks/useEpisodeThumbnail";
import { MiniJointPlot } from "./MiniJointPlot";
import { MiniEePlot } from "./MiniEePlot";

interface Props {
  ds: string;
  episode: EpisodeSummary | null;
  onDelete: (idx: number) => void;
}

export function EpisodePreviewPane({ ds, episode, onDelete }: Props) {
  const navigate = useNavigate();
  const masterCam = episode?.cameras?.[0];
  const thumb = useEpisodeThumbnail(ds, episode?.episode_index ?? null, masterCam);

  if (!episode) {
    return (
      <aside className="w-[360px] flex-shrink-0 border-l border-hairline bg-canvas p-md text-stone text-body-sm">
        Select an episode to preview.
      </aside>
    );
  }

  const open = () => navigate(`/datasets/${ds}/episodes/${episode.episode_index}/replay`);

  return (
    <aside className="w-[360px] flex-shrink-0 border-l border-hairline bg-canvas p-md overflow-auto flex flex-col gap-md">
      <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
        Preview · #{episode.display_index}
      </div>

      <div className="aspect-video bg-surface-code rounded-sm relative overflow-hidden cursor-pointer" onClick={open}>
        {!masterCam ? (
          <div className="absolute inset-0 flex items-center justify-center text-stone text-caption">No video</div>
        ) : thumb ? (
          <img src={thumb} alt="" className="absolute inset-0 w-full h-full object-cover" />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-stone text-caption">loading…</div>
        )}
        <div className="absolute top-1 left-2 font-mono text-[10px] text-on-dark-muted bg-black/55 px-1 py-0.5 rounded-sm">
          {episode.duration_sec.toFixed(1)}s · {episode.num_frames}f
        </div>
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-9 h-9 rounded-full bg-white/15 flex items-center justify-center text-on-dark">▶</div>
        </div>
      </div>

      <div className="border-y border-hairline-soft py-1 space-y-0.5">
        <Fact k="Task"        v={episode.task} />
        <Fact k="Duration"    v={`${episode.duration_sec.toFixed(1)}s · ${episode.num_frames} frames`} mono />
        <Fact k="Status"      v={episode.success === true ? "Success" : episode.success === false ? "Failure" : "—"}
              color={episode.success === true ? "text-brand-green-deep" : episode.success === false ? "text-brand-error" : "text-stone"} />
        <Fact k="Mode · robot" v={`${episode.mode} · ${episode.robot || "—"}`} mono />
        <Fact k="Recorded"    v={episode.recorded_at || "—"} mono />
      </div>

      <div className="border border-hairline rounded-sm p-2">
        <div className="flex items-center justify-between text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold mb-1">
          <span>Joint trajectory</span>
          <span className="font-mono text-[10px] text-muted">j1–j6 + grip</span>
        </div>
        <MiniJointPlot ds={ds} idx={episode.episode_index} />
      </div>

      <div className="border border-hairline rounded-sm p-2">
        <div className="flex items-center justify-between text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold mb-1">
          <span>End-Effector · XY</span>
          <span className="font-mono text-[10px] text-muted">top-down</span>
        </div>
        <MiniEePlot ds={ds} idx={episode.episode_index} />
      </div>

      <div className="flex gap-2 mt-auto">
        <Button onClick={open} className="flex-1">▶ Open replay</Button>
        <Button variant="destructive" size="sm" onClick={() => onDelete(episode.episode_index)}>
          Delete
        </Button>
      </div>
    </aside>
  );
}

function Fact({ k, v, mono, color = "text-ink" }: { k: string; v: React.ReactNode; mono?: boolean; color?: string }) {
  return (
    <div className="flex items-baseline justify-between text-caption">
      <span className="text-micro-uppercase uppercase tracking-[0.5px] text-stone font-semibold">{k}</span>
      <span className={`${color} ${mono ? "font-mono" : ""}`}>{v}</span>
    </div>
  );
}
