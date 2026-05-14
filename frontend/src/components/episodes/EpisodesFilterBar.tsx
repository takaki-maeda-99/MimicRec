import { Input } from "../ui/input";

export type StatusFilter = "all" | "success" | "failure";

interface Props {
  total: number;
  successCount: number;
  failureCount: number;
  status: StatusFilter;
  onStatusChange: (s: StatusFilter) => void;
  modes: Set<string>;             // empty = no mode filter
  availableModes: string[];
  onToggleMode: (mode: string) => void;
  search: string;
  onSearchChange: (q: string) => void;
}

export function EpisodesFilterBar({
  total, successCount, failureCount,
  status, onStatusChange,
  modes, availableModes, onToggleMode,
  search, onSearchChange,
}: Props) {
  return (
    <div className="flex-shrink-0 flex items-center gap-2 px-xl py-sm border-b border-hairline bg-canvas">
      <Chip active={status === "all"}     onClick={() => onStatusChange("all")}>All ({total})</Chip>
      <Chip active={status === "success"} edge="success" onClick={() => onStatusChange("success")}>Success ({successCount})</Chip>
      <Chip active={status === "failure"} edge="failure" onClick={() => onStatusChange("failure")}>Failure ({failureCount})</Chip>

      {availableModes.length > 0 && (
        <>
          <span className="text-hairline">|</span>
          {availableModes.map((m) => (
            <Chip key={m} active={modes.has(m)} onClick={() => onToggleMode(m)}>{m}</Chip>
          ))}
        </>
      )}

      <Input
        placeholder="Search task…"
        value={search}
        onChange={(e) => onSearchChange(e.target.value)}
        className="ml-auto w-[200px]"
      />
    </div>
  );
}

function Chip({
  active, edge, onClick, children,
}: {
  active: boolean;
  edge?: "success" | "failure";
  onClick: () => void;
  children: React.ReactNode;
}) {
  const edgeClass =
    edge === "success" ? "border-l-[3px] border-l-brand-green-deep pl-[7px]"
  : edge === "failure" ? "border-l-[3px] border-l-brand-error pl-[7px]"
  : "";
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        `text-caption rounded-full px-3 py-1 border transition-colors ${edgeClass} ` +
        (active
          ? "bg-ink text-on-primary border-ink"
          : "bg-canvas text-slate border-hairline hover:border-stone")
      }
    >
      {children}
    </button>
  );
}
