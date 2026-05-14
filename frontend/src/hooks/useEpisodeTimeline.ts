import { useEffect, useRef, useState, useCallback } from "react";

interface VideoFrameCallbackMetadata {
  mediaTime: number;
  presentedFrames: number;
}

type VideoWithRVFC = HTMLVideoElement & {
  requestVideoFrameCallback?: (cb: (now: number, meta: VideoFrameCallbackMetadata) => void) => number;
  cancelVideoFrameCallback?: (handle: number) => void;
};

/**
 * Master timeline state for synchronized playback. The master <video>'s
 * playback drives `currentTimeSec` via rVFC (or `timeupdate` fallback).
 * `seek(t)` is the *only* writer to the master's currentTime; the rVFC /
 * timeupdate callback propagates the change back into state.
 *
 * Takes the master <video> element directly (not a RefObject) so that the
 * effect re-binds when the element remounts (e.g. when the underlying camera
 * key changes between episodes).
 */
export function useEpisodeTimeline(master: HTMLVideoElement | null) {
  const [currentTimeSec, setCurrentTimeSec] = useState(0);
  const rvfcHandleRef = useRef<number | null>(null);

  useEffect(() => {
    if (!master) return;
    const video = master as VideoWithRVFC;
    setCurrentTimeSec(video.currentTime); // initial sync

    if (typeof video.requestVideoFrameCallback === "function") {
      const onFrame = (_now: number, meta: VideoFrameCallbackMetadata) => {
        setCurrentTimeSec(meta.mediaTime);
        rvfcHandleRef.current = video.requestVideoFrameCallback!(onFrame);
      };
      rvfcHandleRef.current = video.requestVideoFrameCallback(onFrame);
      return () => {
        if (rvfcHandleRef.current != null && video.cancelVideoFrameCallback) {
          video.cancelVideoFrameCallback(rvfcHandleRef.current);
        }
        rvfcHandleRef.current = null;
      };
    }

    const onTimeUpdate = () => setCurrentTimeSec(video.currentTime);
    video.addEventListener("timeupdate", onTimeUpdate);
    return () => video.removeEventListener("timeupdate", onTimeUpdate);
  }, [master]);

  const seek = useCallback((t: number) => {
    if (!master) return;
    master.currentTime = Math.max(0, t);
  }, [master]);

  return { currentTimeSec, seek };
}
