// frontend/src/components/ConfigEditorModal.tsx
import { useState, useEffect } from "react";
import { apiFetch } from "../api/client";
import { Button } from "./ui/button";
import { CameraConfigForm } from "./CameraConfigForm";
import type { ConfigGroup } from "./ConfigCard";

export interface ConfigEntry {
  name: string;
  group: ConfigGroup;
  content: Record<string, unknown>;
}

export type ConfigEditorMode = "edit" | "new" | "clone";

interface Props {
  config: ConfigEntry | null;        // null = closed
  mode: ConfigEditorMode;
  onClose: () => void;
  onSaved: (saved: ConfigEntry) => void;
}

export function ConfigEditorModal({ config, mode, onClose, onSaved }: Props) {
  const [editJson, setEditJson] = useState("");
  const [editName, setEditName] = useState("");

  useEffect(() => {
    if (!config) return;
    setEditJson(JSON.stringify(config.content, null, 2));
    setEditName(mode === "clone" || mode === "new" ? "" : config.name);
  }, [config, mode]);

  if (!config) return null;

  const isCamera =
    config.group === "cameras"
    && (config.content as Record<string, unknown>)._target_
        === "mimicrec.cameras.opencv_camera.OpenCVCamera";

  const handleSave = async () => {
    try {
      const content = JSON.parse(editJson);
      const name = (mode === "edit") ? config.name : editName;
      if (!name) {
        alert("Name is required");
        return;
      }
      const method = mode === "edit" ? "PUT" : "POST";
      await apiFetch(`/api/settings/configs/${config.group}/${name}`, {
        method,
        body: JSON.stringify({ content }),
      });
      onSaved({ ...config, name, content });
      onClose();
    } catch (e) {
      alert(`Save failed: ${e}`);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-canvas-dark/40"
      onClick={onClose}
    >
      <div
        className="bg-canvas rounded-lg border border-hairline p-xl w-[600px] max-h-[80vh] overflow-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {isCamera && mode === "edit" ? (
          <CameraConfigForm
            name={config.name}
            currentContent={config.content as Record<string, unknown>}
            onSave={(validationSkipped) => {
              onClose();
              if (validationSkipped) {
                alert(
                  "Saved. Camera was busy so the configured parameters " +
                  "will be validated when the next session starts.",
                );
              }
              onSaved(config);
            }}
            onCancel={onClose}
          />
        ) : (
          <>
            <h3 className="text-heading-5 text-ink mb-xs">
              {mode === "edit" && `Edit ${config.group}/${config.name}`}
              {mode === "new" && `New ${config.group}`}
              {mode === "clone" && `Clone ${config.group}/${config.name}`}
            </h3>
            {(mode === "new" || mode === "clone") && (
              <input
                type="text"
                placeholder="config name (without .yaml)"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                className="w-full border border-hairline rounded px-3 py-2 mb-md font-mono text-code-sm"
              />
            )}
            <textarea
              className="w-full h-64 rounded-md border border-hairline bg-canvas p-md font-mono text-code-sm text-charcoal mb-md focus:outline-none focus:border-2 focus:border-ink"
              value={editJson}
              onChange={(e) => setEditJson(e.target.value)}
            />
            <div className="flex justify-end gap-xs">
              <Button variant="secondary" onClick={onClose}>Cancel</Button>
              <Button onClick={handleSave}>Save</Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
