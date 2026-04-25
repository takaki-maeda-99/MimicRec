import { useState } from "react";
import { useConfigs, useStartSession } from "../api/queries.ts";
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
        <Select value={mode} onChange={e => setMode(e.target.value as "teleop" | "hand_teach")}>
          <option value="teleop">Teleop</option>
          <option value="hand_teach">Hand Teach</option>
        </Select>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Dataset</label>
        <Input value={dataset} onChange={e => setDataset(e.target.value)} placeholder="my_dataset" />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Task</label>
        <Input value={task} onChange={e => setTask(e.target.value)} placeholder="pick" />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Robot</label>
        <Select value={robot} onChange={e => setRobot(e.target.value)}>
          <option value="">Select...</option>
          {robots?.map(r => <option key={r} value={r}>{r}</option>)}
        </Select>
      </div>
      {mode === "teleop" && (
        <>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Teleop</label>
            <Select value={teleop} onChange={e => setTeleop(e.target.value)}>
              <option value="">Select...</option>
              {teleops?.map(t => <option key={t} value={t}>{t}</option>)}
            </Select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Mapper</label>
            <Select value={mapper} onChange={e => setMapper(e.target.value)}>
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
                setSelectedCams(prev => e.target.checked ? [...prev, c] : prev.filter(x => x !== c));
              }} />
              {c}
            </label>
          ))}
        </div>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">FPS</label>
        <Input type="number" className="w-20" value={fps} onChange={e => setFps(Number(e.target.value))} />
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
