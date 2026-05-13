import { useCameraRoles, useConfigsWithContent, useDatasetSchema, useDatasets, useStartSession, useTasks } from "../api/queries.ts";
import { useRecordFormStore } from "../state/record-form-store.ts";
import type { SlotAssignmentDraft } from "../state/record-form-store.ts";
import { useSessionStore } from "../state/session-store.ts";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { SegmentedTab, SegmentedTabBar } from "./ui/segmented-tab";
import { SectionMark } from "./ui/section-mark";
import { CameraSlotRow, AddSlotButton } from "./CameraSlotRow";
import type { DeviceOption } from "./CameraSlotRow";
import type { ConfigEditorMode } from "./ConfigEditorModal";
import { ConfigPickerRow } from "./ConfigPickerRow";
import type { ConfigGroup } from "./ConfigCard";

interface Props {
  onStarted: () => void;
  onEditConfig?: (group: ConfigGroup, name: string, mode: ConfigEditorMode) => void;
}

export default function SessionConfigForm({ onStarted, onEditConfig }: Props) {
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
  const deviceOptions: DeviceOption[] = [
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
    <form
      className="flex flex-col h-full min-h-0"
      onSubmit={(e) => { e.preventDefault(); handleStart(); }}
    >
      {/* Two-column body */}
      <div className="flex-1 min-h-0 overflow-auto px-xl py-lg">
        <div className="max-w-[1280px] mx-auto grid grid-cols-1 xl:grid-cols-2 gap-xxxl">

          {/* §02.A — RUN SHEET (left column) */}
          <section className="flex flex-col gap-md min-w-0">
            <header className="flex items-baseline gap-md">
              <SectionMark code="§02.A" name="Run sheet" />
              <span className="flex-1 h-px bg-hairline-soft" />
            </header>

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

            <Field label="Dataset">
              <Input
                list="existing-datasets"
                value={dataset}
                onChange={e => form.set({ dataset: e.target.value })}
                placeholder="my_dataset"
                className="truncate"
              />
              <datalist id="existing-datasets">
                {datasets?.map(d => (
                  <option key={d.name} value={d.name}>{d.num_episodes} episodes</option>
                ))}
              </datalist>
            </Field>

            <Field label="Task">
              <Input
                list="existing-tasks"
                value={task}
                onChange={e => form.set({ task: e.target.value })}
                placeholder="pick"
                className="truncate"
              />
              <datalist id="existing-tasks">
                {tasks?.map(t => (
                  <option key={t.task_index} value={t.task}>{t.instruction ?? ""}</option>
                ))}
              </datalist>
            </Field>

            <Field label="FPS">
              <Input
                type="number"
                className="w-24"
                value={fps}
                onChange={e => form.set({ fps: Number(e.target.value) })}
              />
            </Field>

            <Field label="Parameters">
              <div className="border border-hairline rounded-md p-md gap-sm flex flex-col bg-surface-soft">
                <label className="flex items-center gap-2 text-body-sm-medium text-charcoal">
                  <input
                    type="checkbox"
                    checked={form.autoCycle}
                    onChange={e => form.set({ autoCycle: e.target.checked })}
                  />
                  Auto cycle <span className="text-caption text-steel">— record → save → next</span>
                </label>
                {form.autoCycle && (
                  <>
                    <div className="flex gap-3 text-body-sm pl-6">
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
                        Review
                        <Input
                          type="number"
                          className="w-20"
                          value={form.autoReviewSec}
                          onChange={e => form.set({ autoReviewSec: Math.max(0, Number(e.target.value) || 0) })}
                        />
                        <span className="text-steel">s</span>
                      </label>
                    </div>
                    <p className="text-caption text-steel pl-6">
                      F = fail · D = discard · Esc = stop
                    </p>
                  </>
                )}
                <label className="flex items-center gap-2 text-body-sm-medium text-charcoal">
                  <input
                    type="checkbox"
                    checked={previewEnabled}
                    onChange={e => form.set({ previewEnabled: e.target.checked })}
                  />
                  Live preview <span className="text-caption text-steel">— turn off to free USB / CPU</span>
                </label>
              </div>
            </Field>
          </section>

          {/* §02.B — HARDWARE (right column) */}
          <section className="flex flex-col gap-md min-w-0">
            <header className="flex items-baseline gap-md">
              <SectionMark code="§02.B" name="Hardware" />
              <span className="flex-1 h-px bg-hairline-soft" />
            </header>

            <Field label="Robot">
              <ConfigPickerRow
                group="robot"
                selected={robot}
                configs={robots ?? []}
                onSelect={(name) => form.set({ robot: name })}
                onEdit={(name) => onEditConfig?.("robot", name, "edit")}
                onNew={() => onEditConfig?.("robot", "", "new")}
              />
            </Field>

            {mode === "teleop" && (
              <>
                <Field label="Teleop">
                  <ConfigPickerRow
                    group="teleop"
                    selected={teleop}
                    configs={teleops ?? []}
                    onSelect={(name) => form.set({ teleop: name })}
                    onEdit={(name) => onEditConfig?.("teleop", name, "edit")}
                    onNew={() => onEditConfig?.("teleop", "", "new")}
                  />
                </Field>
                <Field label="Mapper">
                  <ConfigPickerRow
                    group="mapper"
                    selected={mapper}
                    configs={mappers ?? []}
                    onSelect={(name) => form.set({ mapper: name })}
                    onEdit={(name) => onEditConfig?.("mapper", name, "edit")}
                    onNew={() => onEditConfig?.("mapper", "", "new")}
                  />
                </Field>
              </>
            )}

            <Field label="Cameras">
              <div className="flex flex-col gap-2">
                {allSlotsToShow.map(({ slot, device, locked }) => (
                  <CameraSlotRow
                    key={slot}
                    slot={slot}
                    device={device}
                    locked={locked}
                    legacy={legacySlots.includes(slot)}
                    deviceOptions={deviceOptions}
                    usedDevices={usedDevices}
                    onChange={(d) => setSlotDevice(slot, d)}
                    onRemove={!locked ? () => removeSlot(slot) : undefined}
                    onEdit={(d) => {
                      const kind = deviceOptions.find(o => o.name === d)?.kind ?? "camera";
                      onEditConfig?.(kind === "gopro" ? "gopros" : "cameras", d, "edit");
                    }}
                  />
                ))}
                {!datasetExists && (
                  <AddSlotButton
                    roles={availableRoles}
                    existingSlots={formSlots}
                    onAdd={addSlot}
                  />
                )}
              </div>
            </Field>
          </section>

        </div>
      </div>

      {/* Error block */}
      {(startSession.isError || (!startSession.isError && lastError)) && (
        <div className="px-xl pb-2">
          {startSession.isError && (
            <pre className="text-brand-error text-sm whitespace-pre-wrap font-mono bg-brand-error/10 border border-brand-error/30 rounded-md p-3">
              {(startSession.error as Error).message}
            </pre>
          )}
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
        </div>
      )}

      {/* Footer — Start button anchored at bottom */}
      <div className="flex-shrink-0 border-t border-hairline bg-canvas px-xl py-md flex items-center justify-end gap-md">
        {(!robot || !dataset || !task) && (
          <span className="text-caption text-steel">
            Pick a robot, dataset, and task to enable start.
          </span>
        )}
        <Button
          variant="primary"
          size="lg"
          type="submit"
          disabled={startSession.isPending || !robot || !dataset || !task}
        >
          {startSession.isPending ? "Starting..." : "Start session →"}
        </Button>
      </div>
    </form>
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
