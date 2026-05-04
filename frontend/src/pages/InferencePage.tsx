import { useEffect, useRef, useState } from "react";
import { useInferenceStore } from "../state/inference-store";
import { subscribeInferenceWS } from "../api/inference";
import { apiFetch } from "../api/client";

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
    <div style={{ padding: "16px", maxWidth: 1100, margin: "0 auto" }}>
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <h1 style={{ margin: 0, fontSize: 22 }}>
          Inference {isLive && <span style={{ color: "#22c55e", marginLeft: 8 }}>● live</span>}
        </h1>
        <button
          onClick={() => s.emergencyStop()}
          style={{
            background: "#ef4444", color: "white", border: 0, padding: "10px 20px",
            fontSize: 16, fontWeight: 700, borderRadius: 4, cursor: "pointer",
          }}
        >
          E-STOP
        </button>
      </header>

      {(s.phase === "ready" || s.phase === "recording") && (
        <div style={{
          background: "#fef3c7", border: "1px solid #f59e0b", color: "#78350f",
          padding: "8px 12px", borderRadius: 4, marginBottom: 12, fontWeight: 600,
        }}>
          ⚠ Robot under model control — use E-STOP to halt
        </div>
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
    <div>
      <Field label="Inference config">
        <select value={s.selectedConfig} onChange={e => s.selectConfig(e.target.value)}>
          <option value="">— select —</option>
          {s.configs.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
      </Field>
      <Field label="Dataset">
        <select value={s.selectedDataset} onChange={e => s.selectDataset(e.target.value)}>
          <option value="">— select —</option>
          {datasets.map(d => <option key={d.name} value={d.name}>{d.name}</option>)}
        </select>
      </Field>
      <Field label="Instruction">
        <input
          type="text" value={s.instruction}
          onChange={e => s.setInstruction(e.target.value)}
          placeholder="pick up the bottle"
          style={{ width: "100%" }}
        />
        <button disabled title="coming soon">🎤</button>
      </Field>
      <button
        disabled={!s.selectedConfig || !s.selectedDataset || !s.instruction}
        onClick={() => s.startSession()}
      >
        Start session
      </button>
    </div>
  );
}


function ReadyPanel() {
  const s = useInferenceStore();
  return (
    <div>
      <Field label="Instruction">
        <input
          type="text" value={s.instruction}
          onChange={e => s.setInstruction(e.target.value)}
          style={{ width: "70%" }}
        />
        <button onClick={() => s.updateInstruction()}>Update</button>
        <button disabled title="coming soon">🎤</button>
      </Field>
      <TelemetryBlock />
      <ActionPreview />
      <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
        <button onClick={() => s.startEpisode()}>Start episode</button>
        <button onClick={() => s.stopSession()}>Stop session</button>
      </div>
    </div>
  );
}


function RecordingPanel() {
  const s = useInferenceStore();
  return (
    <div>
      <div><strong>Instruction (locked):</strong> "{s.lockedInstruction ?? ""}"</div>
      <div>Episode: {s.episodeElapsedSec.toFixed(1)}s ⏺ recording…</div>
      <TelemetryBlock />
      <div style={{ marginTop: 8 }}>
        Model done signal: {s.telemetry.modelDoneSignal === "waiting" ? "waiting…" :
          s.telemetry.modelDoneSignal === "received" ? "received ✓" : "unsupported"}
      </div>
      <ActionPreview />
      <div style={{ marginTop: 12 }}>
        <button onClick={() => s.stopEpisode()}>Stop episode</button>
      </div>
    </div>
  );
}


function ReviewPanel() {
  const s = useInferenceStore();
  return (
    <div>
      <div>Episode summary{s.reviewEpisode ? ` — #${s.reviewEpisode.index} (${s.reviewEpisode.durationSec.toFixed(1)}s)` : ""}</div>
      <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
        <button onClick={() => s.commitEpisode(true)}>Save (✓ success)</button>
        <button onClick={() => s.commitEpisode(false)}>Save (✗ failure)</button>
        <button onClick={() => s.discardEpisode()}>Discard</button>
      </div>
    </div>
  );
}


function TelemetryBlock() {
  const t = useInferenceStore(s => s.telemetry);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(2, max-content)", gap: 4, marginTop: 12 }}>
      <div>buffer depth:</div><div>{t.bufferDepth} / {t.bufferOrigin}</div>
      <div>last latency:</div><div>{t.lastLatencyMs == null ? "—" : `${t.lastLatencyMs.toFixed(1)} ms`}</div>
      <div>chunks consumed:</div><div>{t.chunksConsumed}</div>
      <div>inference errors:</div><div>{t.inferenceErrors}</div>
      <div>clamps/chunk:</div><div>{t.clampsLastChunk ?? "—"}</div>
      <div>safety events:</div><div>{t.safetyEvents.length}</div>
    </div>
  );
}


function ActionPreview() {
  const a = useInferenceStore(s => s.telemetry.nextAction);
  if (!a) return null;
  return (
    <div style={{ marginTop: 8, fontFamily: "monospace", fontSize: 12 }}>
      ΔEE: [{a.ee_delta.map(v => v.toFixed(3)).join(", ")}], gripper: {a.gripper.toFixed(3)}
    </div>
  );
}


function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "block", marginBottom: 8 }}>
      <div style={{ fontSize: 12, color: "#555" }}>{label}</div>
      <div>{children}</div>
    </label>
  );
}
