import { NavLink } from "react-router-dom";
import { cn } from "../../lib/utils";

interface SidebarNavItemProps {
  to: string;
  children: React.ReactNode;
  className?: string;
}

export function SidebarNavItem({ to, children, className }: SidebarNavItemProps) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "block rounded-sm px-md py-xs transition-colors",
          isActive
            ? "bg-surface text-ink text-body-sm-medium"
            : "text-steel text-body-sm hover:bg-surface-soft hover:text-ink",
          className,
        )
      }
    >
      {children}
    </NavLink>
  );
}
