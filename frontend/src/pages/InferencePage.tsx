import { useEffect, useRef, useState } from "react";
import { useInferenceStore } from "../state/inference-store";
import { subscribeInferenceWS } from "../api/inference";
import { apiFetch } from "../api/client";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { CodeInline } from "../components/ui/code-inline";
import { PillTab } from "../components/ui/pill-tab";

interface DatasetItem {
  name: string;
}

export function InferencePage() {
  const s = useInferenceStore();
  const [datasets, setDatasets] = useState<DatasetItem[]>([]);
  const wsCleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    s.loadConfigs();
    apiFetch<{ items: DatasetItem[] }>("/api/datasets").then(r => setDatasets(r.items)).catch(() => setDatasets([]));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Subscribe to WS only after a session starts
  useEffect(() => {
    if (s.phase === "pre-start") {
      wsCleanupRef.current?.();
      wsCleanupRef.current = null;
      return;
    }
    if (wsCleanupRef.current) return;
    wsCleanupRef.current = subscribeInferenceWS((e) => s.handleEvent(e));
    return () => {
      wsCleanupRef.current?.();
      wsCleanupRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.phase]);

  const isLive = s.phase === "ready" || s.phase === "recording";

  return (
    <div>
      <header className="flex items-center justify-between pb-md mb-xl border-b border-hairline-soft">
        <div className="flex items-center gap-md">
          <h2 className="text-heading-3 text-ink">Inference</h2>
          {isLive ? (
            <PillTab active tone="state" disabled>Streaming</PillTab>
          ) : (
            <span className="text-body-sm text-stone">Stopped</span>
          )}
        </div>
        <Button
          className="!bg-brand-error !text-on-dark hover:!bg-brand-error/90"
          onClick={() => s.emergencyStop()}
        >
          E-STOP
        </Button>
      </header>

      {(s.phase === "ready" || s.phase === "recording") && (
        <Card className="mb-xl border border-brand-warn/30 bg-brand-warn/10">
          <p className="text-body-sm-medium text-brand-warn">
            ⚠ Robot under model control — use E-STOP to halt
          </p>
        </Card>
      )}

      {s.phase === "pre-start" && (
        <PreStartPanel datasets={datasets} />
      )}
      {s.phase === "ready" && (
        <ReadyPanel />
      )}
      {s.phase === "recording" && (
        <RecordingPanel />
      )}
      {s.phase === "review" && (
        <ReviewPanel />
      )}
    </div>
  );
}


function PreStartPanel({ datasets }: { datasets: DatasetItem[] }) {
  const s = useInferenceStore();
  return (
    <Card className="flex flex-col gap-md">
      <Field label="Inference config">
        <select
          className="flex h-10 w-full rounded-md border border-hairline bg-canvas px-md text-body-md text-ink focus-visible:outline-none focus-visible:border-2 focus-visible:border-ink"
          value={s.selectedConfig}
          onChange={e => s.selectConfig(e.target.value)}
        >
          <option value="">— select —</option>
          {s.configs.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
      </Field>
      <Field label="Dataset">
        <select
          className="flex h-10 w-full rounded-md border border-hairline bg-canvas px-md text-body-md text-ink focus-visible:outline-none focus-visible:border-2 focus-visible:border-ink"
          value={s.selectedDataset}
          onChange={e => s.selectDataset(e.target.value)}
        >
          <option value="">— select —</option>
          {datasets.map(d => <option key={d.name} value={d.name}>{d.name}</option>)}
        </select>
      </Field>
      <Field label="Instruction">
        <div className="flex gap-xs">
          <input
            type="text"
            value={s.instruction}
            onChange={e => s.setInstruction(e.target.value)}
            placeholder="pick up the bottle"
            className="flex h-10 w-full rounded-md border border-hairline bg-canvas px-md text-body-md text-ink placeholder:text-stone focus-visible:outline-none focus-visible:border-2 focus-visible:border-ink"
          />
          <Button variant="ghost" disabled title="coming soon">🎤</Button>
        </div>
      </Field>
      <Button
        disabled={!s.selectedConfig || !s.selectedDataset || !s.instruction}
        onClick={() => s.startSession()}
      >
        Start session
      </Button>
    </Card>
  );
}


function ReadyPanel() {
  const s = useInferenceStore();
  return (
    <div className="flex flex-col gap-xl">
      <Card>
        <Field label="Instruction">
          <div className="flex gap-xs">
            <input
              type="text"
              value={s.instruction}
              onChange={e => s.setInstruction(e.target.value)}
              className="flex h-10 w-full rounded-md border border-hairline bg-canvas px-md text-body-md text-ink focus-visible:outline-none focus-visible:border-2 focus-visible:border-ink"
            />
            <Button variant="secondary" onClick={() => s.updateInstruction()}>Update</Button>
            <Button variant="ghost" disabled title="coming soon">🎤</Button>
          </div>
        </Field>
      </Card>
      <TelemetryBlock />
      <ActionPreview />
      <div className="flex gap-xs">
        <Button onClick={() => s.startEpisode()}>Start episode</Button>
        <Button variant="secondary" onClick={() => s.stopSession()}>Stop session</Button>
      </div>
    </div>
  );
}


function RecordingPanel() {
  const s = useInferenceStore();
  return (
    <div className="flex flex-col gap-xl">
      <Card>
        <p className="text-body-sm-medium text-ink">
          <span className="text-stone">Instruction (locked):</span>{" "}
          "{s.lockedInstruction ?? ""}"
        </p>
        <p className="mt-xs text-body-sm text-slate">
          Episode: <CodeInline>{s.episodeElapsedSec.toFixed(1)}s</CodeInline> recording…
        </p>
      </Card>
      <TelemetryBlock />
      <div className="text-body-sm text-slate">
        Model done signal:{" "}
        {s.telemetry.modelDoneSignal === "waiting" ? (
          <span className="text-stone">waiting…</span>
        ) : s.telemetry.modelDoneSignal === "received" ? (
          <span className="text-brand-green-deep">received ✓</span>
        ) : (
          <span className="text-stone">unsupported</span>
        )}
      </div>
      <ActionPreview />
      <Button variant="secondary" onClick={() => s.stopEpisode()}>Stop episode</Button>
    </div>
  );
}


function ReviewPanel() {
  const s = useInferenceStore();
  return (
    <Card className="flex flex-col gap-md">
      <p className="text-body-sm text-ink">
        Episode summary{s.reviewEpisode
          ? ` — #${s.reviewEpisode.index} (`
          : ""}
        {s.reviewEpisode && (
          <CodeInline>{s.reviewEpisode.durationSec.toFixed(1)}s</CodeInline>
        )}
        {s.reviewEpisode ? ")" : ""}
      </p>
      <div className="flex gap-xs">
        <Button onClick={() => s.commitEpisode(true)}>Save (✓ success)</Button>
        <Button variant="secondary" className="!text-brand-error" onClick={() => s.commitEpisode(false)}>Save (✗ failure)</Button>
        <Button variant="ghost" onClick={() => s.discardEpisode()}>Discard</Button>
      </div>
    </Card>
  );
}


function TelemetryBlock() {
  const t = useInferenceStore(s => s.telemetry);
  return (
    <Card>
      <h3 className="text-heading-5 text-ink mb-md">Telemetry</h3>
      <div className="grid grid-cols-2 gap-xs text-body-sm">
        <span className="text-steel">buffer depth</span>
        <span className="flex items-center gap-xs">
          <CodeInline>{String(t.bufferDepth)}</CodeInline>
          <span className="text-stone">/ {t.bufferOrigin}</span>
        </span>
        <span className="text-steel">last latency</span>
        <CodeInline>{t.lastLatencyMs == null ? "—" : `${t.lastLatencyMs.toFixed(1)} ms`}</CodeInline>
        <span className="text-steel">chunks consumed</span>
        <CodeInline>{String(t.chunksConsumed)}</CodeInline>
        <span className="text-steel">inference errors</span>
        <CodeInline>{String(t.inferenceErrors)}</CodeInline>
        <span className="text-steel">clamps/chunk</span>
        <CodeInline>{t.clampsLastChunk != null ? String(t.clampsLastChunk) : "—"}</CodeInline>
        <span className="text-steel">safety events</span>
        <CodeInline>{String(t.safetyEvents.length)}</CodeInline>
      </div>
    </Card>
  );
}


function ActionPreview() {
  const a = useInferenceStore(s => s.telemetry.nextAction);
  if (!a) return null;
  return (
    <Card>
      <h3 className="text-heading-5 text-ink mb-xs">Next action</h3>
      <code className="block text-code-sm font-mono text-charcoal">
        ΔEE: [{a.ee_delta.map(v => v.toFixed(3)).join(", ")}], gripper: {a.gripper.toFixed(3)}
      </code>
    </Card>
  );
}


function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-xs">
      <span className="text-body-sm-medium text-charcoal">{label}</span>
      <div>{children}</div>
    </label>
  );
}
