import { useEffect, useCallback, useState, useRef } from "react";
import { useEpisodeStart, useEpisodeStop, useEpisodeSave, useEpisodeDiscard } from "../api/queries.ts";
import { useSessionStore } from "../state/session-store.ts";
import { useRecordFormStore } from "../state/record-form-store.ts";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";

export default function RecordingControls() {
  const sessionState = useSessionStore(s => s.state);
  const progress = useSessionStore(s => s.episodeProgress);
  const fps = useSessionStore(s => s.fps);
  const autoCycle = useRecordFormStore(s => s.autoCycle);
  const autoDurationSec = useRecordFormStore(s => s.autoDurationSec);
  const autoReviewSec = useRecordFormStore(s => s.autoReviewSec);
  const episodeStart = useEpisodeStart();
  const episodeStop = useEpisodeStop();
  const episodeSave = useEpisodeSave();
  const episodeDiscard = useEpisodeDiscard();
  const [successLabel, setSuccessLabel] = useState<boolean | null>(null);
  // cycleActive: a recording cycle is in flight. Set when user presses Space
  // to start with autoCycle ON, cleared on Esc / End Session / errors.
  const [cycleActive, setCycleActive] = useState(false);
  const [cycleCountdown, setCycleCountdown] = useState<number | null>(null);

  // Default label = success when entering review, so plain Space saves the
  // common case without an extra keypress.
  useEffect(() => {
    if (sessionState === "review") setSuccessLabel(true);
  }, [sessionState]);

  // Reset cycle state if session leaves the recording loop
  useEffect(() => {
    if (sessionState === "idle") {
      setCycleActive(false);
      setCycleCountdown(null);
    }
  }, [sessionState]);

  const saveWith = useCallback((success: boolean | null) => {
    if (sessionState === "review") {
      setSuccessLabel(success);
      episodeSave.mutate({ success });
    }
  }, [sessionState, episodeSave]);

  const handleSpace = useCallback(() => {
    if (sessionState === "ready") {
      if (autoCycle) setCycleActive(true);
      episodeStart.mutate();
    } else if (sessionState === "recording") {
      episodeStop.mutate();
    } else if (sessionState === "review") {
      saveWith(true);
    }
  }, [sessionState, autoCycle, episodeStart, episodeStop, saveWith]);

  const handleDiscard = useCallback(() => {
    if (sessionState === "review") episodeDiscard.mutate();
  }, [sessionState, episodeDiscard]);

  const cancelCycle = useCallback(() => {
    setCycleActive(false);
    setCycleCountdown(null);
  }, []);

  // ---- Auto-cycle timers ----
  // Use refs to avoid re-arming timers when unrelated state updates.
  const stopTimerRef = useRef<number | null>(null);
  const reviewTimerRef = useRef<number | null>(null);
  const countdownTickRef = useRef<number | null>(null);

  useEffect(() => {
    const clearTimers = () => {
      if (stopTimerRef.current !== null) { window.clearTimeout(stopTimerRef.current); stopTimerRef.current = null; }
      if (reviewTimerRef.current !== null) { window.clearTimeout(reviewTimerRef.current); reviewTimerRef.current = null; }
      if (countdownTickRef.current !== null) { window.clearInterval(countdownTickRef.current); countdownTickRef.current = null; }
    };
    if (!cycleActive) { clearTimers(); setCycleCountdown(null); return clearTimers; }

    if (sessionState === "recording") {
      // Auto-stop after the configured duration
      const ms = Math.max(1, autoDurationSec) * 1000;
      stopTimerRef.current = window.setTimeout(() => episodeStop.mutate(), ms);
      // Live countdown for UI
      const start = Date.now();
      setCycleCountdown(autoDurationSec);
      countdownTickRef.current = window.setInterval(() => {
        const remaining = Math.max(0, autoDurationSec - Math.floor((Date.now() - start) / 1000));
        setCycleCountdown(remaining);
      }, 250);
    } else if (sessionState === "review") {
      // Auto-save success after review window; user can override with F/D/Esc
      const ms = Math.max(0, autoReviewSec) * 1000;
      reviewTimerRef.current = window.setTimeout(() => episodeSave.mutate({ success: true }), ms);
      const start = Date.now();
      setCycleCountdown(autoReviewSec);
      countdownTickRef.current = window.setInterval(() => {
        const remaining = Math.max(0, autoReviewSec - Math.floor((Date.now() - start) / 1000));
        setCycleCountdown(remaining);
      }, 250);
    } else if (sessionState === "ready") {
      // Returning from save → start the next episode
      setCycleCountdown(null);
      episodeStart.mutate();
    }

    return clearTimers;
  // episodeStart/Stop/Save are stable mutation hooks; safe to omit
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cycleActive, sessionState, autoDurationSec, autoReviewSec]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "Escape") { cancelCycle(); return; }
      if (e.code === "Space") { e.preventDefault(); handleSpace(); return; }
      if (e.key === "f" || e.key === "F") { saveWith(false); return; }
      if (e.key === "d" || e.key === "D") { handleDiscard(); return; }
      if (e.key === "1") setSuccessLabel(true);
      if (e.key === "2") setSuccessLabel(false);
      if (e.key === "3") setSuccessLabel(null);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleSpace, saveWith, handleDiscard, cancelCycle]);

  const cycleBadge = cycleActive && (
    <Badge className="bg-blue-100 text-blue-700">
      Auto cycle{cycleCountdown !== null ? ` · ${cycleCountdown}s` : ""}
      <button className="ml-2 text-xs underline" onClick={cancelCycle}>cancel (Esc)</button>
    </Badge>
  );

  if (sessionState === "ready") {
    return (
      <div className="space-y-3">
        {cycleBadge}
        <Button variant="destructive" size="lg" onClick={() => { if (autoCycle) setCycleActive(true); episodeStart.mutate(); }}>
          Start Recording (Space){autoCycle ? " · cycle ON" : ""}
        </Button>
      </div>
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
          {cycleBadge}
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
        <div className="flex items-center gap-3">
          <div className="text-lg font-medium text-gray-700">Review Episode</div>
          {cycleBadge}
        </div>
        <div className="flex gap-2">
          <Button size="sm" onClick={() => setSuccessLabel(true)} className={successLabel === true ? "bg-green-600 text-white hover:bg-green-700" : ""} variant={successLabel === true ? "default" : "outline"}>1: Success</Button>
          <Button size="sm" onClick={() => setSuccessLabel(false)} className={successLabel === false ? "bg-red-600 text-white hover:bg-red-700" : ""} variant={successLabel === false ? "destructive" : "outline"}>2: Failure</Button>
          <Button size="sm" onClick={() => setSuccessLabel(null)} className={successLabel === null ? "bg-yellow-600 text-white hover:bg-yellow-700" : ""} variant={successLabel === null ? "default" : "outline"}>3: Skip</Button>
        </div>
        <div className="flex gap-3">
          <Button className="bg-green-600 hover:bg-green-700" onClick={() => saveWith(true)}>Save Success (Space)</Button>
          <Button className="bg-amber-600 text-white hover:bg-amber-700" onClick={() => saveWith(false)}>Save Failure (F)</Button>
          <Button variant="outline" className="bg-gray-600 text-white hover:bg-gray-700" onClick={handleDiscard}>Discard (D)</Button>
        </div>
      </div>
    );
  }

  return null;
}
