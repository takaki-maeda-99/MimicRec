import { forwardRef, useState } from "react";

interface Props {
  ds: string;
  idx: number;
  cam: string;
  /** Master video gets default controls. Secondaries get `controls={false}`
   *  and a transparent overlay that swallows pointer events.
   *  (Timeline state is driven from useEpisodeTimeline reading directly from
   *  the master video's ref via rVFC/timeupdate — VideoPlayer itself doesn't
   *  emit time updates.) */
  isMaster?: boolean;
}

const VideoPlayer = forwardRef<HTMLVideoElement, Props>(function VideoPlayer(
  { ds, idx, cam, isMaster = true },
  ref,
) {
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
          <>
            <video
              ref={ref}
              className="absolute inset-0 w-full h-full object-contain"
              controls={isMaster}
              src={src}
              onError={() => setError(true)}
            />
            {!isMaster && (
              <div
                className="absolute inset-0 cursor-default"
                onClick={(e) => e.preventDefault()}
                aria-hidden
              />
            )}
          </>
        )}
      </div>
      <div className="px-2 py-1 text-caption text-stone bg-surface">{cam}</div>
    </div>
  );
});

export default VideoPlayer;
