import { useSessionStore } from "../../state/session-store";
import CameraPreview from "../CameraPreview";

export function CameraColumn() {
  // session-store exposes `cameras: string[]` (camera names, e.g. ["front", "wrist"])
  const cameras = useSessionStore((s) => s.cameras);
  const previewEnabled = useSessionStore((s) => s.previewEnabled);

  if (!previewEnabled) {
    return (
      <section className="flex-1 min-w-0 bg-surface flex items-center justify-center">
        <p className="text-body-sm text-stone">
          Camera preview disabled for this session.
        </p>
      </section>
    );
  }

  if (cameras.length === 0) {
    return (
      <section className="flex-1 min-w-0 bg-surface flex items-center justify-center">
        <p className="text-body-sm text-stone">No cameras available.</p>
      </section>
    );
  }

  const cols = cameras.length === 1 ? "grid-cols-1" : "grid-cols-2";

  return (
    <section className="flex-1 min-w-0 bg-surface p-md flex flex-col gap-sm">
      <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
        Cameras (live)
      </div>
      <div className={`grid ${cols} gap-sm flex-1 min-h-0`}>
        {cameras.map((cam) => (
          <CameraPreview key={cam} camName={cam} />
        ))}
      </div>
    </section>
  );
}
