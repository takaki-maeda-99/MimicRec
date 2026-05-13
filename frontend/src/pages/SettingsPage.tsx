import { useEffect, useState } from "react";
import { apiFetch } from "../api/client";
import { Button } from "../components/ui/button";
import { CameraConfigForm } from "../components/CameraConfigForm";
import { ConfigCard, type ConfigGroup } from "../components/ConfigCard";
import { PageHeader } from "../components/ui/page-header";
import { SectionMark } from "../components/ui/section-mark";

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

const CONFIG_GROUPS: ConfigGroup[] = ["robot", "teleop", "mapper", "cameras"];

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
    <>
      <PageHeader code="§04" title="Settings" />
      <div className="flex-1 overflow-auto">
        <div className="max-w-[1100px] mx-auto px-xl py-xl flex flex-col gap-xl">

          {/* §04.A · Devices */}
          <section className="flex flex-col gap-md">
            <header className="flex items-baseline gap-md">
              <SectionMark code="§04.A" name="Devices" />
              <span className="flex-1 h-px bg-hairline-soft" />
              <Button variant="secondary" size="sm" onClick={loadDevices} disabled={refreshingDevices}>
                {refreshingDevices ? "Refreshing..." : "Refresh"}
              </Button>
            </header>
            <div className="rounded-md border border-hairline bg-canvas p-md grid grid-cols-1 sm:grid-cols-2 gap-xl">
              <div>
                <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold mb-xs">
                  Serial ports
                </div>
                {serialPorts.length === 0 ? (
                  <p className="text-body-sm text-stone">No serial ports found</p>
                ) : (
                  <div className="flex flex-col gap-1">
                    {serialPorts.map((p) => (
                      <div key={p.port} className="flex items-center gap-xs text-body-sm">
                        <span
                          className={`w-2 h-2 rounded-full ${p.available ? "bg-brand-green" : "bg-brand-error"}`}
                          aria-hidden
                        />
                        <span className="font-mono text-code-sm text-charcoal">{p.port}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div>
                <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold mb-xs">
                  Cameras
                </div>
                {cameras.length === 0 ? (
                  <p className="text-body-sm text-stone">No cameras found</p>
                ) : (
                  <div className="flex flex-col gap-1">
                    {cameras.map((c) => (
                      <div key={c.path} className="flex items-center gap-xs text-body-sm">
                        <span
                          className={`w-2 h-2 rounded-full ${c.available ? "bg-brand-green" : "bg-brand-error"}`}
                          aria-hidden
                        />
                        <span className="font-mono text-code-sm text-charcoal">{c.path}</span>
                        {c.available && (
                          <span className="font-mono text-caption text-stone">
                            {c.width}×{c.height}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </section>

          {/* §04.B · Configurations */}
          <section className="flex flex-col gap-md">
            <header className="flex items-baseline gap-md">
              <SectionMark code="§04.B" name="Configurations" />
              <span className="flex-1 h-px bg-hairline-soft" />
              <Button variant="secondary" size="sm" onClick={loadConfigs} disabled={refreshingConfigs}>
                {refreshingConfigs ? "Refreshing..." : "Refresh"}
              </Button>
            </header>
            {CONFIG_GROUPS.map((group, i) => (
              <div key={group} className="flex flex-col gap-xs">
                <SectionMark
                  code={`§04.B.${i + 1}`}
                  name={group}
                  className="capitalize"
                />
                <div className="flex flex-col gap-2">
                  {(configs[group] || []).map((cfg) => (
                    <ConfigCard
                      key={cfg.name}
                      config={cfg}
                      group={group}
                      rightSlot={
                        <Button
                          variant="secondary"
                          size="sm"
                          className="!bg-surface hover:!bg-hairline"
                          onClick={() => {
                            setEditingConfig({ ...cfg, group });
                            setEditJson(JSON.stringify(cfg.content, null, 2));
                          }}
                        >
                          ⚙ Edit
                        </Button>
                      }
                    />
                  ))}
                </div>
              </div>
            ))}
          </section>

          {/* §04.C · Calibration */}
          <section className="flex flex-col gap-md">
            <header className="flex items-baseline gap-md">
              <SectionMark code="§04.C" name="Calibration" />
              <span className="flex-1 h-px bg-hairline-soft" />
              <Button variant="secondary" size="sm" onClick={loadCalibrations} disabled={refreshingCalibrations}>
                {refreshingCalibrations ? "Refreshing..." : "Refresh"}
              </Button>
            </header>
            {Object.entries(calibrations).map(([category, robots]) => (
              <div key={category} className="mb-sm">
                <div className="text-micro-uppercase uppercase tracking-[0.18em] text-stone font-semibold mb-xs">
                  {category}
                </div>
                {Object.entries(robots).length === 0 ? (
                  <p className="text-body-sm text-stone">No calibrations found</p>
                ) : (
                  <div className="flex flex-col gap-1">
                    {Object.entries(robots).map(([robotType, ids]) => (
                      <div
                        key={robotType}
                        className="flex items-baseline justify-between gap-md py-1 border-b border-dashed border-hairline-soft last:border-b-0"
                      >
                        <span className="text-body-sm-medium text-ink">{robotType}</span>
                        <span className="font-mono text-caption text-steel text-right min-w-0 break-words">
                          {ids.length > 0 ? ids.join(", ") : "—"}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
            <p className="mt-xs text-caption text-stone">
              Run calibration:{" "}
              <code className="rounded-xs border border-hairline bg-surface px-1.5 py-0.5 font-mono text-code-inline text-charcoal">
                python scripts/calibrate_so101.py --port /dev/ttyACM0 --id my_arm --type follower
              </code>
            </p>
          </section>

        </div>
      </div>

      {/* Config editor modal — rendered outside overflow-auto to cover full viewport */}
      {editingConfig && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-canvas-dark/40"
          onClick={() => setEditingConfig(null)}
        >
          <div
            className="bg-canvas rounded-lg border border-hairline p-xl w-[600px] max-h-[80vh] overflow-auto"
            onClick={(e) => e.stopPropagation()}
          >
            {editingConfig.group === "cameras"
              && (editingConfig.content as Record<string, unknown>)._target_
                  === "mimicrec.cameras.opencv_camera.OpenCVCamera" ? (
              <CameraConfigForm
                name={editingConfig.name}
                currentContent={editingConfig.content as Record<string, unknown>}
                onSave={(validationSkipped) => {
                  setEditingConfig(null);
                  if (validationSkipped) {
                    alert(
                      "Saved. Camera was busy so the configured parameters " +
                        "will be validated when the next session starts.",
                    );
                  }
                  loadConfigs();
                }}
                onCancel={() => setEditingConfig(null)}
              />
            ) : (
              <>
                <h3 className="text-heading-5 text-ink mb-xs">
                  Edit {editingConfig.group}/{editingConfig.name}
                </h3>
                <textarea
                  className="w-full h-64 rounded-md border border-hairline bg-canvas p-md font-mono text-code-sm text-charcoal mb-md focus:outline-none focus:border-2 focus:border-ink"
                  value={editJson}
                  onChange={(e) => setEditJson(e.target.value)}
                />
                <div className="flex justify-end gap-xs">
                  <Button variant="secondary" onClick={() => setEditingConfig(null)}>Cancel</Button>
                  <Button onClick={handleSaveConfig}>Save</Button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
