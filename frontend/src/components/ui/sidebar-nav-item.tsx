import { NavLink } from "react-router-dom";
import { cn } from "../../lib/utils";

interface SidebarNavItemProps {
  to: string;
  /** Section code prefix, e.g. "§01". Required by the new design. */
  code?: string;
  children: React.ReactNode;
  className?: string;
}

export function SidebarNavItem({ to, code, children, className }: SidebarNavItemProps) {
  return (
    <NavLink
      to={to}
      end={false}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-sm rounded-sm px-2.5 py-1.5 text-body-sm-medium transition-colors",
          isActive
            ? "bg-ink text-on-primary"
            : "text-slate hover:bg-surface-soft hover:text-ink",
          className,
        )
      }
    >
      {({ isActive }) => (
        <>
          {code && (
            <span
              className={cn(
                "font-mono text-micro-uppercase",
                isActive ? "text-on-dark-mark" : "text-stone",
              )}
            >
              {code}
            </span>
          )}
          <span>{children}</span>
        </>
      )}
    </NavLink>
  );
}
