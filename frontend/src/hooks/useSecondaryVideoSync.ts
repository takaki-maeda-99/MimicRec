import { useEffect, type RefObject } from "react";

/**
 * Slaves a secondary <video> to a master <video>:
 *   - mirrors play/pause/rate/ended events from master
 *   - mirrors seeks via guarded currentTime writes (readyState + !seeking +
 *     > 1/fps drift threshold) to prevent seek storms when the master is
 *     emitting per-frame timeupdates.
 */
export function useSecondaryVideoSync(
  secondaryRef: RefObject<HTMLVideoElement | null>,
  masterRef: RefObject<HTMLVideoElement | null>,
  currentTimeSec: number,
  fps: number,
) {
  // Mirror play/pause/rate
  useEffect(() => {
    const master = masterRef.current;
    const secondary = secondaryRef.current;
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
  }, [masterRef, secondaryRef]);

  // Mirror seeks (guarded)
  useEffect(() => {
    const secondary = secondaryRef.current;
    if (!secondary) return;
    if (secondary.readyState < 1 /* HAVE_METADATA */) return;
    if (secondary.seeking) return;
    const frameTime = 1 / Math.max(1, fps);
    if (Math.abs(secondary.currentTime - currentTimeSec) <= frameTime) return;
    secondary.currentTime = currentTimeSec;
  }, [secondaryRef, currentTimeSec, fps]);
}
