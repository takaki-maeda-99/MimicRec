import { useInferenceStore } from "../../state/inference-store";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";

interface Props {
  /** True when session is in a state that permits starting inference. */
  canStartSession: boolean;
}

export function PhaseActionBar({ canStartSession }: Props) {
  const s = useInferenceStore();
  const selected = s.configs.find((c) => c.name === s.selectedConfig);
  const selectedHasError = !!selected?.error;
  const canStart = canStartSession && !!s.selectedConfig && !selectedHasError && !!s.instruction;

  return (
    <footer className="flex-shrink-0 flex items-center gap-md px-md py-sm border-t border-hairline bg-canvas">
      {s.phase === "pre-start" && (
        <>
          <span className="text-body-sm text-steel">Configure the inference session, then start.</span>
          <span className="flex-1" />
          <Button onClick={() => s.startSession()} disabled={!canStart}>
            Start session
          </Button>
        </>
      )}

      {s.phase === "ready" && (
        <>
          <span className="text-body-sm text-steel">Ready — start an episode when you're set.</span>
          <span className="flex-1" />
          <Button onClick={() => s.startEpisode()}>Start episode</Button>
        </>
      )}

      {s.phase === "recording" && (
        <>
          <Badge variant="destructive">⏺ {s.episodeElapsedSec.toFixed(1)}s</Badge>
          <span className="text-body-sm text-steel">REC · instruction locked</span>
          <span className="flex-1" />
          <Button variant="destructive" onClick={() => s.stopEpisode()}>⏹ Stop episode</Button>
        </>
      )}

      {s.phase === "review" && (
        <>
          <span className="text-body-sm text-steel">
            Episode
            {s.reviewEpisode && <> #{s.reviewEpisode.index} · {s.reviewEpisode.durationSec.toFixed(1)}s</>}
            {" ended."}
          </span>
          <span className="flex-1" />
          <Button onClick={() => s.commitEpisode(true)}>Save success</Button>
          <Button variant="outline" onClick={() => s.commitEpisode(false)}>Save failure</Button>
          <Button variant="ghost" onClick={() => s.discardEpisode()}>Discard</Button>
        </>
      )}
    </footer>
  );
}
