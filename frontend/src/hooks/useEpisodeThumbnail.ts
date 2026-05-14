import { useEffect, useState } from "react";

const cache = new Map<string, string>(); // key: `${ds}:${idx}:${cam}` → dataURL
const MAX = 50;

/**
 * Generates a poster-frame thumbnail from the episode's video by mounting an
 * offscreen <video>, seeking to t=0.001, drawing it to a <canvas>, and caching
 * the resulting dataURL in memory. Avoids any backend writes and works
 * consistently across browsers (unlike <video preload="metadata">, which often
 * shows black until an explicit seek).
 *
 * Each effect run has its own local `cancelled` flag — a late event from a
 * superseded video (when the user clicks through episodes quickly) cannot
 * write into state. The previous thumbnail is cleared at the top of each
 * cache-miss to avoid showing a stale image during the new load.
 */
export function useEpisodeThumbnail(ds: string | undefined, idx: number | null, cam: string | undefined) {
  const [src, setSrc] = useState<string | null>(null);

  useEffect(() => {
    if (!ds || idx == null || !cam) {
      setSrc(null);
      return;
    }
    const key = `${ds}:${idx}:${cam}`;
    const cached = cache.get(key);
    if (cached) {
      setSrc(cached);
      return;
    }

    // Cache miss → clear current src so the UI doesn't show the previously
    // selected episode's thumbnail while this one loads.
    setSrc(null);

    let cancelled = false;
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.crossOrigin = "anonymous";
    video.preload = "metadata";
    video.src = `/api/datasets/${ds}/episodes/${idx}/video/${cam}`;

    const onLoaded = () => {
      if (cancelled) return;
      try {
        video.currentTime = 0.001;
      } catch {
        finish(null);
      }
    };
    const onSeeked = () => {
      if (cancelled) return;
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth || 320;
      canvas.height = video.videoHeight || 180;
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        finish(null);
        return;
      }
      try {
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const url = canvas.toDataURL("image/jpeg", 0.7);
        if (cache.size >= MAX) {
          const oldest = cache.keys().next().value as string | undefined;
          if (oldest) cache.delete(oldest);
        }
        cache.set(key, url);
        finish(url);
      } catch {
        // toDataURL throws if the canvas is tainted (cross-origin issues).
        finish(null);
      }
    };
    const onError = () => finish(null);

    function detachListeners() {
      video.removeEventListener("loadedmetadata", onLoaded);
      video.removeEventListener("seeked", onSeeked);
      video.removeEventListener("error", onError);
    }

    function finish(url: string | null) {
      detachListeners();
      // Release the network connection.
      video.removeAttribute("src");
      try { video.load(); } catch { /* ignore */ }
      if (!cancelled) setSrc(url);
    }

    video.addEventListener("loadedmetadata", onLoaded);
    video.addEventListener("seeked", onSeeked);
    video.addEventListener("error", onError);

    return () => {
      cancelled = true;
      detachListeners();
      video.removeAttribute("src");
      try { video.load(); } catch { /* ignore */ }
    };
  }, [ds, idx, cam]);

  return src;
}
