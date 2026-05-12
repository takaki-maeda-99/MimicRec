import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { useInferenceStore } from "../state/inference-store";
import { useSessionStore } from "../state/session-store";
import { subscribeInferenceWS } from "../api/inference";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Select } from "../components/ui/select";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";

export function InferencePage() {
  const s = useInferenceStore();
  const sessionState = useSessionStore((x) => x.state);
  const sessionRobot = useSessionStore((x) => x.robot);
  const sessionMode = useSessionStore((x) => x.mode);
  const sessionDataset = useSessionStore((x) => x.dataset);
  const wsCleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    s.loadConfigs();
    s.rehydrateFromBackend();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
  // Backend requires session in READY (not recording/review) and not already
  // mid-inference. Match that here so the form doesn't promise a Start that
  // will 409.
  const sessionReadyForInference =
    sessionState === "ready" && sessionMode !== "inference";
  const sessionBlocker: string | null = (() => {
    if (sessionState === "idle") return "no-session";
    if (sessionState === "recording") return "recording";
    if (sessionState === "review") return "review";
    if (sessionMode === "inference") return "already-inference";
    return null;
  })();

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-4">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold">Inference</h1>
          {isLive && <Badge variant="success">● live</Badge>}
          {sessionRobot && (
            <span className="text-xs text-steel">
              robot: <code>{sessionRobot}</code>
              {sessionMode && <> · mode: <code>{sessionMode}</code></>}
            </span>
          )}
        </div>
      </header>

      {s.error && (
        <div className="rounded-md border border-brand-error/30 bg-brand-error/10 p-3 flex items-start justify-between gap-3">
          <div className="text-sm text-brand-error break-words">{s.error}</div>
          <button
            onClick={() => s.setError(null)}
            className="text-brand-error hover:text-brand-error text-lg leading-none"
            aria-label="dismiss"
          >
            ×
          </button>
        </div>
      )}

      {sessionBlocker && s.phase === "pre-start" && (
        <div className="rounded-md border border-brand-warn/30 bg-brand-warn/10 p-3 text-sm text-brand-warn">
          <div className="font-medium mb-1">
            {sessionBlocker === "no-session" && "⚠ No active session"}
            {sessionBlocker === "recording" && "⚠ Session is recording"}
            {sessionBlocker === "review" && "⚠ Session is in review"}
            {sessionBlocker === "already-inference" && "⚠ Already in inference mode"}
          </div>
          <div>
            {sessionBlocker === "no-session" && (
              <>
                The inference pipeline runs on top of an active robot session. Open the{" "}
                <Link to="/record" className="underline font-medium">Record page</Link> first
                to load a robot adapter (e.g. <code>so101</code>, <code>sim_so101</code>),
                then come back here.
              </>
            )}
            {(sessionBlocker === "recording" || sessionBlocker === "review") && (
              <>
                Stop the current episode on the{" "}
                <Link to="/record" className="underline font-medium">Record page</Link> before
                starting an inference session.
              </>
            )}
            {sessionBlocker === "already-inference" && (
              <>The page is rehydrating from the backend — refresh if it stays stuck.</>
            )}
          </div>
        </div>
      )}

      {s.phase === "pre-start" && (
        <PreStartPanel
          activeDataset={sessionDataset}
          disabled={!sessionReadyForInference}
        />
      )}
      {s.phase === "ready" && <ReadyPanel />}
      {s.phase === "recording" && <RecordingPanel />}
      {s.phase === "review" && <ReviewPanel />}
    </div>
  );
}


function PreStartPanel({
  activeDataset,
  disabled,
}: {
  activeDataset: string | null;
  disabled: boolean;
}) {
  const s = useInferenceStore();
  const selected = s.configs.find((c) => c.name === s.selectedConfig);
  const selectedHasError = !!selected?.error;
  const canStart = !disabled && !!s.selectedConfig && !selectedHasError && !!s.instruction;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Start an inference session</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <Field label="Inference config">
          <Select value={s.selectedConfig} onChange={(e) => s.selectConfig(e.target.value)} disabled={disabled}>
            <option value="">— select —</option>
            {s.configs.map((c) => (
              <option key={c.name} value={c.name} disabled={!!c.error}>
                {c.title && c.title !== c.name ? `${c.name} — ${c.title}` : c.name}
                {c.error ? " (load error)" : ""}
              </option>
            ))}
          </Select>
          {selected?.description && (
            <div className={`text-xs mt-1 ${selectedHasError ? "text-brand-error" : "text-steel"}`}>
              {selected.description}
            </div>
          )}
        </Field>
        <div className="text-xs text-slate">
          Successful episodes save to the active session's dataset:{" "}
          <code className="text-ink">{activeDataset ?? "—"}</code>. Switch datasets on the Record page.
        </div>
        <Field label="Instruction">
          <Input
            type="text"
            value={s.instruction}
            onChange={(e) => s.setInstruction(e.target.value)}
            placeholder="pick up the bottle"
            disabled={disabled}
          />
        </Field>
        <div>
          <Button disabled={!canStart} onClick={() => s.startSession()}>
            Start session
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}


function ReadyPanel() {
  const s = useInferenceStore();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Ready</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <Field label="Instruction (live — locks once you start an episode)">
          <div className="flex gap-2">
            <Input
              type="text"
              value={s.instruction}
              onChange={(e) => s.setInstruction(e.target.value)}
            />
            <Button variant="outline" onClick={() => s.updateInstruction()}>
              Update
            </Button>
          </div>
        </Field>
        <TelemetryBlock />
        <ActionPreview />
        <div className="flex gap-2">
          <Button onClick={() => s.startEpisode()}>Start episode</Button>
          <Button variant="outline" onClick={() => s.stopSession()}>Stop session</Button>
        </div>
      </CardContent>
    </Card>
  );
}


function RecordingPanel() {
  const s = useInferenceStore();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Recording
          <Badge variant="destructive">⏺ {s.episodeElapsedSec.toFixed(1)}s</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="text-sm">
          <span className="text-steel">Instruction (locked):</span>{" "}
          <span className="font-medium">"{s.lockedInstruction ?? ""}"</span>
        </div>
        <div className="text-sm">
          <span className="text-steel">Model done signal:</span>{" "}
          {s.telemetry.modelDoneSignal === "waiting" && <span>waiting…</span>}
          {s.telemetry.modelDoneSignal === "received" && <span className="text-brand-green-deep">received ✓</span>}
          {s.telemetry.modelDoneSignal === "unsupported" && <span className="text-stone">unsupported</span>}
        </div>
        <TelemetryBlock />
        <ActionPreview />
        <div>
          <Button variant="destructive" onClick={() => s.stopEpisode()}>Stop episode</Button>
        </div>
      </CardContent>
    </Card>
  );
}


function ReviewPanel() {
  const s = useInferenceStore();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Review</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="text-sm">
          Episode summary
          {s.reviewEpisode && (
            <> — #{s.reviewEpisode.index} ({s.reviewEpisode.durationSec.toFixed(1)}s)</>
          )}
        </div>
        <div className="flex gap-2">
          <Button onClick={() => s.commitEpisode(true)}>Save as success</Button>
          <Button variant="outline" onClick={() => s.commitEpisode(false)}>Save as failure</Button>
          <Button variant="ghost" onClick={() => s.discardEpisode()}>Discard</Button>
        </div>
      </CardContent>
    </Card>
  );
}


function TelemetryBlock() {
  const t = useInferenceStore((x) => x.telemetry);
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-2 text-sm">
      <Stat label="buffer depth" value={`${t.bufferDepth} / ${t.bufferOrigin}`} />
      <Stat
        label="last latency"
        value={t.lastLatencyMs == null ? "—" : `${t.lastLatencyMs.toFixed(1)} ms`}
      />
      <Stat label="chunks consumed" value={String(t.chunksConsumed)} />
      <Stat
        label="inference errors"
        value={String(t.inferenceErrors)}
        warn={t.inferenceErrors > 0}
      />
      <Stat label="clamps / chunk" value={t.clampsLastChunk == null ? "—" : String(t.clampsLastChunk)} />
      <Stat
        label="safety events"
        value={String(t.safetyEvents.length)}
        warn={t.safetyEvents.length > 0}
      />
    </div>
  );
}


function Stat({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-steel">{label}</div>
      <div className={`font-mono ${warn ? "text-brand-error font-semibold" : "text-ink"}`}>
        {value}
      </div>
    </div>
  );
}


function ActionPreview() {
  const a = useInferenceStore((x) => x.telemetry.nextAction);
  if (!a || !Array.isArray(a.ee_delta)) return null;
  return (
    <div className="rounded-md bg-surface-soft border border-hairline px-3 py-2 font-mono text-xs">
      <span className="text-steel">next action:</span>{" "}
      ΔEE [{a.ee_delta.map((v) => v.toFixed(3)).join(", ")}]{" "}
      gripper {typeof a.gripper === "number" ? a.gripper.toFixed(3) : "—"}
    </div>
  );
}


function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-xs text-slate mb-1">{label}</div>
      <div>{children}</div>
    </label>
  );
}
