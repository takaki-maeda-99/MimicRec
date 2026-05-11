import { useConfigsWithContent, useDatasets, useStartSession, useTasks } from "../api/queries.ts";
import { useRecordFormStore } from "../state/record-form-store.ts";
import { useSessionStore } from "../state/session-store.ts";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { ConfigCard } from "./ConfigCard";
import { SegmentedTab, SegmentedTabBar } from "./ui/segmented-tab";

interface Props {
  onStarted: () => void;
}

export default function SessionConfigForm({ onStarted }: Props) {
  const { data: robots } = useConfigsWithContent("robot");
  const { data: teleops } = useConfigsWithContent("teleop");
  const { data: mappers } = useConfigsWithContent("mapper");
  const { data: cameras } = useConfigsWithContent("cameras");
  const { data: gopros } = useConfigsWithContent("gopros", { optional: true });
  const { data: datasets } = useDatasets();
  const startSession = useStartSession();

  const lastError = useSessionStore((s) => s.lastError);
  const clearError = useSessionStore((s) => s.clearError);

  const form = useRecordFormStore();
  const { mode, robot, teleop, mapper, dataset, task, fps, previewEnabled } = form;
  const selectedCams: string[] = [];  // TEMPORARY: removed by T16
  const selectedGopros: string[] = [];  // TEMPORARY: removed by T16

  const datasetExists = !!datasets?.some(d => d.name === dataset);
  const { data: tasks } = useTasks(datasetExists ? dataset : "");

  const handleStart = () => {
    // Clear any error left over from a prior session that ended via
    // FatalHardwareError — otherwise the stale message stays pinned next
    // to the new attempt's spinner.
    clearError();
    const body: Record<string, unknown> = {
      mode, dataset, task, robot, cameras: selectedCams, gopros: selectedGopros, fps,
      preview_enabled: previewEnabled,
    };
    if (mode === "teleop") {
      body.teleop = teleop;
      body.mapper = mapper;
    }
    startSession.mutate(body, { onSuccess: () => onStarted() });
  };

  return (
    <div className="space-y-md max-w-[40rem]">
      <div>
        <label className="block text-body-sm-medium text-charcoal mb-xs">Mode</label>
        <SegmentedTabBar>
          <SegmentedTab active={mode === "teleop"} onClick={() => form.set({ mode: "teleop" })}>
            Teleop
          </SegmentedTab>
          <SegmentedTab active={mode === "hand_teach"} onClick={() => form.set({ mode: "hand_teach" })}>
            Hand Teach
          </SegmentedTab>
        </SegmentedTabBar>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-md">
        <div>
          <label className="block text-body-sm-medium text-charcoal mb-xs">Dataset</label>
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
        </div>
        <div>
          <label className="block text-body-sm-medium text-charcoal mb-xs">Task</label>
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
        </div>
      </div>
      <div>
        <label className="block text-body-sm-medium text-charcoal mb-xs">Robot</label>
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
      </div>
      {mode === "teleop" && (
        <>
          <div>
            <label className="block text-body-sm-medium text-charcoal mb-xs">Teleop</label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
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
          </div>
          <div>
            <label className="block text-body-sm-medium text-charcoal mb-xs">Mapper</label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
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
          </div>
        </>
      )}
      <div>
        <label className="block text-body-sm-medium text-charcoal mb-xs">
          Cameras <span className="text-stone font-normal">(複数選択)</span>
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {cameras?.map(c => (
            <ConfigCard
              key={c.name}
              config={c}
              group="cameras"
              multiSelect
              selected={selectedCams.includes(c.name)}
              onClick={() => {
                // TEMPORARY: camera selection rewritten in T16
              }}
            />
          ))}
        </div>
      </div>
      {gopros && gopros.length > 0 && (
        <div>
          <label className="block text-body-sm-medium text-charcoal mb-xs">
            GoPros <span className="text-stone font-normal">(複数選択)</span>
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {gopros.map(g => (
              <ConfigCard
                key={g.name}
                config={g}
                group="gopros"
                multiSelect
                selected={selectedGopros.includes(g.name)}
                onClick={() => {
                  // TEMPORARY: gopro selection rewritten in T16
                }}
              />
            ))}
          </div>
        </div>
      )}
      <div>
        <label className="block text-sm font-medium text-charcoal mb-1">FPS</label>
        <Input type="number" className="w-20" value={fps} onChange={e => form.set({ fps: Number(e.target.value) })} />
      </div>
      <div className="border border-hairline rounded-md p-3 space-y-2 bg-surface-soft">
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
      <Button
        onClick={handleStart}
        disabled={startSession.isPending || !robot || !dataset || !task}
      >
        {startSession.isPending ? "Starting..." : "Start Session"}
      </Button>
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
    </div>
  );
}
