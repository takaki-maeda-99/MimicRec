import { useEffect, useState } from "react";
import { apiFetch } from "../api/client";
import { Button } from "../components/ui/button";

interface SerialDevice {
  port: string;
  available: boolean;
}

interface CameraDevice {
  path: string;
  device_id: number;
  available: boolean;
  width: number;
  height: number;
}

interface ConfigEntry {
  name: string;
  group: string;
  content: Record<string, unknown>;
}

const CONFIG_GROUPS = ["robot", "teleop", "mapper", "cameras"];

export default function SettingsPage() {
  const [serialPorts, setSerialPorts] = useState<SerialDevice[]>([]);
  const [cameras, setCameras] = useState<CameraDevice[]>([]);
  const [configs, setConfigs] = useState<Record<string, ConfigEntry[]>>({});
  const [editingConfig, setEditingConfig] = useState<ConfigEntry | null>(null);
  const [editJson, setEditJson] = useState("");
  const [calibrations, setCalibrations] = useState<Record<string, Record<string, string[]>>>({});
  const [refreshingDevices, setRefreshingDevices] = useState(false);
  const [refreshingConfigs, setRefreshingConfigs] = useState(false);
  const [refreshingCalibrations, setRefreshingCalibrations] = useState(false);

  const loadDevices = async () => {
    setRefreshingDevices(true);
    try {
      const [serial, cams] = await Promise.all([
        apiFetch<SerialDevice[]>("/api/settings/devices/serial"),
        apiFetch<CameraDevice[]>("/api/settings/devices/cameras"),
      ]);
      setSerialPorts(serial);
      setCameras(cams);
    } catch (e) {
      alert(`Failed to refresh devices: ${e}`);
    } finally {
      setRefreshingDevices(false);
    }
  };

  const loadConfigs = async () => {
    setRefreshingConfigs(true);
    try {
      const results = await Promise.all(
        CONFIG_GROUPS.map(async (group) => {
          const data = await apiFetch<ConfigEntry[]>(`/api/settings/configs/${group}`);
          return [group, data] as const;
        }),
      );
      setConfigs(Object.fromEntries(results));
    } catch (e) {
      alert(`Failed to refresh configs: ${e}`);
    } finally {
      setRefreshingConfigs(false);
    }
  };

  const loadCalibrations = async () => {
    setRefreshingCalibrations(true);
    try {
      const data = await apiFetch<Record<string, Record<string, string[]>>>(
        "/api/settings/calibration",
      );
      setCalibrations(data);
    } catch (e) {
      alert(`Failed to refresh calibrations: ${e}`);
    } finally {
      setRefreshingCalibrations(false);
    }
  };

  useEffect(() => {
    loadDevices();
    loadConfigs();
    loadCalibrations();
  }, []);

  const handleSaveConfig = async () => {
    if (!editingConfig) return;
    try {
      const content = JSON.parse(editJson);
      await apiFetch(`/api/settings/configs/${editingConfig.group}/${editingConfig.name}`, {
        method: "PUT",
        body: JSON.stringify({ content }),
      });
      setEditingConfig(null);
      loadConfigs();
    } catch (e) {
      alert(`Save failed: ${e}`);
    }
  };

  return (
    <div className="p-6 max-w-4xl">
      <h2 className="text-2xl font-bold mb-6">Settings</h2>

      {/* Devices */}
      <section className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold">Devices</h3>
          <Button variant="outline" size="sm" onClick={loadDevices} disabled={refreshingDevices}>
            {refreshingDevices ? "Refreshing..." : "Refresh"}
          </Button>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <h4 className="text-sm font-medium text-gray-500 mb-2">Serial Ports</h4>
            {serialPorts.length === 0 ? (
              <p className="text-sm text-gray-400">No serial ports found</p>
            ) : (
              <div className="space-y-1">
                {serialPorts.map((p) => (
                  <div key={p.port} className="flex items-center gap-2 text-sm">
                    <span className={`w-2 h-2 rounded-full ${p.available ? "bg-green-500" : "bg-red-500"}`} />
                    <span className="font-mono">{p.port}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div>
            <h4 className="text-sm font-medium text-gray-500 mb-2">Cameras</h4>
            {cameras.length === 0 ? (
              <p className="text-sm text-gray-400">No cameras found</p>
            ) : (
              <div className="space-y-1">
                {cameras.map((c) => (
                  <div key={c.path} className="flex items-center gap-2 text-sm">
                    <span className={`w-2 h-2 rounded-full ${c.available ? "bg-green-500" : "bg-red-500"}`} />
                    <span className="font-mono">{c.path}</span>
                    {c.available && (
                      <span className="text-gray-400">
                        {c.width}x{c.height}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Configs */}
      <section className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold">Configurations</h3>
          <Button variant="outline" size="sm" onClick={loadConfigs} disabled={refreshingConfigs}>
            {refreshingConfigs ? "Refreshing..." : "Refresh"}
          </Button>
        </div>
        {CONFIG_GROUPS.map((group) => (
          <div key={group} className="mb-4">
            <h4 className="text-sm font-medium text-gray-500 mb-2 capitalize">{group}</h4>
            <div className="space-y-1">
              {(configs[group] || []).map((cfg) => (
                <div
                  key={cfg.name}
                  className="flex items-center justify-between bg-gray-50 rounded px-3 py-2"
                >
                  <div>
                    <span className="font-medium text-sm">{cfg.name}</span>
                    <span className="text-xs text-gray-400 ml-2">
                      {(cfg.content as Record<string, unknown>)?._target_
                        ? String((cfg.content as Record<string, unknown>)._target_).split(".").pop()
                        : ""}
                    </span>
                  </div>
                  <div className="flex gap-2">
                    <button
                      className="text-xs text-blue-600 hover:text-blue-800"
                      onClick={() => {
                        setEditingConfig({ ...cfg, group });
                        setEditJson(JSON.stringify(cfg.content, null, 2));
                      }}
                    >
                      Edit
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </section>

      {/* Config editor modal */}
      {editingConfig && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-[600px] max-h-[80vh] overflow-auto">
            <h3 className="text-lg font-semibold mb-2">
              Edit {editingConfig.group}/{editingConfig.name}
            </h3>
            <textarea
              className="w-full h-64 font-mono text-sm border rounded p-3 mb-4"
              value={editJson}
              onChange={(e) => setEditJson(e.target.value)}
            />
            <div className="flex gap-3 justify-end">
              <Button variant="outline" onClick={() => setEditingConfig(null)}>
                Cancel
              </Button>
              <Button onClick={handleSaveConfig}>Save</Button>
            </div>
          </div>
        </div>
      )}

      {/* Calibration */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold">Calibration</h3>
          <Button variant="outline" size="sm" onClick={loadCalibrations} disabled={refreshingCalibrations}>
            {refreshingCalibrations ? "Refreshing..." : "Refresh"}
          </Button>
        </div>
        {Object.entries(calibrations).map(([category, robots]) => (
          <div key={category} className="mb-3">
            <h4 className="text-sm font-medium text-gray-500 mb-1 capitalize">{category}</h4>
            {Object.entries(robots).length === 0 ? (
              <p className="text-sm text-gray-400">No calibrations found</p>
            ) : (
              <div className="space-y-1">
                {Object.entries(robots).map(([robotType, ids]) => (
                  <div key={robotType} className="bg-gray-50 rounded px-3 py-2 text-sm">
                    <span className="font-medium">{robotType}</span>
                    <span className="text-gray-400 ml-2">
                      {ids.length > 0 ? ids.join(", ") : "no calibrations"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        <p className="text-xs text-gray-400 mt-2">
          Run calibration:{" "}
          <code className="bg-gray-100 px-1 rounded">
            python scripts/calibrate_so101.py --port /dev/ttyACM0 --id my_arm --type follower
          </code>
        </p>
      </section>
    </div>
  );
}
