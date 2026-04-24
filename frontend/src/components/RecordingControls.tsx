import { useEffect, useCallback, useState } from "react";
import { useEpisodeStart, useEpisodeStop, useEpisodeSave, useEpisodeDiscard } from "../api/queries.ts";
import { useSessionStore } from "../state/session-store.ts";

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
      <button className="bg-red-600 text-white px-8 py-3 rounded-lg text-lg font-medium hover:bg-red-700" onClick={() => episodeStart.mutate()}>
        Start Recording (Space)
      </button>
    );
  }

  if (sessionState === "recording") {
    const effectiveFps = fps ?? 30;
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-4">
          <span className="inline-flex items-center gap-2">
            <span className="w-3 h-3 bg-red-500 rounded-full animate-pulse" />
            <span className="text-red-600 font-medium">Recording</span>
          </span>
          {progress && (
            <span className="text-sm text-gray-600">
              {progress.num_frames} frames &middot; {(progress.num_frames / effectiveFps).toFixed(1)}s
            </span>
          )}
        </div>
        <button className="bg-gray-800 text-white px-8 py-3 rounded-lg text-lg font-medium hover:bg-gray-900" onClick={() => episodeStop.mutate()}>
          Stop Recording (Space)
        </button>
      </div>
    );
  }

  if (sessionState === "review") {
    return (
      <div className="space-y-4">
        <div className="text-lg font-medium text-gray-700">Review Episode</div>
        <div className="flex gap-2">
          <button onClick={() => setSuccessLabel(true)} className={`px-3 py-1 rounded text-sm ${successLabel === true ? "bg-green-600 text-white" : "bg-gray-100 text-gray-700"}`}>1: Success</button>
          <button onClick={() => setSuccessLabel(false)} className={`px-3 py-1 rounded text-sm ${successLabel === false ? "bg-red-600 text-white" : "bg-gray-100 text-gray-700"}`}>2: Failure</button>
          <button onClick={() => setSuccessLabel(null)} className={`px-3 py-1 rounded text-sm ${successLabel === null ? "bg-yellow-600 text-white" : "bg-gray-100 text-gray-700"}`}>3: Skip</button>
        </div>
        <div className="flex gap-3">
          <button className="bg-green-600 text-white px-6 py-2 rounded-md font-medium hover:bg-green-700" onClick={handleSave}>Save (S)</button>
          <button className="bg-gray-600 text-white px-6 py-2 rounded-md font-medium hover:bg-gray-700" onClick={handleDiscard}>Discard (D)</button>
        </div>
      </div>
    );
  }

  return null;
}
