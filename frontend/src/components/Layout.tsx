import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { useSessionStore } from "../state/session-store";
import { useSessionState } from "../api/queries";
import { Badge } from "./ui/badge";
import { SidebarNavItem } from "./ui/sidebar-nav-item";
import { ErrorBoundary } from "./ErrorBoundary";
import { GoProPendingBadge } from "./GoProPendingBadge";

const navItems = [
  { to: "/datasets", label: "Datasets" },
  { to: "/record", label: "Record" },
  { to: "/inference", label: "Inference" },
  { to: "/settings", label: "Settings" },
];

function SessionBadge() {
  const state = useSessionStore((s) => s.state);
  const robot = useSessionStore((s) => s.robot);
  const variantMap: Record<string, "outline" | "success" | "destructive" | "tag"> = {
    idle: "outline",
    ready: "success",
    recording: "destructive",
    review: "tag",
  };
  return (
    <div className="flex flex-col items-end gap-0.5">
      <Badge variant={variantMap[state] || "outline"} className="text-micro-uppercase uppercase tracking-[0.5px]">
        {state}
      </Badge>
      {state !== "idle" && robot && (
        <span className="text-caption text-stone">{robot}</span>
      )}
    </div>
  );
}

function ConnectionStatus() {
  // Static pill for now — wire to real WS/API health in a follow-up.
  return (
    <div className="flex items-center gap-xs px-md py-xs text-caption text-steel">
      <span className="w-2 h-2 rounded-full bg-brand-green" aria-hidden />
      <span>Connected</span>
    </div>
  );
}

export default function Layout() {
  const { data: apiState } = useSessionState();
  const setSessionState = useSessionStore((s) => s.setSessionState);

  useEffect(() => {
    if (apiState) {
      setSessionState(apiState as unknown as Record<string, unknown>);
    }
  }, [apiState, setSessionState]);

  return (
    <div className="flex h-screen bg-surface-soft">
      <aside className="w-60 bg-canvas border-r border-hairline-soft flex flex-col">
        <div className="px-md py-md border-b border-hairline-soft flex items-center justify-between">
          <h1 className="text-heading-5 text-ink">MimicRec</h1>
          <div className="flex flex-col items-end gap-1">
            <SessionBadge />
            <GoProPendingBadge />
          </div>
        </div>
        <nav className="flex-1 p-xs flex flex-col gap-0.5">
          {navItems.map((item) => (
            <SidebarNavItem key={item.to} to={item.to}>
              {item.label}
            </SidebarNavItem>
          ))}
        </nav>
        <div className="border-t border-hairline-soft">
          <ConnectionStatus />
        </div>
      </aside>
      <main className="flex-1 overflow-auto">
        <div className="max-w-[1280px] mx-auto px-lg py-md">
          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </div>
      </main>
    </div>
  );
}
