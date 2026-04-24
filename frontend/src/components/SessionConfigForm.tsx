import { useState } from "react";
import { useConfigs, useStartSession } from "../api/queries.ts";

interface Props {
  onStarted: () => void;
}

export default function SessionConfigForm({ onStarted }: Props) {
  const { data: robots } = useConfigs("robot");
  const { data: teleops } = useConfigs("teleop");
  const { data: mappers } = useConfigs("mapper");
  const { data: cameras } = useConfigs("cameras");
  const startSession = useStartSession();

  const [mode, setMode] = useState<"teleop" | "hand_teach">("teleop");
  const [robot, setRobot] = useState("");
  const [teleop, setTeleop] = useState("");
  const [mapper, setMapper] = useState("");
  const [selectedCams, setSelectedCams] = useState<string[]>([]);
  const [dataset, setDataset] = useState("");
  const [task, setTask] = useState("");
  const [fps, setFps] = useState(30);

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
        <select className="w-full border rounded-md px-3 py-2 text-sm" value={mode} onChange={e => setMode(e.target.value as "teleop" | "hand_teach")}>
          <option value="teleop">Teleop</option>
          <option value="hand_teach">Hand Teach</option>
        </select>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Dataset</label>
        <input className="w-full border rounded-md px-3 py-2 text-sm" value={dataset} onChange={e => setDataset(e.target.value)} placeholder="my_dataset" />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Task</label>
        <input className="w-full border rounded-md px-3 py-2 text-sm" value={task} onChange={e => setTask(e.target.value)} placeholder="pick" />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Robot</label>
        <select className="w-full border rounded-md px-3 py-2 text-sm" value={robot} onChange={e => setRobot(e.target.value)}>
          <option value="">Select...</option>
          {robots?.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
      </div>
      {mode === "teleop" && (
        <>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Teleop</label>
            <select className="w-full border rounded-md px-3 py-2 text-sm" value={teleop} onChange={e => setTeleop(e.target.value)}>
              <option value="">Select...</option>
              {teleops?.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Mapper</label>
            <select className="w-full border rounded-md px-3 py-2 text-sm" value={mapper} onChange={e => setMapper(e.target.value)}>
              <option value="">Select...</option>
              {mappers?.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
        </>
      )}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Cameras</label>
        <div className="space-y-1">
          {cameras?.map(c => (
            <label key={c} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={selectedCams.includes(c)} onChange={e => {
                setSelectedCams(prev => e.target.checked ? [...prev, c] : prev.filter(x => x !== c));
              }} />
              {c}
            </label>
          ))}
        </div>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">FPS</label>
        <input type="number" className="w-20 border rounded-md px-3 py-2 text-sm" value={fps} onChange={e => setFps(Number(e.target.value))} />
      </div>
      <button
        className="bg-blue-600 text-white px-6 py-2 rounded-md text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        onClick={handleStart}
        disabled={startSession.isPending || !robot || !dataset || !task}
      >
        {startSession.isPending ? "Starting..." : "Start Session"}
      </button>
      {startSession.isError && (
        <p className="text-red-600 text-sm">{(startSession.error as Error).message}</p>
      )}
    </div>
  );
}
