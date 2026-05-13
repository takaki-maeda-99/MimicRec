import { useEffect, useRef, useSyncExternalStore } from "react";
import { WsConnection } from "../api/ws";

interface StatePayload {
  ee_pos?: number[];
}

interface Buffer {
  capacity: number;
  xs: number[];
  ys: number[];
  version: number;
}

function makeBuffer(capacity: number): Buffer {
  return { capacity, xs: [], ys: [], version: 0 };
}

function push(buf: Buffer, x: number, y: number) {
  buf.xs.push(x);
  buf.ys.push(y);
  if (buf.xs.length > buf.capacity) buf.xs.shift();
  if (buf.ys.length > buf.capacity) buf.ys.shift();
  buf.version += 1;
}

/**
 * Subscribe to /ws/state and keep a rolling buffer of the last
 * `secondsWindow` seconds of end-effector (x, y) positions.
 * Mirrors useJointHistory's buffering pattern; designed for the
 * RecordPage XY trajectory plot.
 *
 * Returns parallel `xs` and `ys` arrays of equal length. Empty until
 * samples arrive (e.g. before a session starts).
 */
export function useEeXyHistory(
  enabled: boolean,
  secondsWindow = 8,
  hz = 100,
): { xs: number[]; ys: number[] } {
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
      if (!m.ee_pos || m.ee_pos.length < 2) return;
      push(bufRef.current, m.ee_pos[0], m.ee_pos[1]);
      listenersRef.current.forEach((l) => l());
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

  return { xs: bufRef.current.xs, ys: bufRef.current.ys };
}
