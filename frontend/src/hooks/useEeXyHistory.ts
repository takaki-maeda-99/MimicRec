import { useEffect, useRef, useSyncExternalStore } from "react";
import { WsConnection } from "../api/ws";

interface StatePayload {
  ee_pos?: number[];
}

interface Buffer {
  capacity: number;
  xs: number[];
  ys: number[];
  zs: number[];
  version: number;
  lastNotifyMs: number;
}

const NOTIFY_INTERVAL_MS = 100; // 10 fps visual refresh — buffer still grows at WS rate

function makeBuffer(capacity: number): Buffer {
  return { capacity, xs: [], ys: [], zs: [], version: 0, lastNotifyMs: 0 };
}

function push(buf: Buffer, x: number, y: number, z: number): boolean {
  buf.xs.push(x);
  buf.ys.push(y);
  buf.zs.push(z);
  if (buf.xs.length > buf.capacity) buf.xs.shift();
  if (buf.ys.length > buf.capacity) buf.ys.shift();
  if (buf.zs.length > buf.capacity) buf.zs.shift();
  const now = performance.now();
  if (now - buf.lastNotifyMs >= NOTIFY_INTERVAL_MS) {
    buf.version += 1;
    buf.lastNotifyMs = now;
    return true;
  }
  return false;
}

/**
 * Subscribe to /ws/state and keep a rolling buffer of the last
 * `secondsWindow` seconds of end-effector (x, y, z) positions.
 * Mirrors useJointHistory's buffering pattern with a 10 fps notify
 * throttle so consumers don't re-render at the WS sample rate.
 *
 * Returns parallel `xs`, `ys`, `zs` arrays of equal length. Empty until
 * samples arrive (e.g. before a session starts).
 */
export function useEeXyHistory(
  enabled: boolean,
  secondsWindow = 8,
  hz = 100,
): { xs: number[]; ys: number[]; zs: number[] } {
  const capacity = secondsWindow * hz;
  const bufRef = useRef<Buffer>(makeBuffer(capacity));
  const listenersRef = useRef<Set<() => void>>(new Set());

  useEffect(() => {
    bufRef.current = makeBuffer(capacity);
    listenersRef.current.forEach((l) => l());
  }, [capacity]);

  useEffect(() => {
    if (!enabled) return;
    const conn = new WsConnection("/ws/state");
    conn.onMessage((msg) => {
      const m = msg as StatePayload;
      if (!m.ee_pos || m.ee_pos.length < 3) return;
      if (push(bufRef.current, m.ee_pos[0], m.ee_pos[1], m.ee_pos[2])) {
        listenersRef.current.forEach((l) => l());
      }
    });
    conn.connect();
    return () => conn.disconnect();
  }, [enabled]);

  const subscribe = (cb: () => void) => {
    listenersRef.current.add(cb);
    return () => listenersRef.current.delete(cb);
  };
  const getSnapshot = () => bufRef.current.version;
  useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  return {
    xs: bufRef.current.xs,
    ys: bufRef.current.ys,
    zs: bufRef.current.zs,
  };
}
