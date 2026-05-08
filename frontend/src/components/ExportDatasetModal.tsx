import { useState } from "react";
import { useExportDataset, useTasks } from "../api/queries.ts";
import { ApiError } from "../api/client.ts";
import type { ExportFormat, RobotTypeOverride } from "../api/types.ts";
import { Button } from "./ui/button";

const DEFAULT_TEMPLATE = "What action should the robot take to {TASK}? A:";

type Destination = "server" | "zip";

interface Props {
  ds: string;
  onClose: () => void;
}

export function ExportDatasetModal({ ds, onClose }: Props) {
  const [format, setFormat] = useState<ExportFormat>("vla_compat");
  const [destination, setDestination] = useState<Destination>("server");
  const [template, setTemplate] = useState<string>(DEFAULT_TEMPLATE);
  const [force, setForce] = useState<boolean>(false);
  const [needsForce, setNeedsForce] = useState<boolean>(false);
  const [robotType, setRobotType] = useState<"" | RobotTypeOverride>("");
  const exportMutation = useExportDataset(ds);
  const { data: tasks } = useTasks(ds);

  const handleSubmit = () => {
    setNeedsForce(false);
    if (destination === "zip") {
      const params = new URLSearchParams({ format });
      if (format === "vla_compat") {
        params.set("instruction_template", template);
        if (robotType) params.set("robot_type", robotType);
      }
      window.location.href = `/api/datasets/${encodeURIComponent(ds)}/archive?${params.toString()}`;
      return;
    }
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-canvas-dark/40">
      <div className="w-[640px] bg-canvas rounded-lg border border-hairline p-xl shadow-xl">
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

        <fieldset className="mb-4">
          <legend className="mb-2 text-sm font-medium">Output destination</legend>
          <label className="mb-1 flex items-center gap-2">
            <input type="radio" checked={destination === "server"}
                   onChange={() => setDestination("server")} />
            Save to server (writes to <code className="text-xs">vla_dest_root</code>)
          </label>
          <label className="flex items-center gap-2">
            <input type="radio" checked={destination === "zip"}
                   onChange={() => setDestination("zip")} />
            Download as zip (browser file download)
          </label>
        </fieldset>

        {format === "vla_compat" && (
          <>
            <label className="mb-1 block text-sm font-medium">Instruction template</label>
            <textarea className="mb-2 w-full rounded border border-hairline p-2 text-sm"
                      rows={2} value={template}
                      onChange={(e) => setTemplate(e.target.value)} />
            <p className="mb-4 text-xs text-steel">
              <code>{"{TASK}"}</code> is replaced per episode with each task's instruction
              (or task name when instruction is empty).
            </p>

            <label className="mb-1 block text-sm font-medium">Robot-type override (legacy datasets)</label>
            <select className="mb-1 w-full rounded border border-hairline p-2 text-sm"
                    value={robotType}
                    onChange={(e) => setRobotType(e.target.value as "" | RobotTypeOverride)}>
              <option value="">Auto (use info.json)</option>
              <option value="so101">SO-101</option>
              <option value="rebot">reBot</option>
            </select>
            <p className="mb-4 text-xs text-steel">
              Set this only if the export fails because <code>info.json</code> declares
              <code className="mx-1">robot_type=&quot;unknown&quot;</code>
              (datasets recorded before adapter declarations were tracked).
            </p>

            <div className="mb-4 max-h-32 overflow-auto rounded border border-hairline p-2 text-xs">
              <div className="mb-1 font-medium">Tasks in this dataset:</div>
              {tasks?.map((t) => (
                <div key={t.task_index} className="flex justify-between gap-3 py-0.5">
                  <span className="font-mono">{t.task}</span>
                  <span className={t.instruction ? "text-charcoal" : "text-brand-warn"}>
                    {t.instruction || "(no instruction — will fall back to task name)"}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}

        {destination === "server" && needsForce && (
          <div className="mb-3 rounded bg-brand-warn/10 p-2 text-sm text-brand-warn">
            Destination already exists. Tick "Overwrite" and submit again to replace it.
          </div>
        )}
        {destination === "server" && (
          <label className="mb-4 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={force}
                   onChange={(e) => setForce(e.target.checked)} />
            Overwrite existing destination
          </label>
        )}

        {destination === "server" && exportMutation.isSuccess && (
          <div className="mb-3 rounded bg-brand-green/10 p-2 text-sm text-brand-green-deep">
            Exported {exportMutation.data.num_episodes} episodes
            ({exportMutation.data.num_frames} frames) to{" "}
            <code>{exportMutation.data.dest_path}</code>
            {exportMutation.data.warnings.length > 0 && (
              <ul className="mt-1 list-disc pl-4 text-xs text-brand-warn">
                {exportMutation.data.warnings.map((w) => <li key={w}>{w}</li>)}
              </ul>
            )}
          </div>
        )}
        {destination === "server" && exportMutation.isError && !needsForce && (
          <div className="mb-3 rounded bg-brand-error/10 p-2 text-sm text-brand-error">
            {exportMutation.error.message}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <Button
            variant="primary"
            disabled={destination === "server" && exportMutation.isPending}
            onClick={handleSubmit}
          >
            {destination === "server" && exportMutation.isPending
              ? "Exporting…"
              : destination === "zip"
                ? "Download zip"
                : "Export"}
          </Button>
        </div>
      </div>
    </div>
  );
}
