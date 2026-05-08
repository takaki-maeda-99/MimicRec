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
    <div className="bg-black rounded-lg overflow-hidden">
      {error ? (
        <div className="flex items-center justify-center h-48 text-steel text-sm">
          Video unavailable for {cam}
        </div>
      ) : (
        <video
          className="w-full"
          controls
          src={src}
          onError={() => setError(true)}
        />
      )}
      <div className="px-2 py-1 text-caption text-stone bg-canvas-dark">{cam}</div>
    </div>
  );
}
