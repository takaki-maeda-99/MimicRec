import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { WsConnection } from "../api/ws";

interface StatePayload {
  joint_pos?: number[];
  joint_vel?: number[];
  ee_pos?: number[];
  ee_rotvec?: number[];
  gripper_pos?: number;
  t_mono_ns?: number;
}

interface Buffer {
  capacity: number;
  snapshots: number[][]; // [joint_idx][sample]
  version: number;
}

function makeBuffer(numJoints: number, capacity: number): Buffer {
  return {
    capacity,
    snapshots: Array.from({ length: numJoints }, () => []),
    version: 0,
  };
}

function push(buf: Buffer, sample: number[]) {
  while (buf.snapshots.length < sample.length) buf.snapshots.push([]);
  sample.forEach((v, i) => {
    const series = buf.snapshots[i];
    series.push(v);
    if (series.length > buf.capacity) series.shift();
  });
  buf.version += 1;
}

/**
 * Subscribe to /ws/state and keep a rolling buffer of the last
 * `secondsWindow` seconds of joint positions. Designed for sparkline
 * consumers; non-recording sessions are fine — the buffer simply stays
 * empty until samples arrive.
 *
 * Capacity is conservative: at 100 Hz × 6 s = 600 samples per joint.
 * If perf matters later, downsample at push time.
 */
export function useJointHistory(
  enabled: boolean,
  numJoints: number,
  secondsWindow = 6,
  hz = 100,
) {
  const capacity = secondsWindow * hz;
  const bufRef = useRef<Buffer>(makeBuffer(numJoints, capacity));
  const listenersRef = useRef<Set<() => void>>(new Set());
  const [numJointsObserved, setNumJointsObserved] = useState(numJoints);

  // Re-init buffer if numJoints changes.
  useEffect(() => {
    bufRef.current = makeBuffer(Math.max(numJoints, numJointsObserved), capacity);
    listenersRef.current.forEach((l) => l());
  }, [numJoints, capacity, numJointsObserved]);

  // Open / close the WS subscription as `enabled` flips.
  useEffect(() => {
    if (!enabled) return;
    const conn = new WsConnection("/ws/state");
    conn.onMessage((msg) => {
      const m = msg as StatePayload;
      if (!m.joint_pos || !m.joint_pos.length) return;
      if (m.joint_pos.length > numJointsObserved) {
        setNumJointsObserved(m.joint_pos.length);
      }
      push(bufRef.current, m.joint_pos);
      listenersRef.current.forEach((l) => l());
    });
    conn.connect();
    return () => conn.disconnect();
  }, [enabled, numJointsObserved]);

  const subscribe = (cb: () => void) => {
    listenersRef.current.add(cb);
    return () => listenersRef.current.delete(cb);
  };
  const getSnapshot = () => bufRef.current.version;
  useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  return bufRef.current.snapshots;
}
