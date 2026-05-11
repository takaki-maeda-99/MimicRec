import { useEffect, useCallback, useState, useRef } from "react";
import { useEpisodeStart, useEpisodeStop, useEpisodeSave, useEpisodeDiscard, getGoProPending } from "../api/queries.ts";
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
  // GoPro DL queue depth. Backend refuses episode/start while > 0 to prevent
  // USB-bandwidth contention with an in-flight download from the previous
  // episode. Auto-cycle waits on this; manual record button is disabled.
  const [goproPending, setGoproPending] = useState(0);

  // Poll pending count whenever the user is between episodes, so both auto-
  // cycle and the manual button stay responsive.
  useEffect(() => {
    if (sessionState !== "ready" && sessionState !== "review") return;
    let alive = true;
    const tick = async () => {
      try {
        const n = await getGoProPending();
        if (alive) setGoproPending(n);
      } catch {
        /* swallow polling errors */
      }
    };
    tick();
    const id = window.setInterval(tick, 500);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [sessionState]);

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
    if (sessionState !== "review") return;
    // Mirror the disabled-button behavior for keyboard shortcuts (Space/F):
    // backend rejects with 409 when goproPending > 0, but silent mutation
    // errors leave the user confused about why nothing happened. Surface
    // the wait through the button label instead.
    if (goproPending > 0) return;
    setSuccessLabel(success);
    episodeSave.mutate({ success });
  }, [sessionState, episodeSave, goproPending]);

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
      // Auto-save success after review window; user can override with F/D/Esc.
      // BUT: the backend rejects episode/save with 409 while the GoPro DL is
      // still in flight, otherwise the parquet metadata commits an episode
      // whose mp4 may never land in the dataset (DL timeout / ffmpeg failure
      // on truncated file). Defer the timer until pending reaches 0; the
      // polling effect re-runs this useEffect when goproPending changes.
      if (goproPending > 0) {
        setCycleCountdown(null);
        return clearTimers;
      }
      const ms = Math.max(0, autoReviewSec) * 1000;
      reviewTimerRef.current = window.setTimeout(() => episodeSave.mutate({ success: true }), ms);
      const start = Date.now();
      setCycleCountdown(autoReviewSec);
      countdownTickRef.current = window.setInterval(() => {
        const remaining = Math.max(0, autoReviewSec - Math.floor((Date.now() - start) / 1000));
        setCycleCountdown(remaining);
      }, 250);
    } else if (sessionState === "ready") {
      // Returning from save → start the next episode, but wait for any GoPro
      // DL to fully drain first. The backend refuses episode/start with 409
      // while pending > 0; without this gate auto-cycle would loop on errors
      // and (worse) trigger the very USB contention it's trying to avoid.
      if (goproPending > 0) {
        setCycleCountdown(null);
        // The polling effect updates goproPending; this useEffect re-runs
        // and retries the check until it reaches zero.
        return clearTimers;
      }
      setCycleCountdown(null);
      episodeStart.mutate();
    }

    return clearTimers;
  // episodeStart/Stop/Save are stable mutation hooks; safe to omit
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cycleActive, sessionState, autoDurationSec, autoReviewSec, goproPending]);

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
    <Badge variant="tag" className="gap-2">
      Auto cycle{cycleCountdown !== null ? ` · ${cycleCountdown}s` : ""}
      <button className="ml-2 text-caption underline" onClick={cancelCycle}>
        cancel (Esc)
      </button>
    </Badge>
  );

  if (sessionState === "ready") {
    const blocked = goproPending > 0;
    return (
      <div className="flex flex-col gap-sm">
        {cycleBadge}
        {blocked && cycleActive && (
          <Badge variant="warning" className="gap-2">
            GoPro 転送中... 残 {goproPending}
          </Badge>
        )}
        <Button
          size="lg"
          className="!bg-brand-error !text-on-dark hover:!bg-brand-error/90 disabled:!opacity-60"
          disabled={blocked}
          title={blocked ? "GoPro mp4 を転送中。完了後に再度押してください。" : undefined}
          onClick={() => {
            if (autoCycle) setCycleActive(true);
            episodeStart.mutate();
          }}
        >
          {blocked
            ? `GoPro 転送中... 残 ${goproPending}`
            : `Start Recording (Space)${autoCycle ? " · cycle ON" : ""}`}
        </Button>
      </div>
    );
  }

  if (sessionState === "recording") {
    const effectiveFps = fps ?? 30;
    return (
      <div className="flex flex-col gap-sm">
        <div className="flex items-center gap-md">
          <Badge variant="destructive" className="gap-2">
            <span className="w-2 h-2 bg-on-dark rounded-full animate-pulse" />
            Recording
          </Badge>
          {progress && (
            <span className="text-body-sm text-slate">
              {progress.num_frames} frames &middot; {(progress.num_frames / effectiveFps).toFixed(1)}s
            </span>
          )}
          {cycleBadge}
        </div>
        <Button size="lg" onClick={() => episodeStop.mutate()}>
          Stop Recording (Space)
        </Button>
      </div>
    );
  }

  if (sessionState === "review") {
    const saveBlocked = goproPending > 0;
    const saveTitle = saveBlocked
      ? "GoPro mp4 を転送中。完了後に保存可能になります。"
      : undefined;
    return (
      <div className="flex flex-col gap-md">
        <div className="flex items-center gap-sm">
          <div className="text-heading-5 text-charcoal">Review Episode</div>
          {cycleBadge}
          {saveBlocked && (
            <Badge variant="warning" className="gap-2">
              GoPro 転送中... 残 {goproPending}
            </Badge>
          )}
        </div>
        <div className="flex gap-xs">
          <Button
            size="sm"
            variant={successLabel === true ? "primary" : "secondary"}
            className={successLabel === true ? "!bg-brand-green !text-primary" : ""}
            onClick={() => setSuccessLabel(true)}
          >
            1: Success
          </Button>
          <Button
            size="sm"
            variant={successLabel === false ? "primary" : "secondary"}
            className={successLabel === false ? "!bg-brand-error !text-on-dark" : ""}
            onClick={() => setSuccessLabel(false)}
          >
            2: Failure
          </Button>
          <Button
            size="sm"
            variant={successLabel === null ? "primary" : "secondary"}
            className={successLabel === null ? "!bg-brand-warn !text-on-dark" : ""}
            onClick={() => setSuccessLabel(null)}
          >
            3: Skip
          </Button>
        </div>
        <div className="flex gap-sm">
          <Button
            className="!bg-brand-green !text-primary hover:!bg-brand-green-deep disabled:!opacity-60"
            disabled={saveBlocked}
            title={saveTitle}
            onClick={() => saveWith(true)}
          >
            {saveBlocked ? `GoPro 転送中... 残 ${goproPending}` : "Save Success (Space)"}
          </Button>
          <Button
            className="!bg-brand-warn !text-on-dark disabled:!opacity-60"
            disabled={saveBlocked}
            title={saveTitle}
            onClick={() => saveWith(false)}
          >
            {saveBlocked ? `GoPro 転送中... 残 ${goproPending}` : "Save Failure (F)"}
          </Button>
          <Button variant="secondary" onClick={handleDiscard}>
            Discard (D)
          </Button>
        </div>
      </div>
    );
  }

  return null;
}
