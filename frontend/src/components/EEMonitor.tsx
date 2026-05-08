import { useEffect, useRef, useState } from "react";
import { WsConnection } from "../api/ws.ts";

interface StatePayload {
  joint_pos?: number[];
  joint_vel?: number[];
  ee_pos?: number[];
  ee_rotvec?: number[];
  gripper_pos?: number;
  t_mono_ns?: number;
}

interface Props {
  enabled: boolean;
}

const FMT = (n: number, w = 7, p = 3) =>
  (n >= 0 ? " " : "") + n.toFixed(p).padStart(w);

export default function EEMonitor({ enabled }: Props) {
  const [pos, setPos] = useState<number[] | null>(null);
  const [rot, setRot] = useState<number[] | null>(null);
  const [grip, setGrip] = useState<number | null>(null);
  const [delta, setDelta] = useState<number[] | null>(null);
  const lastPosRef = useRef<number[] | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const conn = new WsConnection("/ws/state");
    conn.onMessage((msg) => {
      const m = msg as StatePayload;
      if (m.ee_pos) {
        setPos(m.ee_pos);
        if (lastPosRef.current && lastPosRef.current.length === 3) {
          const d = m.ee_pos.map((v, i) => v - lastPosRef.current![i]);
          setDelta(d);
        }
        lastPosRef.current = m.ee_pos;
      }
      if (m.ee_rotvec) setRot(m.ee_rotvec);
      if (typeof m.gripper_pos === "number") setGrip(m.gripper_pos);
    });
    conn.connect();
    return () => {
      conn.disconnect();
      lastPosRef.current = null;
    };
  }, [enabled]);

  // Hide entirely if backend never sent EE — robot has no kinematics block.
  if (!enabled) return null;
  if (pos === null && rot === null) {
    return (
      <div className="text-xs text-stone">
        EE monitor: waiting for state… (configure <code>kinematics:</code> in robot YAML)
      </div>
    );
  }

  return (
    <div className="border border-hairline rounded-md p-3 bg-surface-soft font-mono text-xs">
      <div className="font-medium text-charcoal mb-2 font-sans">End-effector (live)</div>
      <table className="w-full">
        <tbody>
          {pos && (
            <tr>
              <td className="text-steel pr-3">pos [m]</td>
              <td>x={FMT(pos[0])}</td>
              <td>y={FMT(pos[1])}</td>
              <td>z={FMT(pos[2])}</td>
            </tr>
          )}
          {delta && (
            <tr>
              <td className="text-steel pr-3">Δ pos</td>
              <td>{FMT(delta[0] * 1000, 7, 1)}mm</td>
              <td>{FMT(delta[1] * 1000, 7, 1)}mm</td>
              <td>{FMT(delta[2] * 1000, 7, 1)}mm</td>
            </tr>
          )}
          {rot && (
            <tr>
              <td className="text-steel pr-3">rotvec</td>
              <td>wx={FMT(rot[0])}</td>
              <td>wy={FMT(rot[1])}</td>
              <td>wz={FMT(rot[2])}</td>
            </tr>
          )}
          {grip !== null && (
            <tr>
              <td className="text-steel pr-3">gripper</td>
              <td colSpan={3}>{FMT(grip, 7, 1)}%</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
