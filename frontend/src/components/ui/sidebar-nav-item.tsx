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
          "block rounded-sm py-xs pr-md transition-colors border-l-2",
          isActive
            ? "bg-surface text-ink text-body-sm-medium border-brand-green pl-[14px]"
            : "border-transparent text-steel text-body-sm hover:bg-surface-soft hover:text-ink pl-[14px]",
          className,
        )
      }
    >
      {children}
    </NavLink>
  );
}
