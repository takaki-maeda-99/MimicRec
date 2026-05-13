// frontend/src/components/CameraSlotRow.tsx
import { useEffect, useRef, useState } from "react";
import { ChevronDown, Settings } from "lucide-react";
import { Badge } from "./ui/badge";
import { cn } from "../lib/utils";

export interface DeviceOption {
  name: string;
  kind: "camera" | "gopro";
}

interface CameraSlotRowProps {
  slot: string;
  device: string;
  locked: boolean;
  legacy: boolean;
  deviceOptions: DeviceOption[];
  usedDevices: Set<string>;
  onChange: (device: string) => void;
  onRemove?: () => void;
  onEdit?: (deviceName: string) => void;
}

export function CameraSlotRow({
  slot, device, legacy, deviceOptions, usedDevices,
  onChange, onRemove, onEdit,
}: CameraSlotRowProps) {
  return (
    <div className="flex items-center gap-sm rounded-md border border-hairline bg-canvas px-md py-2">
      <Badge variant="type" className="font-mono">
        {slot}{legacy && " (legacy)"}
      </Badge>
      <span className="flex-1" />
      <DevicePickerButton
        slot={slot}
        device={device}
        options={deviceOptions}
        usedDevices={usedDevices}
        onChange={onChange}
      />
      {onEdit && device && (
        <button
          type="button"
          onClick={() => onEdit(device)}
          className="text-stone hover:text-ink px-1"
          aria-label={`Edit ${device}`}
        >
          <Settings className="w-4 h-4" />
        </button>
      )}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="text-stone hover:text-brand-error px-2"
          aria-label={`Remove ${slot}`}
        >
          ✕
        </button>
      )}
    </div>
  );
}

interface AddSlotButtonProps {
  roles: string[];
  existingSlots: string[];
  onAdd: (slot: string) => void;
}

export function AddSlotButton({ roles, onAdd, existingSlots }: AddSlotButtonProps) {
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState("");
  const [error, setError] = useState<string | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

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
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const submitCustom = () => {
    const name = custom.trim();
    if (!name) return;
    if (existingSlots.includes(name)) {
      setError(`"${name}" is already added`);
      return;
    }
    onAdd(name);
    setCustom("");
    setError(null);
    setOpen(false);
    triggerRef.current?.focus();
  };

  const pickRole = (r: string) => {
    onAdd(r);
    setOpen(false);
    triggerRef.current?.focus();
  };

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => { setOpen(o => !o); setError(null); }}
        className="w-full border border-dashed border-hairline rounded-md px-md py-2 text-body-sm bg-canvas text-stone hover:border-stone hover:text-ink transition-colors text-left"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        + add camera slot…
      </button>
      {open && (
        <div
          ref={menuRef}
          role="menu"
          className="absolute z-40 mt-1 w-full bg-canvas border border-hairline rounded-md shadow-lg p-2 flex flex-col gap-1"
        >
          {roles.length > 0 && (
            <>
              <div className="px-1 text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
                Known roles
              </div>
              {roles.map(r => (
                <button
                  key={r}
                  type="button"
                  role="menuitem"
                  onClick={() => pickRole(r)}
                  className="text-left px-2 py-1 rounded-sm text-ink hover:bg-surface"
                >
                  {r}
                </button>
              ))}
              <div className="border-t border-hairline-soft mt-1 pt-2" />
            </>
          )}
          <div className="px-1 text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
            Custom slot
          </div>
          <div className="flex items-center gap-1">
            <input
              type="text"
              placeholder="e.g. wrist_left"
              value={custom}
              onChange={e => { setCustom(e.target.value); setError(null); }}
              onKeyDown={e => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  submitCustom();
                }
              }}
              className="flex-1 border border-hairline rounded px-2 py-1 text-body-sm bg-canvas font-mono"
              autoFocus
            />
            <button
              type="button"
              onClick={submitCustom}
              disabled={!custom.trim()}
              className="px-2 py-1 rounded text-body-sm bg-ink text-on-dark disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Add
            </button>
          </div>
          {error && <div className="px-1 text-caption text-brand-error">{error}</div>}
        </div>
      )}
    </div>
  );
}

interface DevicePickerButtonProps {
  slot: string;
  device: string;
  options: DeviceOption[];
  usedDevices: Set<string>;
  onChange: (device: string) => void;
}

function DevicePickerButton({
  slot, device, options, usedDevices, onChange,
}: DevicePickerButtonProps) {
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const toggleOpen = () => {
    setOpen(o => {
      if (!o) setHighlight(0);
      return !o;
    });
  };

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
        return;
      }
      // Slot 0 = "— none —", slots 1..N = options
      const total = options.length + 1;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlight(h => Math.min(h + 1, total - 1));
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlight(h => Math.max(h - 1, 0));
      }
      if (e.key === "Enter") {
        e.preventDefault();
        if (highlight === 0) {
          onChange("");
          setOpen(false);
          triggerRef.current?.focus();
          return;
        }
        const item = options[highlight - 1];
        if (!item) return;
        // Mirror the mouse-click in-use guard so keyboard doesn't bypass it.
        const inUse = usedDevices.has(item.name) && device !== item.name;
        if (inUse) return;
        onChange(item.name);
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, options, highlight, onChange, usedDevices, device]);

  const selectedKind = options.find(o => o.name === device)?.kind;
  const label = device ? `${device} (${selectedKind ?? "?"})` : "— none —";

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={toggleOpen}
        className={cn(
          "border border-hairline rounded px-2 py-1 text-body-sm bg-canvas min-w-[200px] flex items-center gap-2",
          "focus:outline-none focus:ring-2 focus:ring-ink",
        )}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Device for ${slot}`}
      >
        <span className="flex-1 text-left truncate">{label}</span>
        <ChevronDown className="w-3.5 h-3.5 text-stone" />
      </button>
      {open && (
        <div
          ref={menuRef}
          role="menu"
          className="absolute z-40 mt-1 w-full bg-canvas border border-hairline rounded-md shadow-lg p-1 max-h-[200px] overflow-auto"
        >
          <div
            role="menuitem"
            className={cn(
              "px-2 py-1 rounded-sm cursor-pointer text-stone",
              highlight === 0 ? "bg-surface" : "",
            )}
            onMouseEnter={() => setHighlight(0)}
            onClick={() => { onChange(""); setOpen(false); }}
          >
            — none —
          </div>
          {options.map((opt, i) => {
            const inUse = usedDevices.has(opt.name) && device !== opt.name;
            return (
              <div
                key={opt.name}
                role="menuitem"
                aria-disabled={inUse}
                className={cn(
                  "px-2 py-1 rounded-sm",
                  inUse ? "text-stone cursor-not-allowed" : "cursor-pointer text-ink",
                  highlight === i + 1 ? "bg-surface" : "",
                )}
                onMouseEnter={() => setHighlight(i + 1)}
                onClick={() => {
                  if (inUse) return;
                  onChange(opt.name);
                  setOpen(false);
                }}
              >
                {opt.name} <span className="text-caption text-stone">({opt.kind}){inUse && " · in use"}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
