// frontend/src/components/ConfigPickerRow.tsx
import { useEffect, useRef, useState } from "react";
import { ChevronDown, Settings } from "lucide-react";
import type { ConfigGroup, ConfigCardEntry } from "./ConfigCard";
import { cn } from "../lib/utils";

interface ConfigPickerRowProps {
  group: ConfigGroup;
  selected: string;
  configs: ConfigCardEntry[];
  onSelect: (name: string) => void;
  onEdit: (name: string) => void;
  onNew: () => void;
}

export function ConfigPickerRow({
  group, selected, configs, onSelect, onEdit, onNew,
}: ConfigPickerRowProps) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const triggerRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const selectedConfig = configs.find(c => c.name === selected);
  // configs.length > 0 gate: during the React Query loading window
  // configs is [] and selectedConfig is undefined for every persisted
  // selection. Without the gate, the useEffect below force-opens every
  // picker on mount and the popovers stay open after configs arrives.
  const missing = !!selected && configs.length > 0 && !selectedConfig;
  const count = configs.length;
  const isEmpty = count === 0;

  useEffect(() => {
    if (missing) setOpen(true);
  }, [missing]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)
          && !triggerRef.current?.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlight(h => Math.min(h + 1, configs.length - 1));
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlight(h => Math.max(h - 1, 0));
      }
      if (e.key === "Enter") {
        e.preventDefault();
        const item = configs[highlight];
        if (item) {
          onSelect(item.name);
          setOpen(false);
          triggerRef.current?.focus();
        }
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, configs, highlight, onSelect]);

  if (isEmpty) {
    return (
      <button
        type="button"
        onClick={onNew}
        className="w-full rounded-md border-2 border-dashed border-hairline bg-canvas px-md py-sm text-stone hover:border-stone hover:text-ink transition-colors"
      >
        + new {group}…
      </button>
    );
  }

  const toggleOpen = () => {
    setOpen(o => {
      if (!o) setHighlight(0);
      return !o;
    });
  };

  const onRowKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      e.stopPropagation();
      toggleOpen();
    }
  };

  return (
    <div className="relative">
      <div
        ref={triggerRef}
        role="button"
        tabIndex={0}
        onClick={toggleOpen}
        onKeyDown={onRowKey}
        className={cn(
          "w-full rounded-md border-2 bg-canvas px-md py-sm transition-colors text-left",
          "flex items-center gap-sm cursor-pointer focus:outline-none focus:ring-2 focus:ring-ink",
          missing ? "border-brand-error/60" : "border-ink",
        )}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {missing ? (
          <span className="text-brand-error font-mono text-body-sm-medium">⚠ {selected} — missing</span>
        ) : (
          <>
            <span className="w-2 h-2 rounded-full bg-ink" aria-hidden />
            <span className="text-body-sm-medium text-ink truncate min-w-0 flex-1">
              {selected}
            </span>
            <span className="text-caption text-steel font-mono">
              {count} option{count !== 1 ? "s" : ""}
            </span>
          </>
        )}
        {selectedConfig && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onEdit(selected); }}
            className="text-stone hover:text-ink px-1"
            aria-label={`Edit ${selected}`}
          >
            <Settings className="w-4 h-4" />
          </button>
        )}
        <ChevronDown className="w-4 h-4 text-stone" />
      </div>

      {open && (
        <div
          ref={menuRef}
          role="menu"
          className="absolute z-40 mt-1 w-full bg-canvas border border-hairline rounded-md shadow-lg p-1 max-h-[240px] overflow-auto"
        >
          <div className="px-2 py-1 text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
            switch {group}
          </div>
          {configs.map((c, i) => (
            <div
              key={c.name}
              role="menuitem"
              className={cn(
                "flex items-center gap-2 px-2 py-1.5 rounded-sm cursor-pointer",
                i === highlight ? "bg-surface" : "",
                c.name === selected ? "border-l-2 border-ink" : "",
              )}
              onMouseEnter={() => setHighlight(i)}
              onClick={() => { onSelect(c.name); setOpen(false); }}
            >
              <span className="w-2 h-2 rounded-full" style={{ background: c.name === selected ? "var(--color-ink)" : "transparent", border: c.name === selected ? "none" : "1px solid var(--color-hairline)" }} />
              <span className="flex-1 text-body-sm text-ink truncate">{c.name}</span>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onEdit(c.name); setOpen(false); }}
                className="text-stone hover:text-ink px-1"
                aria-label={`Edit ${c.name}`}
              >
                <Settings className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
          <div className="border-t border-hairline-soft mt-1 pt-1">
            <button
              type="button"
              onClick={() => { onNew(); setOpen(false); }}
              className="w-full text-left px-2 py-1.5 rounded-sm text-stone hover:bg-surface hover:text-ink"
            >
              + new {group}…
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
