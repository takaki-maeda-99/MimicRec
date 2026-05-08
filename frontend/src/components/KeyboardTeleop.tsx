import { useEffect, useRef, useState } from "react";
import { WsConnection } from "../api/ws";

interface Props {
  enabled: boolean;
}

const STEP = 0.05; // rad per keypress

export default function KeyboardTeleop({ enabled }: Props) {
  const connRef = useRef<WsConnection | null>(null);
  const [activeJoint, setActiveJoint] = useState(0);
  const [jointNames, setJointNames] = useState<string[]>([]);
  const [jointPos, setJointPos] = useState<number[]>([]);

  useEffect(() => {
    if (!enabled) return;

    const conn = new WsConnection("/ws/teleop");
    conn.onMessage((msg) => {
      const m = msg as { type?: string; dof?: number; joint_names?: string[]; joint_pos?: number[] };
      if (m.type === "init") {
        setJointNames(m.joint_names || []);
        setJointPos(m.joint_pos || []);
      }
    });
    conn.connect();
    connRef.current = conn;

    return () => {
      conn.disconnect();
      connRef.current = null;
    };
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;

    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      const conn = connRef.current;
      if (!conn) return;

      if (e.key === "ArrowUp" || e.key === "w") {
        e.preventDefault();
        conn.sendJson({ joint: activeJoint, delta: STEP });
        setJointPos((prev) => {
          const next = [...prev];
          next[activeJoint] = (next[activeJoint] || 0) + STEP;
          return next;
        });
      } else if (e.key === "ArrowDown" || e.key === "s") {
        e.preventDefault();
        conn.sendJson({ joint: activeJoint, delta: -STEP });
        setJointPos((prev) => {
          const next = [...prev];
          next[activeJoint] = (next[activeJoint] || 0) - STEP;
          return next;
        });
      } else if (e.key >= "1" && e.key <= "9") {
        setActiveJoint(parseInt(e.key) - 1);
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [enabled, activeJoint]);

  if (!enabled) return null;

  return (
    <div className="bg-canvas-dark text-on-dark rounded-lg p-4 text-sm">
      <div className="font-medium mb-2">Keyboard Teleop</div>
      <div className="text-on-dark-muted text-xs mb-3">
        <span className="text-brand-warn">1-9</span> select joint &middot;{" "}
        <span className="text-brand-warn">W/S</span> or <span className="text-brand-warn">↑/↓</span> move
      </div>
      <div className="space-y-1">
        {jointNames.map((name, i) => (
          <div
            key={i}
            className={`flex justify-between px-2 py-0.5 rounded cursor-pointer ${
              i === activeJoint ? "bg-brand-tag" : "hover:bg-hairline-dark"
            }`}
            onClick={() => setActiveJoint(i)}
          >
            <span>
              <span className="text-on-dark-muted mr-1">{i + 1}</span>
              {name}
            </span>
            <span className="font-mono">{(jointPos[i] || 0).toFixed(3)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
