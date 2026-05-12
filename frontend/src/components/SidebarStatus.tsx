import { useEffect, useState } from "react";
import { useSessionStore } from "../state/session-store";
import { fetchAuthStatus, type AuthStatus } from "../api/cloud";
import { getGoProPending } from "../api/queries";
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
  const gopros = useSessionStore((s) => s.gopros);

  const [auth, setAuth] = useState<AuthStatus | null>(null);
  useEffect(() => {
    let alive = true;
    fetchAuthStatus()
      .then((s) => alive && setAuth(s))
      .catch(() => alive && setAuth(null));
    return () => {
      alive = false;
    };
  }, []);

  const [goproPending, setGoproPending] = useState(0);
  useEffect(() => {
    if (!gopros.length) return;
    let alive = true;
    const tick = async () => {
      try {
        const n = await getGoProPending();
        if (alive) setGoproPending(n);
      } catch {
        /* swallow */
      }
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [gopros.length]);

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
      {gopros.length > 0 && (
        <Row
          k="gopro"
          v={goproPending > 0 ? `${goproPending} pending` : "ready"}
          tone={goproPending > 0 ? "warn" : "ok"}
        />
      )}
    </div>
  );
}
