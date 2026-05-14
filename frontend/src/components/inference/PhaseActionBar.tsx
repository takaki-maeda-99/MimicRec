import { useInferenceStore } from "../../state/inference-store";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";

interface Props {
  /** True when session is in a state that permits starting inference. */
  canStartSession: boolean;
}

export function PhaseActionBar({ canStartSession }: Props) {
  const phase = useInferenceStore((s) => s.phase);
  const configs = useInferenceStore((s) => s.configs);
  const selectedConfig = useInferenceStore((s) => s.selectedConfig);
  const instruction = useInferenceStore((s) => s.instruction);
  const episodeElapsedSec = useInferenceStore((s) => s.episodeElapsedSec);
  const reviewEpisode = useInferenceStore((s) => s.reviewEpisode);
  const startSession = useInferenceStore((s) => s.startSession);
  const startEpisode = useInferenceStore((s) => s.startEpisode);
  const stopEpisode = useInferenceStore((s) => s.stopEpisode);
  const commitEpisode = useInferenceStore((s) => s.commitEpisode);
  const discardEpisode = useInferenceStore((s) => s.discardEpisode);

  const selected = configs.find((c) => c.name === selectedConfig);
  const selectedHasError = !!selected?.error;
  const canStart = canStartSession && !!selectedConfig && !selectedHasError && !!instruction;

  return (
    <footer className="flex-shrink-0 flex items-center gap-md px-md py-sm border-t border-hairline bg-canvas">
      {phase === "pre-start" && (
        <>
          <span className="text-body-sm text-steel">Configure the inference session, then start.</span>
          <span className="flex-1" />
          <Button onClick={() => startSession()} disabled={!canStart}>
            Start session
          </Button>
        </>
      )}

      {phase === "ready" && (
        <>
          <span className="text-body-sm text-steel">Ready — start an episode when you're set.</span>
          <span className="flex-1" />
          <Button onClick={() => startEpisode()}>Start episode</Button>
        </>
      )}

      {phase === "recording" && (
        <>
          <Badge variant="destructive">⏺ {episodeElapsedSec.toFixed(1)}s</Badge>
          <span className="text-body-sm text-steel">REC · instruction locked</span>
          <span className="flex-1" />
          <Button variant="destructive" onClick={() => stopEpisode()}>⏹ Stop episode</Button>
        </>
      )}

      {phase === "review" && (
        <>
          <span className="text-body-sm text-steel">
            Episode
            {reviewEpisode && <> #{reviewEpisode.index} · {reviewEpisode.durationSec.toFixed(1)}s</>}
            {" ended."}
          </span>
          <span className="flex-1" />
          <Button onClick={() => commitEpisode(true)}>Save success</Button>
          <Button variant="outline" onClick={() => commitEpisode(false)}>Save failure</Button>
          <Button variant="ghost" onClick={() => discardEpisode()}>Discard</Button>
        </>
      )}
    </footer>
  );
}
