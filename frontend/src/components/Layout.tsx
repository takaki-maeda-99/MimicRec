import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { useSessionStore } from "../state/session-store";
import { useSessionState } from "../api/queries";
import { SidebarNavItem } from "./ui/sidebar-nav-item";
import { ErrorBoundary } from "./ErrorBoundary";
import EStopButton from "./EStopButton";
import SidebarStatus from "./SidebarStatus";

const navItems = [
  { to: "/datasets", code: "§01", label: "Datasets" },
  { to: "/record", code: "§02", label: "Record" },
  { to: "/inference", code: "§03", label: "Inference" },
  { to: "/settings", code: "§04", label: "Settings" },
];

function Brand() {
  return (
    <div className="flex items-center gap-xs">
      <span className="relative w-[18px] h-[18px] rounded-xs bg-ink">
        <span className="absolute -right-0.5 -bottom-0.5 w-[7px] h-[7px] rounded-xs bg-brand-warn" />
      </span>
      <span className="text-heading-5 text-ink tracking-tight">MimicRec</span>
    </div>
  );
}

export default function Layout() {
  const { data: apiState } = useSessionState();
  const setSessionState = useSessionStore((s) => s.setSessionState);
  const robot = useSessionStore((s) => s.robot);
  const state = useSessionStore((s) => s.state);

  useEffect(() => {
    if (apiState) setSessionState(apiState as unknown as Record<string, unknown>);
  }, [apiState, setSessionState]);

  const showEstop = robot === "rebotarm" && state !== "idle";

  return (
    <div className="flex flex-col h-screen bg-surface">
      {import.meta.env.VITE_DEMO === "true" && (
        <div className="bg-amber-500 text-black text-center text-sm py-1 px-2 shrink-0">
          Demo mode — recordings reset on reload.{" "}
          <a
            href="https://github.com/takaki-maeda-99/MimicRec"
            className="underline"
            target="_blank"
            rel="noreferrer"
          >
            View source
          </a>
        </div>
      )}
      <div className="flex flex-1 min-h-0">
        <aside className="w-[220px] flex-shrink-0 bg-canvas border-r border-hairline flex flex-col">
          <div className="px-md py-md border-b border-hairline">
            <Brand />
            <div className="mt-2 font-mono text-micro text-steel tracking-wide">
              {new Date().toISOString().slice(0, 10)}
            </div>
          </div>

          <nav className="px-2 py-md flex flex-col gap-0.5">
            <div className="px-2.5 pb-1 text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
              Index
            </div>
            {navItems.map((item) => (
              <SidebarNavItem key={item.to} to={item.to} code={item.code}>
                {item.label}
              </SidebarNavItem>
            ))}
          </nav>

          <div className="mt-auto flex flex-col gap-md pb-md">
            <SidebarStatus />
            {showEstop && (
              <div className="px-md">
                <EStopButton />
              </div>
            )}
            <div className="px-md flex justify-between font-mono text-micro text-stone tracking-wide pt-md border-t border-hairline-soft">
              <span>v0.42</span>
              <span>build —</span>
            </div>
          </div>
        </aside>

        <main className="flex-1 flex flex-col min-w-0 min-h-0 overflow-auto">
          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
