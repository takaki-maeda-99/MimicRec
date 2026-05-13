// frontend/src/components/HardwareStatusBlock.tsx
import type { ReactNode } from "react";
import { Button } from "./ui/button";
import { SectionMark } from "./ui/section-mark";

interface SerialDevice { port: string; available: boolean }
interface CameraDevice {
  path: string; device_id: number; available: boolean; width: number; height: number;
}

interface Props {
  serial: SerialDevice[];
  cameras: CameraDevice[];
  calibrations: Record<string, Record<string, string[]>>;
  refreshing: boolean;
  onRefresh: () => void;
}

export function HardwareStatusBlock({
  serial, cameras, calibrations, refreshing, onRefresh,
}: Props) {
  return (
    <section className="flex flex-col gap-md">
      <header className="flex items-baseline gap-md">
        <SectionMark code="§04.A" name="Hardware status" />
        <span className="flex-1 h-px bg-hairline-soft" />
        <Button variant="secondary" size="sm" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh"}
        </Button>
      </header>
      <div className="rounded-md border border-hairline bg-canvas p-md grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-xl">
        <Column label={`Serial · ${serial.length}`}>
          {serial.length === 0
            ? <Empty>No serial ports found</Empty>
            : serial.map(p => (
                <Row key={p.port}>
                  <Dot ok={p.available} />
                  <Mono>{p.port}</Mono>
                </Row>
              ))}
        </Column>
        <Column label={`Cameras · ${cameras.length}`}>
          {cameras.length === 0
            ? <Empty>No cameras found</Empty>
            : cameras.map(c => (
                <Row key={c.path}>
                  <Dot ok={c.available} />
                  <Mono>{c.path}</Mono>
                  {c.available && (
                    <span className="ml-auto font-mono text-caption text-stone">
                      {c.width}×{c.height}
                    </span>
                  )}
                </Row>
              ))}
        </Column>
        <Column label="Calibration">
          {Object.keys(calibrations).length === 0
            ? <Empty>No calibrations found</Empty>
            : Object.entries(calibrations).map(([category, robots]) => (
                <div key={category} className="flex flex-col gap-1">
                  <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
                    {category}
                  </div>
                  {Object.entries(robots).map(([robotType, ids]) => (
                    <div
                      key={robotType}
                      className="flex items-baseline justify-between gap-md border-b border-dashed border-hairline-soft last:border-b-0 py-0.5"
                    >
                      <span className="text-body-sm-medium text-ink">{robotType}</span>
                      <span className="font-mono text-caption text-steel min-w-0 break-words">
                        {ids.length > 0 ? ids.join(", ") : "—"}
                      </span>
                    </div>
                  ))}
                </div>
              ))}
        </Column>
      </div>
      <p className="text-caption text-stone">
        Run calibration:{" "}
        <code className="rounded-xs border border-hairline bg-surface px-1.5 py-0.5 font-mono text-code-inline text-charcoal">
          python scripts/calibrate_so101.py --port /dev/ttyACM0 --id my_arm --type follower
        </code>
      </p>
    </section>
  );
}

function Column({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold mb-xs">
        {label}
      </div>
      <div className="flex flex-col gap-1">{children}</div>
    </div>
  );
}
function Row({ children }: { children: ReactNode }) {
  return <div className="flex items-center gap-xs text-body-sm">{children}</div>;
}
function Dot({ ok }: { ok: boolean }) {
  return <span aria-hidden className={`w-2 h-2 rounded-full ${ok ? "bg-brand-green" : "bg-brand-error"}`} />;
}
function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-code-sm text-charcoal">{children}</span>;
}
function Empty({ children }: { children: ReactNode }) {
  return <p className="text-body-sm text-stone">{children}</p>;
}
