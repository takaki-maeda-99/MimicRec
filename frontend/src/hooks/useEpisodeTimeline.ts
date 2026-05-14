import { useEffect, useRef, useState, useCallback, type RefObject } from "react";

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
 * playback drives `currentTimeSec` via rVFC (or `timeupdate` fallback). The
 * `seek(t)` function is the *only* way callers should change the master's
 * position — it calls `video.currentTime = t`, and the rVFC/`timeupdate`
 * callback propagates the change back into state. This single-writer
 * invariant prevents the scrubber/state/seek feedback loop described in
 * the design spec.
 */
export function useEpisodeTimeline(masterRef: RefObject<HTMLVideoElement | null>) {
  const [currentTimeSec, setCurrentTimeSec] = useState(0);
  const rvfcHandleRef = useRef<number | null>(null);

  useEffect(() => {
    const video = masterRef.current as VideoWithRVFC | null;
    if (!video) return;

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
      };
    }

    // Fallback: timeupdate (4–15 Hz). Chunky but functional.
    const onTimeUpdate = () => setCurrentTimeSec(video.currentTime);
    video.addEventListener("timeupdate", onTimeUpdate);
    return () => video.removeEventListener("timeupdate", onTimeUpdate);
  }, [masterRef]);

  const seek = useCallback((t: number) => {
    const video = masterRef.current;
    if (!video) return;
    // Setting currentTime triggers a seek → eventually the rVFC/timeupdate
    // callback writes the new value into state. Do NOT setCurrentTimeSec(t)
    // here — that would create a second writer.
    video.currentTime = Math.max(0, t);
  }, [masterRef]);

  return { currentTimeSec, seek };
}
