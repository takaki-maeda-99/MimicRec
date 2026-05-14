import { useInferenceStore } from "../../state/inference-store";

export function TelemetryColumn() {
  const t = useInferenceStore((x) => x.telemetry);
  const a = t.nextAction;

  return (
    <aside className="w-[220px] flex-shrink-0 border-l border-hairline bg-canvas flex flex-col">
      <div className="px-md py-md flex-1 overflow-auto flex flex-col gap-md">
        <div className="space-y-2">
          <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
            Telemetry
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Tile k="buffer"  v={`${t.bufferDepth} / ${t.bufferOrigin}`} />
            <Tile k="latency" v={t.lastLatencyMs == null ? "—" : `${t.lastLatencyMs.toFixed(1)} ms`} />
            <Tile k="chunks"  v={String(t.chunksConsumed)} />
            <Tile k="errors"  v={String(t.inferenceErrors)} warn={t.inferenceErrors > 0} />
            <Tile k="clamps"  v={t.clampsLastChunk == null ? "—" : String(t.clampsLastChunk)} />
            <Tile k="safety"  v={String(t.safetyEvents.length)} warn={t.safetyEvents.length > 0} />
          </div>
        </div>

        {a && Array.isArray(a.ee_delta) && (
          <div className="space-y-2">
            <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
              Next action
            </div>
            <div className="rounded-sm bg-surface-code px-2 py-2 font-mono text-xs text-on-dark space-y-0.5">
              <div>ΔEE [{a.ee_delta.map((v: number) => v.toFixed(3)).join(", ")}]</div>
              <div>gripper {typeof a.gripper === "number" ? a.gripper.toFixed(3) : "—"}</div>
            </div>
          </div>
        )}

        {t.modelDoneSignal && (
          <div className="space-y-1">
            <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
              Model done
            </div>
            <div className="text-body-sm">
              {t.modelDoneSignal === "waiting"     && <span className="text-stone">waiting…</span>}
              {t.modelDoneSignal === "received"    && <span className="text-brand-green-deep">received ✓</span>}
              {t.modelDoneSignal === "unsupported" && <span className="text-stone">unsupported</span>}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

function Tile({ k, v, warn }: { k: string; v: string; warn?: boolean }) {
  return (
    <div className="rounded-sm border border-hairline-soft bg-surface-soft px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-steel">{k}</div>
      <div className={`font-mono text-body-sm-medium ${warn ? "text-brand-error" : "text-ink"}`}>
        {v}
      </div>
    </div>
  );
}
