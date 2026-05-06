import { useState } from "react";
import { useExportDataset, useTasks } from "../api/queries.ts";
import { ApiError } from "../api/client.ts";
import type { ExportFormat, RobotTypeOverride } from "../api/types.ts";

const DEFAULT_TEMPLATE = "What action should the robot take to {TASK}? A:";

interface Props {
  ds: string;
  onClose: () => void;
}

export function ExportDatasetModal({ ds, onClose }: Props) {
  const [format, setFormat] = useState<ExportFormat>("vla_compat");
  const [template, setTemplate] = useState<string>(DEFAULT_TEMPLATE);
  const [force, setForce] = useState<boolean>(false);
  const [needsForce, setNeedsForce] = useState<boolean>(false);
  // "" = no override (use info.json); "so101" / "rebot" = override for legacy
  // datasets where info.json declares robot_type='unknown'.
  const [robotType, setRobotType] = useState<"" | RobotTypeOverride>("");
  const exportMutation = useExportDataset(ds);
  const { data: tasks } = useTasks(ds);

  const handleSubmit = () => {
    setNeedsForce(false);
    exportMutation.mutate(
      {
        format,
        instruction_template: template,
        force,
        ...(robotType ? { robot_type: robotType } : {}),
      },
      {
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            setNeedsForce(true);
            setForce(true);
          }
        },
      },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-[640px] rounded-lg bg-white p-6 shadow-xl">
        <h2 className="mb-4 text-lg font-semibold">Export "{ds}"</h2>

        <fieldset className="mb-4">
          <legend className="mb-2 text-sm font-medium">Format</legend>
          <label className="mb-1 flex items-center gap-2">
            <input type="radio" checked={format === "lerobot_v3_native"}
                   onChange={() => setFormat("lerobot_v3_native")} />
            LeRobot v3 native (raw recorded columns)
          </label>
          <label className="flex items-center gap-2">
            <input type="radio" checked={format === "vla_compat"}
                   onChange={() => setFormat("vla_compat")} />
            VLA-compat (EE-delta + gripper, instruction-conditioned)
          </label>
        </fieldset>

        {format === "vla_compat" && (
          <>
            <label className="mb-1 block text-sm font-medium">Instruction template</label>
            <textarea className="mb-2 w-full rounded border border-gray-300 p-2 text-sm"
                      rows={2} value={template}
                      onChange={(e) => setTemplate(e.target.value)} />
            <p className="mb-4 text-xs text-gray-500">
              <code>{"{TASK}"}</code> is replaced per episode with each task's instruction
              (or task name when instruction is empty).
            </p>

            <label className="mb-1 block text-sm font-medium">Robot-type override (legacy datasets)</label>
            <select className="mb-1 w-full rounded border border-gray-300 p-2 text-sm"
                    value={robotType}
                    onChange={(e) => setRobotType(e.target.value as "" | RobotTypeOverride)}>
              <option value="">Auto (use info.json)</option>
              <option value="so101">SO-101</option>
              <option value="rebot">reBot</option>
            </select>
            <p className="mb-4 text-xs text-gray-500">
              Set this only if the export fails because <code>info.json</code> declares
              <code className="mx-1">robot_type=&quot;unknown&quot;</code>
              (datasets recorded before adapter declarations were tracked).
            </p>

            <div className="mb-4 max-h-32 overflow-auto rounded border border-gray-200 p-2 text-xs">
              <div className="mb-1 font-medium">Tasks in this dataset:</div>
              {tasks?.map((t) => (
                <div key={t.task_index} className="flex justify-between gap-3 py-0.5">
                  <span className="font-mono">{t.task}</span>
                  <span className={t.instruction ? "text-gray-700" : "text-amber-600"}>
                    {t.instruction || "(no instruction — will fall back to task name)"}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}

        {needsForce && (
          <div className="mb-3 rounded bg-amber-50 p-2 text-sm text-amber-800">
            Destination already exists. Tick "Overwrite" and submit again to replace it.
          </div>
        )}
        <label className="mb-4 flex items-center gap-2 text-sm">
          <input type="checkbox" checked={force}
                 onChange={(e) => setForce(e.target.checked)} />
          Overwrite existing destination
        </label>

        {exportMutation.isSuccess && (
          <div className="mb-3 rounded bg-green-50 p-2 text-sm text-green-800">
            Exported {exportMutation.data.num_episodes} episodes
            ({exportMutation.data.num_frames} frames) to{" "}
            <code>{exportMutation.data.dest_path}</code>
            {exportMutation.data.warnings.length > 0 && (
              <ul className="mt-1 list-disc pl-4 text-xs text-amber-700">
                {exportMutation.data.warnings.map((w) => <li key={w}>{w}</li>)}
              </ul>
            )}
          </div>
        )}
        {exportMutation.isError && !needsForce && (
          <div className="mb-3 rounded bg-red-50 p-2 text-sm text-red-800">
            {exportMutation.error.message}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button className="rounded border border-gray-300 px-3 py-1 text-sm" onClick={onClose}>
            Close
          </button>
          <button className="rounded bg-blue-600 px-3 py-1 text-sm text-white disabled:opacity-50"
                  disabled={exportMutation.isPending} onClick={handleSubmit}>
            {exportMutation.isPending ? "Exporting…" : "Export"}
          </button>
        </div>
      </div>
    </div>
  );
}
