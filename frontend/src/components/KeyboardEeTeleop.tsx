import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { WsConnection } from "../api/ws";

const MOTION_KEYS = new Set([
  "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "PageUp", "PageDown",
  "KeyI", "KeyK", "KeyJ", "KeyL", "KeyU", "KeyO", "BracketLeft", "BracketRight",
]);

function axesFromKeys(keys: Set<string>) {
  const axis = (positive: string, negative: string) =>
    Number(keys.has(positive)) - Number(keys.has(negative));
  return {
    axes: [
      axis("ArrowUp", "ArrowDown"),
      axis("ArrowLeft", "ArrowRight"),
      axis("PageUp", "PageDown"),
      axis("KeyI", "KeyK"),
      axis("KeyJ", "KeyL"),
      axis("KeyU", "KeyO"),
    ],
    gripper: axis("BracketRight", "BracketLeft"),
  };
}

export default function KeyboardEeTeleop() {
  const connection = useMemo(() => new WsConnection("/ws/teleop"), []);
  const pressed = useRef(new Set<string>());
  const ready = useRef(false);
  const [connected, setConnected] = useState(false);

  const sendState = useCallback(() => {
    if (!ready.current) return;
    connection.sendJson({ cmd: "ee_axes", ...axesFromKeys(pressed.current) });
  }, [connection]);

  useEffect(() => {
    const unsubscribe = connection.onMessage((message) => {
      if (message.type === "init" && message.input_mode === "ee_delta") {
        ready.current = true;
        setConnected(true);
        sendState();
      }
    });
    const unsubscribeStatus = connection.onStatus((isOpen) => {
      if (isOpen) return;
      ready.current = false;
      pressed.current.clear();
      setConnected(false);
    });
    connection.connect();
    return () => {
      pressed.current.clear();
      if (ready.current) connection.sendJson({ cmd: "stop" });
      ready.current = false;
      unsubscribe();
      unsubscribeStatus();
      connection.disconnect();
    };
  }, [connection, sendState]);

  useEffect(() => {
    const isTextInput = (target: EventTarget | null) =>
      target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement ||
      (target instanceof HTMLElement && target.isContentEditable);

    const onKeyDown = (event: KeyboardEvent) => {
      if (isTextInput(event.target) || !MOTION_KEYS.has(event.code)) return;
      event.preventDefault();
      if (!pressed.current.has(event.code)) {
        pressed.current.add(event.code);
        sendState();
      }
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (!MOTION_KEYS.has(event.code)) return;
      event.preventDefault();
      if (pressed.current.delete(event.code)) sendState();
    };
    const stop = () => {
      if (pressed.current.size === 0) return;
      pressed.current.clear();
      sendState();
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", stop);
    document.addEventListener("visibilitychange", stop);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", stop);
      document.removeEventListener("visibilitychange", stop);
    };
  }, [sendState]);

  return (
    <div className="ml-auto flex items-center gap-3 font-mono text-micro text-steel">
      <span className={connected ? "text-brand-green" : "text-brand-error"}>
        KEY EE {connected ? "READY" : "WAIT"}
      </span>
      <span>XYZ: arrows PgUp/PgDn</span>
      <span>ROT: I/K J/L U/O</span>
      <span>GRIP: [ / ]</span>
    </div>
  );
}
