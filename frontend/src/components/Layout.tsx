import { NavLink, Outlet } from "react-router-dom";
import { useSessionStore } from "../state/session-store";
import { Badge } from "./ui/badge";

const navItems = [
  { to: "/datasets", label: "Datasets" },
  { to: "/record", label: "Record" },
];

function SessionBadge() {
  const state = useSessionStore((s) => s.state);
  const variantMap: Record<string, "outline" | "success" | "destructive" | "warning"> = {
    idle: "outline",
    ready: "success",
    recording: "destructive",
    review: "warning",
  };
  return (
    <Badge variant={variantMap[state] || "outline"}>
      {state.toUpperCase()}
    </Badge>
  );
}

export default function Layout() {
  return (
    <div className="flex h-screen bg-gray-50">
      <aside className="w-56 bg-white border-r border-gray-200 flex flex-col">
        <div className="p-4 border-b border-gray-200 flex items-center justify-between">
          <h1 className="text-lg font-bold text-gray-900">MimicRec</h1>
          <SessionBadge />
        </div>
        <nav className="flex-1 p-2">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `block px-3 py-2 rounded-md text-sm font-medium ${
                  isActive
                    ? "bg-blue-50 text-blue-700"
                    : "text-gray-700 hover:bg-gray-100"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
