import { useEffect, useState } from 'react';
import { getGoProPending } from '../api/queries';
import { Badge } from './ui/badge';

export function GoProPendingBadge() {
  const [pending, setPending] = useState(0);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const n = await getGoProPending();
        if (alive) setPending(n);
      } catch {
        /* swallow polling errors */
      }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // beforeunload warning when pending > 0
  useEffect(() => {
    if (pending === 0) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = `${pending} GoPro download(s) pending. Don't unplug the SD card.`;
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [pending]);

  if (pending === 0) return null;

  return (
    <Badge
      variant="warning"
      title="GoPro DL pending — don't unplug the SD card"
      className="text-micro-uppercase uppercase tracking-[0.5px]"
    >
      GoPro: {pending}
    </Badge>
  );
}
