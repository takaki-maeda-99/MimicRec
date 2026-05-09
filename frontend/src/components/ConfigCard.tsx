import type { ReactNode } from "react";
import { ArrowRightLeft, Bot, Camera, Check, Gamepad2 } from "lucide-react";
import { cn } from "../lib/utils";
import { Badge } from "./ui/badge";
import { CodeInline } from "./ui/code-inline";

export type ConfigGroup = "robot" | "teleop" | "mapper" | "cameras";

export interface ConfigCardEntry {
  name: string;
  content: Record<string, unknown>;
}

interface ConfigCardProps {
  config: ConfigCardEntry;
  group: ConfigGroup;
  selected?: boolean;
  multiSelect?: boolean;
  onClick?: () => void;
  rightSlot?: ReactNode;
  className?: string;
}

const ICON_BY_GROUP = {
  robot: Bot,
  teleop: Gamepad2,
  mapper: ArrowRightLeft,
  cameras: Camera,
} as const;

const ICON_THEME_BY_GROUP: Record<ConfigGroup, string> = {
  robot: "bg-brand-tag/15 text-brand-tag",
  teleop: "bg-brand-warn/15 text-brand-warn",
  mapper: "bg-surface text-steel",
  cameras: "bg-brand-green/20 text-brand-green-deep",
};

function getTypeBadge(content: Record<string, unknown>): string | null {
  const target = content._target_;
  if (typeof target !== "string") return null;
  return target.split(".").pop() ?? null;
}

function getMeta(group: ConfigGroup, content: Record<string, unknown>): ReactNode {
  if (group === "robot") {
    const port = typeof content.port === "string" ? content.port : null;
    const kinematics = content.kinematics as Record<string, unknown> | undefined;
    const joints = kinematics?.joint_names;
    const jointCount = Array.isArray(joints) ? joints.length : null;
    if (!port && jointCount === null) return null;
    return (
      <>
        {port && <CodeInline>{port}</CodeInline>}
        {jointCount !== null && <span>{jointCount} joints</span>}
      </>
    );
  }
  if (group === "teleop") {
    const port = typeof content.port === "string" ? content.port : null;
    return port ? <CodeInline>{port}</CodeInline> : null;
  }
  if (group === "cameras") {
    const deviceId = content.device_id;
    const width = typeof content.width === "number" ? content.width : null;
    const height = typeof content.height === "number" ? content.height : null;
    if (deviceId === undefined && width === null) return null;
    return (
      <>
        {deviceId !== undefined && <CodeInline>device {String(deviceId)}</CodeInline>}
        {width !== null && height !== null && <span>{width} × {height}</span>}
      </>
    );
  }
  return null;
}

function SelectIndicator({ selected, multiSelect }: { selected: boolean; multiSelect: boolean }) {
  if (multiSelect) {
    return (
      <span
        aria-hidden
        className={cn(
          "inline-flex items-center justify-center w-4 h-4 rounded-xs flex-shrink-0",
          selected ? "bg-ink text-on-dark" : "border-2 border-hairline bg-canvas",
        )}
      >
        {selected && <Check className="w-3 h-3" strokeWidth={3} />}
      </span>
    );
  }
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex items-center justify-center w-4 h-4 rounded-full flex-shrink-0",
        selected ? "bg-ink" : "border-2 border-hairline bg-canvas",
      )}
    >
      {selected && <span className="block w-1.5 h-1.5 rounded-full bg-canvas" />}
    </span>
  );
}

export function ConfigCard({
  config,
  group,
  selected = false,
  multiSelect = false,
  onClick,
  rightSlot,
  className,
}: ConfigCardProps) {
  const Icon = ICON_BY_GROUP[group];
  const iconTheme = ICON_THEME_BY_GROUP[group];
  const typeBadge = getTypeBadge(config.content);
  const meta = getMeta(group, config.content);

  const clickable = !!onClick;
  const isSelected = clickable && selected;

  const baseClass = cn(
    "block w-full rounded-md border-2 bg-canvas px-md py-sm transition-colors",
    isSelected ? "border-ink" : "border-hairline",
    clickable && !isSelected && "hover:border-stone cursor-pointer",
    className,
  );

  const inner = (
    <>
      <div className="flex items-center gap-sm">
        <span className={cn("inline-flex w-8 h-8 items-center justify-center rounded-sm flex-shrink-0", iconTheme)}>
          <Icon className="w-[18px] h-[18px]" strokeWidth={2} />
        </span>
        <span className="text-body-sm-medium text-ink truncate min-w-0 flex-1">{config.name}</span>
        {typeBadge && <Badge variant="type">{typeBadge}</Badge>}
        {clickable && <SelectIndicator selected={isSelected} multiSelect={multiSelect} />}
        {rightSlot}
      </div>
      {meta && (
        <div className="flex items-center gap-xs flex-wrap text-caption text-steel mt-xs pl-[44px]">
          {meta}
        </div>
      )}
    </>
  );

  if (clickable) {
    return (
      <button type="button" onClick={onClick} className={cn(baseClass, "text-left")}>
        {inner}
      </button>
    );
  }
  return <div className={baseClass}>{inner}</div>;
}
