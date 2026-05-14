import { useEffect } from "react";

/**
 * Slaves a secondary <video> to a master <video>. Mirrors play/pause/rate/ended
 * events and seeks via guarded currentTime writes (readyState + !seeking +
 * > 1/fps drift threshold).
 *
 * Takes both video elements directly so that the effects re-bind when either
 * element remounts (e.g. when the underlying camera key changes).
 */
export function useSecondaryVideoSync(
  secondary: HTMLVideoElement | null,
  master: HTMLVideoElement | null,
  currentTimeSec: number,
  fps: number,
) {
  // Mirror play/pause/rate
  useEffect(() => {
    if (!master || !secondary) return;

    const onPlay = () => secondary.play().catch(() => {});
    const onPause = () => secondary.pause();
    const onRate = () => { secondary.playbackRate = master.playbackRate; };
    const onEnded = () => secondary.pause();

    master.addEventListener("play", onPlay);
    master.addEventListener("pause", onPause);
    master.addEventListener("ratechange", onRate);
    master.addEventListener("ended", onEnded);

    // Initial sync
    secondary.playbackRate = master.playbackRate;
    if (!master.paused) secondary.play().catch(() => {});

    return () => {
      master.removeEventListener("play", onPlay);
      master.removeEventListener("pause", onPause);
      master.removeEventListener("ratechange", onRate);
      master.removeEventListener("ended", onEnded);
    };
  }, [master, secondary]);

  // Mirror seeks (guarded)
  useEffect(() => {
    if (!secondary) return;
    if (secondary.readyState < 1 /* HAVE_METADATA */) return;
    if (secondary.seeking) return;
    const frameTime = 1 / Math.max(1, fps);
    if (Math.abs(secondary.currentTime - currentTimeSec) <= frameTime) return;
    secondary.currentTime = currentTimeSec;
  }, [secondary, currentTimeSec, fps]);
}
