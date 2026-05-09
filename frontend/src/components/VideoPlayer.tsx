import { useState } from "react";

interface Props {
  ds: string;
  idx: number;
  cam: string;
}

export default function VideoPlayer({ ds, idx, cam }: Props) {
  const [error, setError] = useState(false);
  const src = `/api/datasets/${ds}/episodes/${idx}/video/${cam}`;

  return (
    <div className="rounded-lg overflow-hidden border border-hairline bg-canvas">
      <div className="relative bg-black aspect-square">
        {error ? (
          <div className="absolute inset-0 flex items-center justify-center text-steel text-sm">
            Video unavailable for {cam}
          </div>
        ) : (
          <video
            className="absolute inset-0 w-full h-full object-contain"
            controls
            src={src}
            onError={() => setError(true)}
          />
        )}
      </div>
      <div className="px-2 py-1 text-caption text-stone bg-surface">{cam}</div>
    </div>
  );
}
