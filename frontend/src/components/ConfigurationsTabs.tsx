// frontend/src/components/ConfigurationsTabs.tsx
import { useState } from "react";
import { ConfigCard, type ConfigGroup, type ConfigCardEntry } from "./ConfigCard";
import { Button } from "./ui/button";
import { SegmentedTab, SegmentedTabBar } from "./ui/segmented-tab";
import { SectionMark } from "./ui/section-mark";

const GROUPS: { id: ConfigGroup; label: string }[] = [
  { id: "robot", label: "robot" },
  { id: "teleop", label: "teleop" },
  { id: "mapper", label: "mapper" },
  { id: "cameras", label: "cameras" },
  { id: "gopros", label: "gopros" },
];

interface Props {
  configs: Record<ConfigGroup, ConfigCardEntry[]>;
  refreshing: boolean;
  onRefresh: () => void;
  onEdit: (group: ConfigGroup, name: string) => void;
  onClone: (group: ConfigGroup, name: string) => void;
  onNew: (group: ConfigGroup) => void;
  onDelete: (group: ConfigGroup, name: string) => void;
}

export function ConfigurationsTabs({
  configs, refreshing, onRefresh, onEdit, onClone, onNew, onDelete,
}: Props) {
  const [active, setActive] = useState<ConfigGroup>("robot");
  const rows = configs[active] ?? [];

  return (
    <section className="flex flex-col gap-md">
      <header className="flex items-baseline gap-md">
        <SectionMark code="§04.B" name="Configurations" />
        <span className="flex-1 h-px bg-hairline-soft" />
        <Button variant="secondary" size="sm" onClick={() => onNew(active)}>
          + new {active}
        </Button>
        <Button variant="secondary" size="sm" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh"}
        </Button>
      </header>
      <SegmentedTabBar>
        {GROUPS.map(g => (
          <SegmentedTab
            key={g.id}
            active={active === g.id}
            onClick={() => setActive(g.id)}
          >
            {g.label} · {(configs[g.id] ?? []).length}
          </SegmentedTab>
        ))}
      </SegmentedTabBar>
      <div className="flex flex-col gap-2">
        {rows.length === 0 ? (
          <p className="text-body-sm text-stone py-md">No {active} configs.</p>
        ) : rows.map(cfg => (
          <ConfigCard
            key={cfg.name}
            config={cfg}
            group={active}
            rightSlot={
              <span className="flex items-center gap-1">
                <Button
                  variant="secondary"
                  size="sm"
                  className="!bg-surface hover:!bg-hairline"
                  onClick={() => onEdit(active, cfg.name)}
                >
                  ⚙ Edit
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  className="!bg-surface hover:!bg-hairline"
                  onClick={() => onClone(active, cfg.name)}
                >
                  Clone
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  className="!bg-surface hover:!bg-brand-error/15 !text-brand-error"
                  onClick={() => onDelete(active, cfg.name)}
                  aria-label={`Delete ${cfg.name}`}
                >
                  ⌫
                </Button>
              </span>
            }
          />
        ))}
      </div>
    </section>
  );
}
