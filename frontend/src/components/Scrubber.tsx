interface Props {
  durationSec: number;
  currentTimeSec: number;
  onSeek: (t: number) => void;
}

export function Scrubber({ durationSec, currentTimeSec, onSeek }: Props) {
  const fraction = durationSec > 0 ? Math.min(1, Math.max(0, currentTimeSec / durationSec)) : 0;

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const fx = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    onSeek(fx * durationSec);
  };

  const handleDrag = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.buttons === 0) return; // not dragging
    handleClick(e);
  };

  return (
    <div className="flex-shrink-0 h-9 px-md flex items-center gap-md border-t border-hairline-soft bg-surface-soft">
      <span className="font-mono text-caption text-steel min-w-[44px]">00:00</span>
      <div
        className="flex-1 h-1 bg-hairline rounded-full relative cursor-pointer"
        onClick={handleClick}
        onMouseMove={handleDrag}
      >
        <div className="absolute left-0 top-0 bottom-0 bg-ink rounded-full" style={{ width: `${fraction * 100}%` }} />
        <div
          className="absolute -top-1.5 w-3 h-3 -translate-x-1/2 rounded-full bg-canvas border-2 border-ink"
          style={{ left: `${fraction * 100}%` }}
        />
      </div>
      <span className="font-mono text-caption text-steel min-w-[88px] text-right">
        {fmt(currentTimeSec)} / {fmt(durationSec)}
      </span>
    </div>
  );
}

function fmt(sec: number): string {
  const mm = Math.floor(sec / 60).toString().padStart(2, "0");
  const ss = (sec % 60).toFixed(1).padStart(4, "0");
  return `${mm}:${ss}`;
}
