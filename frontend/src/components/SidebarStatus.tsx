import { useEffect, useState } from "react";
import { useSessionStore } from "../state/session-store";
import { fetchAuthStatus, type AuthStatus } from "../api/cloud";
import { cn } from "../lib/utils";

function Row({
  k,
  v,
  tone,
}: {
  k: string;
  v: React.ReactNode;
  tone?: "ok" | "warn" | "rec" | "idle";
}) {
  const color =
    tone === "ok"
      ? "text-brand-green-deep"
      : tone === "warn"
      ? "text-brand-warn"
      : tone === "rec"
      ? "text-brand-error"
      : "text-ink";
  return (
    <div className="flex items-baseline justify-between font-mono text-micro tracking-[0.04em]">
      <span className="text-steel">{k}</span>
      <span className={cn("flex items-center gap-1.5", color)}>
        {tone === "rec" && <span className="w-1.5 h-1.5 rounded-full bg-brand-error animate-pulse" />}
        {v}
      </span>
    </div>
  );
}

export default function SidebarStatus() {
  const robot = useSessionStore((s) => s.robot);
  const sessionState = useSessionStore((s) => s.state);

  const [auth, setAuth] = useState<AuthStatus | null>(null);
  useEffect(() => {
    let alive = true;
    const refresh = () =>
      fetchAuthStatus()
        .then((s) => alive && setAuth(s))
        .catch(() => alive && setAuth(null));
    refresh();
    const onChange = () => refresh();
    window.addEventListener("hf-auth-changed", onChange);
    return () => {
      alive = false;
      window.removeEventListener("hf-auth-changed", onChange);
    };
  }, []);

  return (
    <div className="flex flex-col gap-1 px-md">
      <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold pb-1">
        Status
      </div>
      <Row
        k="hub"
        v={auth?.authenticated ? `@${auth.username ?? "—"}` : "—"}
        tone={auth?.authenticated ? "ok" : undefined}
      />
      <Row k="robot" v={robot ?? "not connected"} tone={robot ? "ok" : undefined} />
      <Row
        k="session"
        v={sessionState}
        tone={sessionState === "recording" ? "rec" : sessionState === "idle" ? "idle" : "ok"}
      />
    </div>
  );
}
