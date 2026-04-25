import { useConfigs, useDatasets, useStartSession, useTasks } from "../api/queries.ts";
import { useRecordFormStore } from "../state/record-form-store.ts";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Select } from "./ui/select";

interface Props {
  onStarted: () => void;
}

export default function SessionConfigForm({ onStarted }: Props) {
  const { data: robots } = useConfigs("robot");
  const { data: teleops } = useConfigs("teleop");
  const { data: mappers } = useConfigs("mapper");
  const { data: cameras } = useConfigs("cameras");
  const { data: datasets } = useDatasets();
  const startSession = useStartSession();

  const form = useRecordFormStore();
  const { mode, robot, teleop, mapper, selectedCams, dataset, task, fps } = form;

  const datasetExists = !!datasets?.some(d => d.name === dataset);
  const { data: tasks } = useTasks(datasetExists ? dataset : "");

  const handleStart = () => {
    const body: Record<string, unknown> = {
      mode, dataset, task, robot, cameras: selectedCams, fps,
    };
    if (mode === "teleop") {
      body.teleop = teleop;
      body.mapper = mapper;
    }
    startSession.mutate(body, { onSuccess: () => onStarted() });
  };

  return (
    <div className="space-y-4 max-w-md">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Mode</label>
        <Select value={mode} onChange={e => form.set({ mode: e.target.value as "teleop" | "hand_teach" })}>
          <option value="teleop">Teleop</option>
          <option value="hand_teach">Hand Teach</option>
        </Select>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Dataset</label>
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
        <label className="block text-sm font-medium text-gray-700 mb-1">Task</label>
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
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Robot</label>
        <Select value={robot} onChange={e => form.set({ robot: e.target.value })}>
          <option value="">Select...</option>
          {robots?.map(r => <option key={r} value={r}>{r}</option>)}
        </Select>
      </div>
      {mode === "teleop" && (
        <>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Teleop</label>
            <Select value={teleop} onChange={e => form.set({ teleop: e.target.value })}>
              <option value="">Select...</option>
              {teleops?.map(t => <option key={t} value={t}>{t}</option>)}
            </Select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Mapper</label>
            <Select value={mapper} onChange={e => form.set({ mapper: e.target.value })}>
              <option value="">Select...</option>
              {mappers?.map(m => <option key={m} value={m}>{m}</option>)}
            </Select>
          </div>
        </>
      )}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Cameras</label>
        <div className="space-y-1">
          {cameras?.map(c => (
            <label key={c} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={selectedCams.includes(c)} onChange={e => {
                form.set({
                  selectedCams: e.target.checked
                    ? [...selectedCams, c]
                    : selectedCams.filter(x => x !== c),
                });
              }} />
              {c}
            </label>
          ))}
        </div>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">FPS</label>
        <Input type="number" className="w-20" value={fps} onChange={e => form.set({ fps: Number(e.target.value) })} />
      </div>
      <div className="border rounded-md p-3 space-y-2 bg-gray-50">
        <label className="flex items-center gap-2 text-sm font-medium text-gray-700">
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
              <span className="text-gray-500">s</span>
            </label>
            <label className="flex items-center gap-1">
              Review window
              <Input
                type="number"
                className="w-20"
                value={form.autoReviewSec}
                onChange={e => form.set({ autoReviewSec: Math.max(0, Number(e.target.value) || 0) })}
              />
              <span className="text-gray-500">s</span>
            </label>
          </div>
        )}
        {form.autoCycle && (
          <p className="text-xs text-gray-500 pl-6">
            During review window, press <kbd>F</kbd> to save as failure, <kbd>D</kbd> to discard, <kbd>Esc</kbd> to stop the cycle.
          </p>
        )}
      </div>
      <Button
        onClick={handleStart}
        disabled={startSession.isPending || !robot || !dataset || !task}
      >
        {startSession.isPending ? "Starting..." : "Start Session"}
      </Button>
      {startSession.isError && (
        <p className="text-red-600 text-sm">{(startSession.error as Error).message}</p>
      )}
    </div>
  );
}
