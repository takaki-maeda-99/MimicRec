import { useCameraRoles, useConfigsWithContent, useDatasetSchema, useDatasets, useStartSession, useTasks } from "../api/queries.ts";
import { useRecordFormStore } from "../state/record-form-store.ts";
import type { SlotAssignmentDraft } from "../state/record-form-store.ts";
import { useSessionStore } from "../state/session-store.ts";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { ConfigCard } from "./ConfigCard";
import { SegmentedTab, SegmentedTabBar } from "./ui/segmented-tab";
import { SectionMark } from "./ui/section-mark";

interface Props {
  onStarted: () => void;
}

export default function SessionConfigForm({ onStarted }: Props) {
  const { data: robots } = useConfigsWithContent("robot");
  const { data: teleops } = useConfigsWithContent("teleop");
  const { data: mappers } = useConfigsWithContent("mapper");
  const { data: datasets } = useDatasets();
  const startSession = useStartSession();

  const lastError = useSessionStore((s) => s.lastError);
  const clearError = useSessionStore((s) => s.clearError);

  const form = useRecordFormStore();
  const { mode, robot, teleop, mapper, dataset, task, fps, previewEnabled, slotAssignments } = form;

  const datasetExists = !!datasets?.some(d => d.name === dataset);
  const { data: tasks } = useTasks(datasetExists ? dataset : "");

  const { data: roles } = useCameraRoles();
  const { data: schema } = useDatasetSchema(datasetExists ? dataset : undefined);
  const cameraConfigs = useConfigsWithContent("cameras").data ?? [];
  const goproConfigs = useConfigsWithContent("gopros", { optional: true }).data ?? [];
  const deviceOptions = [
    ...cameraConfigs.map(c => ({ name: c.name, kind: "camera" as const })),
    ...goproConfigs.map(g => ({ name: g.name, kind: "gopro" as const })),
  ];
  const datasetSlots = schema?.image_keys ?? [];
  const formSlots = slotAssignments.map((a: SlotAssignmentDraft) => a.slot);
  const allSlotsToShow = datasetExists
    ? datasetSlots.map(slot => ({
        slot,
        device: slotAssignments.find((a: SlotAssignmentDraft) => a.slot === slot)?.device ?? "",
        locked: true,
      }))
    : slotAssignments.map((a: SlotAssignmentDraft) => ({ ...a, locked: false }));
  const setSlotDevice = (slot: string, device: string) => {
    const next = slotAssignments.filter((a: SlotAssignmentDraft) => a.slot !== slot);
    if (device) next.push({ slot, device });
    form.set({ slotAssignments: next });
  };
  const addSlot = (slot: string) => {
    if (slotAssignments.some((a: SlotAssignmentDraft) => a.slot === slot)) return;
    form.set({ slotAssignments: [...slotAssignments, { slot, device: "" }] });
  };
  const removeSlot = (slot: string) => {
    form.set({ slotAssignments: slotAssignments.filter((a: SlotAssignmentDraft) => a.slot !== slot) });
  };
  const usedDevices = new Set(slotAssignments.map((a: SlotAssignmentDraft) => a.device).filter(Boolean));
  const availableRoles = (roles?.roles ?? []).filter(r => !formSlots.includes(r));
  const legacySlots = datasetSlots.filter(s => !(roles?.roles ?? []).includes(s) && !formSlots.includes(s));

  const handleStart = () => {
    // Clear any error left over from a prior session that ended via
    // FatalHardwareError — otherwise the stale message stays pinned next
    // to the new attempt's spinner.
    clearError();
    const body: Record<string, unknown> = {
      mode, dataset, task, robot, fps,
      slot_assignments: slotAssignments.map((a: SlotAssignmentDraft) => ({ slot: a.slot, device: a.device })),
      preview_enabled: previewEnabled,
    };
    if (mode === "teleop") {
      body.teleop = teleop;
      body.mapper = mapper;
    }
    startSession.mutate(body, { onSuccess: () => onStarted() });
  };

  return (
    <div className="max-w-[1200px] flex flex-col gap-xl">

      {/* §02.idle.A — Mode */}
      <Section code="§02.idle.A" name="Mode">
        <Field label="Mode">
          <SegmentedTabBar>
            <SegmentedTab active={mode === "teleop"} onClick={() => form.set({ mode: "teleop" })}>
              Teleop
            </SegmentedTab>
            <SegmentedTab active={mode === "hand_teach"} onClick={() => form.set({ mode: "hand_teach" })}>
              Hand Teach
            </SegmentedTab>
          </SegmentedTabBar>
        </Field>
      </Section>

      {/* §02.idle.B — Dataset, task, fps (3-column) */}
      <Section code="§02.idle.B" name="Dataset, task, fps">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-md">
          <Field label="Dataset">
            <Input
              list="existing-datasets"
              value={dataset}
              onChange={e => form.set({ dataset: e.target.value })}
              placeholder="my_dataset"
            />
            <datalist id="existing-datasets">
              {datasets?.map(d => (
                <option key={d.name} value={d.name}>
                  {d.num_episodes} episodes
                </option>
              ))}
            </datalist>
          </Field>
          <Field label="Task">
            <Input
              list="existing-tasks"
              value={task}
              onChange={e => form.set({ task: e.target.value })}
              placeholder="pick"
            />
            <datalist id="existing-tasks">
              {tasks?.map(t => (
                <option key={t.task_index} value={t.task}>
                  {t.instruction ?? ""}
                </option>
              ))}
            </datalist>
          </Field>
          <Field label="FPS">
            <Input
              type="number"
              value={fps}
              onChange={(e) => form.set({ fps: Number(e.target.value) })}
            />
          </Field>
        </div>
      </Section>

      {/* §02.idle.C — Robot */}
      <Section code="§02.idle.C" name="Robot">
        <Field label="Robot">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {robots?.map(r => (
              <ConfigCard
                key={r.name}
                config={r}
                group="robot"
                selected={robot === r.name}
                onClick={() => form.set({ robot: r.name })}
              />
            ))}
          </div>
        </Field>
      </Section>

      {/* §02.idle.D — Teleop & mapper (only shown when mode === "teleop") */}
      {mode === "teleop" && (
        <Section code="§02.idle.D" name="Teleop & mapper">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-md">
            <Field label="Teleop">
              <div className="grid grid-cols-1 gap-2">
                {teleops?.map(t => (
                  <ConfigCard
                    key={t.name}
                    config={t}
                    group="teleop"
                    selected={teleop === t.name}
                    onClick={() => form.set({ teleop: t.name })}
                  />
                ))}
              </div>
            </Field>
            <Field label="Mapper">
              <div className="grid grid-cols-1 gap-2">
                {mappers?.map(m => (
                  <ConfigCard
                    key={m.name}
                    config={m}
                    group="mapper"
                    selected={mapper === m.name}
                    onClick={() => form.set({ mapper: m.name })}
                  />
                ))}
              </div>
            </Field>
          </div>
        </Section>
      )}

      {/* §02.idle.E — Camera assignments */}
      <Section code="§02.idle.E" name="Camera assignments">
        <Field label="Camera Assignments">
          <div className="flex flex-col gap-2">
            {allSlotsToShow.map(({ slot, device, locked }) => (
              <div key={slot} className="flex items-center gap-2">
                <select
                  disabled={locked}
                  value={slot}
                  className="border border-hairline rounded px-2 py-1 text-body-sm bg-canvas"
                  onChange={() => {}}
                >
                  <option value={slot}>{slot}{legacySlots.includes(slot) ? " (legacy)" : ""}</option>
                </select>
                <select
                  value={device}
                  className="border border-hairline rounded px-2 py-1 text-body-sm bg-canvas flex-1"
                  onChange={e => setSlotDevice(slot, e.target.value)}
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
                {!locked && (
                  <button
                    type="button"
                    onClick={() => removeSlot(slot)}
                    className="text-stone hover:text-brand-error px-2"
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
            {!datasetExists && (
              <div className="flex items-center gap-2">
                <select
                  value=""
                  className="border border-hairline rounded px-2 py-1 text-body-sm bg-canvas"
                  onChange={e => { if (e.target.value) addSlot(e.target.value); }}
                >
                  <option value="">+ Add slot…</option>
                  {availableRoles.map(r => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </Field>
      </Section>

      {/* §02.idle.F — Run parameters */}
      <Section code="§02.idle.F" name="Run parameters">
        <div className="border border-hairline rounded-md p-md gap-sm flex flex-col bg-surface-soft">
          <label className="flex items-center gap-2 text-sm font-medium text-charcoal">
            <input
              type="checkbox"
              checked={form.autoCycle}
              onChange={e => form.set({ autoCycle: e.target.checked })}
            />
            Auto cycle (record &rarr; auto save &rarr; next)
          </label>
          {form.autoCycle && (
            <div className="flex gap-3 text-sm pl-6">
              <label className="flex items-center gap-1">
                Duration
                <Input
                  type="number"
                  className="w-20"
                  value={form.autoDurationSec}
                  onChange={e => form.set({ autoDurationSec: Math.max(1, Number(e.target.value) || 0) })}
                />
                <span className="text-steel">s</span>
              </label>
              <label className="flex items-center gap-1">
                Review window
                <Input
                  type="number"
                  className="w-20"
                  value={form.autoReviewSec}
                  onChange={e => form.set({ autoReviewSec: Math.max(0, Number(e.target.value) || 0) })}
                />
                <span className="text-steel">s</span>
              </label>
            </div>
          )}
          {form.autoCycle && (
            <p className="text-xs text-steel pl-6">
              During review window, press <kbd>F</kbd> to save as failure, <kbd>D</kbd> to discard, <kbd>Esc</kbd> to stop the cycle.
            </p>
          )}
          <label className="flex items-center gap-2 text-sm font-medium text-charcoal">
            <input
              type="checkbox"
              checked={previewEnabled}
              onChange={e => form.set({ previewEnabled: e.target.checked })}
            />
            ライブプレビュー表示（OFF で USB 帯域・CPU を解放）
          </label>
        </div>
      </Section>

      {/* Error blocks — contextual, before the Start button footer */}
      {startSession.isError && (
        <pre className="text-brand-error text-sm whitespace-pre-wrap font-mono bg-brand-error/10 border border-brand-error/30 rounded-md p-3">
          {(startSession.error as Error).message}
        </pre>
      )}
      {/* Errors that arrive AFTER session_start succeeded — e.g. a
          FatalHardwareError from the reader loop that ended the session
          on its own. Without this, the session quietly returns to IDLE
          and the operator is dropped back on this form with no context. */}
      {!startSession.isError && lastError && (
        <div className="bg-brand-error/10 border border-brand-error/30 rounded-md p-3 space-y-1">
          <div className="text-brand-error text-sm font-semibold">
            Previous session ended with an error: {lastError.error}
          </div>
          <pre className="text-brand-error text-sm whitespace-pre-wrap font-mono">
            {lastError.message}
          </pre>
        </div>
      )}

      {/* Start button footer */}
      <div className="flex items-center gap-md border-t border-hairline pt-lg">
        {(!robot || !dataset || !task) ? (
          <span className="text-caption text-steel">
            Pick a robot, dataset, and task to enable start.
          </span>
        ) : (
          <span className="text-caption text-steel">Ready to start.</span>
        )}
        <span className="flex-1" />
        <Button
          variant="primary"
          size="lg"
          onClick={handleStart}
          disabled={startSession.isPending || !robot || !dataset || !task}
        >
          {startSession.isPending ? "Starting..." : "Start session"}
        </Button>
      </div>

    </div>
  );
}

function Section({ code, name, children }: { code: string; name: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-md">
      <header className="flex items-baseline gap-md">
        <SectionMark code={code} name={name} />
        <span className="flex-1 h-px bg-hairline-soft" />
      </header>
      {children}
    </section>
  );
}

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold">
        {label}
      </label>
      {children}
      {hint && <div className="text-caption text-steel">{hint}</div>}
    </div>
  );
}
