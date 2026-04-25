import { useEffect, useCallback, useState } from "react";
import { useEpisodeStart, useEpisodeStop, useEpisodeSave, useEpisodeDiscard } from "../api/queries.ts";
import { useSessionStore } from "../state/session-store.ts";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";

export default function RecordingControls() {
  const sessionState = useSessionStore(s => s.state);
  const progress = useSessionStore(s => s.episodeProgress);
  const fps = useSessionStore(s => s.fps);
  const episodeStart = useEpisodeStart();
  const episodeStop = useEpisodeStop();
  const episodeSave = useEpisodeSave();
  const episodeDiscard = useEpisodeDiscard();
  const [successLabel, setSuccessLabel] = useState<boolean | null>(null);

  const handleSpace = useCallback(() => {
    if (sessionState === "ready") episodeStart.mutate();
    else if (sessionState === "recording") episodeStop.mutate();
  }, [sessionState, episodeStart, episodeStop]);

  const handleSave = useCallback(() => {
    if (sessionState === "review") episodeSave.mutate({ success: successLabel });
  }, [sessionState, episodeSave, successLabel]);

  const handleDiscard = useCallback(() => {
    if (sessionState === "review") episodeDiscard.mutate();
  }, [sessionState, episodeDiscard]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.code === "Space") { e.preventDefault(); handleSpace(); }
      if (e.key === "s" || e.key === "S") handleSave();
      if (e.key === "d" || e.key === "D") handleDiscard();
      if (e.key === "1") setSuccessLabel(true);
      if (e.key === "2") setSuccessLabel(false);
      if (e.key === "3") setSuccessLabel(null);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleSpace, handleSave, handleDiscard]);

  if (sessionState === "ready") {
    return (
      <Button variant="destructive" size="lg" onClick={() => episodeStart.mutate()}>
        Start Recording (Space)
      </Button>
    );
  }

  if (sessionState === "recording") {
    const effectiveFps = fps ?? 30;
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-4">
          <Badge variant="destructive" className="gap-2">
            <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
            Recording
          </Badge>
          {progress && (
            <span className="text-sm text-gray-600">
              {progress.num_frames} frames &middot; {(progress.num_frames / effectiveFps).toFixed(1)}s
            </span>
          )}
        </div>
        <Button size="lg" className="bg-gray-800 hover:bg-gray-900" onClick={() => episodeStop.mutate()}>
          Stop Recording (Space)
        </Button>
      </div>
    );
  }

  if (sessionState === "review") {
    return (
      <div className="space-y-4">
        <div className="text-lg font-medium text-gray-700">Review Episode</div>
        <div className="flex gap-2">
          <Button size="sm" onClick={() => setSuccessLabel(true)} className={successLabel === true ? "bg-green-600 text-white hover:bg-green-700" : ""} variant={successLabel === true ? "default" : "outline"}>1: Success</Button>
          <Button size="sm" onClick={() => setSuccessLabel(false)} className={successLabel === false ? "bg-red-600 text-white hover:bg-red-700" : ""} variant={successLabel === false ? "destructive" : "outline"}>2: Failure</Button>
          <Button size="sm" onClick={() => setSuccessLabel(null)} className={successLabel === null ? "bg-yellow-600 text-white hover:bg-yellow-700" : ""} variant={successLabel === null ? "default" : "outline"}>3: Skip</Button>
        </div>
        <div className="flex gap-3">
          <Button className="bg-green-600 hover:bg-green-700" onClick={handleSave}>Save (S)</Button>
          <Button variant="outline" className="bg-gray-600 text-white hover:bg-gray-700" onClick={handleDiscard}>Discard (D)</Button>
        </div>
      </div>
    );
  }

  return null;
}
