type Subscriber = (blob: Blob) => void;

let started = false;
let video: HTMLVideoElement | null = null;
const subscribers = new Set<Subscriber>();
let encoding = false;

function makeFallbackPrompt(onUserGesture: () => void) {
  const div = document.createElement("div");
  div.style.cssText = [
    "position:fixed", "right:16px", "bottom:16px",
    "background:#222", "color:#fff", "padding:10px 14px",
    "border-radius:8px", "font:14px system-ui", "cursor:pointer",
    "z-index:99999", "box-shadow:0 4px 12px rgba(0,0,0,0.3)",
  ].join(";");
  div.textContent = "Click to enable demo preview";
  div.addEventListener("click", () => {
    onUserGesture();
    div.remove();
  });
  document.body.appendChild(div);
}

async function ensureStarted() {
  if (started) return;
  started = true;

  video = document.createElement("video");
  video.src = `${import.meta.env.BASE_URL}demo/episode_0/cam_front.mp4`;
  video.muted = true;
  video.loop = true;
  video.playsInline = true;
  video.style.display = "none";
  document.body.appendChild(video);

  try {
    await video.play();
  } catch {
    makeFallbackPrompt(() => {
      void video?.play();
    });
  }

  const hasOffscreen = typeof OffscreenCanvas !== "undefined";
  const canvas: OffscreenCanvas | HTMLCanvasElement = hasOffscreen
    ? new OffscreenCanvas(224, 224)
    : (() => {
        const c = document.createElement("canvas");
        c.width = 224;
        c.height = 224;
        return c;
      })();
  const ctx = (canvas as any).getContext("2d") as
    | CanvasRenderingContext2D
    | OffscreenCanvasRenderingContext2D;

  const supportsRVFC = "requestVideoFrameCallback" in HTMLVideoElement.prototype;

  const emit = async () => {
    if (encoding || subscribers.size === 0 || !video) return;
    encoding = true;
    ctx.drawImage(video, 0, 0, 224, 224);
    let blob: Blob;
    if (hasOffscreen) {
      blob = await (canvas as OffscreenCanvas).convertToBlob({ type: "image/jpeg", quality: 0.85 });
    } else {
      blob = await new Promise<Blob>((resolve) =>
        (canvas as HTMLCanvasElement).toBlob((b) => resolve(b!), "image/jpeg", 0.85),
      );
    }
    subscribers.forEach((fn) => fn(blob));
    encoding = false;
  };

  if (supportsRVFC) {
    const tick = () => {
      void emit();
      video?.requestVideoFrameCallback(tick);
    };
    video.requestVideoFrameCallback(tick);
  } else {
    setInterval(() => void emit(), 33);
  }
}

export function subscribeFrames(fn: Subscriber): () => void {
  void ensureStarted();
  subscribers.add(fn);
  return () => {
    subscribers.delete(fn);
  };
}
