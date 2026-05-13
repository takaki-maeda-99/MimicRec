// frontend/src/components/CameraSlotRow.tsx
import { Badge } from "./ui/badge";

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
}

export function CameraSlotRow({
  slot,
  device,
  locked,
  legacy,
  deviceOptions,
  usedDevices,
  onChange,
  onRemove,
}: CameraSlotRowProps) {
  return (
    <div className="flex items-center gap-sm rounded-md border border-hairline bg-canvas px-md py-2">
      <Badge variant="type" className="font-mono">
        {slot}{legacy && " (legacy)"}
      </Badge>
      <span className="flex-1" />
      <select
        value={device}
        disabled={locked && !device}
        onChange={e => onChange(e.target.value)}
        className="border border-hairline rounded px-2 py-1 text-body-sm bg-canvas min-w-[200px]"
      >
        <option value="">— none —</option>
        {deviceOptions.map(opt => (
          <option
            key={opt.name}
            value={opt.name}
            disabled={usedDevices.has(opt.name) && device !== opt.name}
          >
            {opt.name} ({opt.kind}){usedDevices.has(opt.name) && device !== opt.name ? " (in use)" : ""}
          </option>
        ))}
      </select>
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
  onAdd: (role: string) => void;
}

export function AddSlotButton({ roles, onAdd }: AddSlotButtonProps) {
  return (
    <select
      value=""
      className="border border-dashed border-hairline rounded-md px-md py-2 text-body-sm bg-canvas text-stone"
      onChange={e => { if (e.target.value) onAdd(e.target.value); }}
    >
      <option value="">+ add slot…</option>
      {roles.map(r => (
        <option key={r} value={r}>{r}</option>
      ))}
    </select>
  );
}
