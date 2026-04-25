import { useState } from "react";

interface Props {
  ds: string;
  idx: number;
  cam: string;
}

export default function VideoPlayer({ ds, idx, cam }: Props) {
  const [error, setError] = useState(false);
  const src = `/api/datasets/${ds}/episodes/${idx}/video/${cam}`;

  if (error) return null; // Hide if video doesn't exist for this camera

  return (
    <div className="bg-black rounded-lg overflow-hidden">
      <video
        className="w-full"
        controls
        src={src}
        onError={() => setError(true)}
      />
      <div className="px-2 py-1 text-xs text-gray-400 bg-gray-900">{cam}</div>
    </div>
  );
}
