import { useEffect, useRef } from "react";
import { WsConnection } from "../api/ws.ts";

interface Props {
  camName: string;
}

export default function CameraPreview({ camName }: Props) {
  const imgRef = useRef<HTMLImageElement>(null);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    const conn = new WsConnection(`/ws/cameras/${camName}`, true);
    const unsub = conn.onMessage((msg) => {
      const blob = msg.blob as Blob | undefined;
      if (blob && imgRef.current) {
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        const url = URL.createObjectURL(blob);
        urlRef.current = url;
        imgRef.current.src = url;
      }
    });
    conn.connect();
    return () => {
      unsub();
      conn.disconnect();
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, [camName]);

  return (
    <div className="bg-black rounded-lg overflow-hidden">
      <img ref={imgRef} alt={camName} className="w-full h-auto" />
      <div className="px-2 py-1 text-xs text-gray-400">{camName}</div>
    </div>
  );
}
