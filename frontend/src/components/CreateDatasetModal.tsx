import { useState } from "react";
import { useCreateDataset } from "../api/queries";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

interface Props {
  onClose: () => void;
}

export function CreateDatasetModal({ onClose }: Props) {
  const createMutation = useCreateDataset();
  const [name, setName] = useState("");
  const [fps, setFps] = useState(30);

  const handleCreate = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    createMutation.mutate(
      { name: trimmed, fps, joint_names: [], camera_names: [] },
      {
        onSuccess: () => {
          setName("");
          onClose();
        },
      },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-canvas-dark/40" onClick={onClose}>
      <div
        className="w-[420px] max-w-full bg-canvas rounded-lg border border-hairline p-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-heading-5 text-ink mb-md">New Dataset</h3>
        <div className="flex flex-col gap-md">
          <label className="text-body-sm-medium text-charcoal">
            Name
            <Input
              className="mt-1"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="my_dataset"
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              autoFocus
            />
          </label>
          <label className="text-body-sm-medium text-charcoal">
            FPS
            <Input
              className="mt-1 w-24"
              type="number"
              value={fps}
              onChange={(e) => setFps(Number(e.target.value))}
            />
          </label>
        </div>
        <div className="mt-xl flex justify-end gap-xs">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button onClick={handleCreate} disabled={createMutation.isPending || !name.trim()}>
            Create
          </Button>
        </div>
      </div>
    </div>
  );
}
