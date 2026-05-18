import { useEffect, useState } from "react";
import { apiFetch } from "../api/client";
import { ConfigEditorModal, type ConfigEntry, type ConfigEditorMode } from "../components/ConfigEditorModal";
import type { ConfigGroup, ConfigCardEntry } from "../components/ConfigCard";
import { ConfigurationsTabs } from "../components/ConfigurationsTabs";
import { HardwareStatusBlock } from "../components/HardwareStatusBlock";
import { PageHeader } from "../components/ui/page-header";

interface SerialDevice { port: string; available: boolean }
interface CameraDevice {
  path: string; device_id: number; available: boolean; width: number; height: number;
}

const CONFIG_GROUPS: ConfigGroup[] = ["robot", "teleop", "mapper", "cameras"];

export default function SettingsPage() {
  const [serialPorts, setSerialPorts] = useState<SerialDevice[]>([]);
  const [cameras, setCameras] = useState<CameraDevice[]>([]);
  const [configs, setConfigs] = useState<Record<ConfigGroup, ConfigCardEntry[]>>({
    robot: [], teleop: [], mapper: [], cameras: [],
  });
  const [calibrations, setCalibrations] = useState<Record<string, Record<string, string[]>>>({});
  const [editing, setEditing] = useState<{ config: ConfigEntry; mode: ConfigEditorMode } | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const loadAll = async () => {
    setRefreshing(true);
    try {
      const [serial, cams, cal, ...groups] = await Promise.all([
        apiFetch<SerialDevice[]>("/api/settings/devices/serial").catch(() => [] as SerialDevice[]),
        apiFetch<CameraDevice[]>("/api/settings/devices/cameras").catch(() => [] as CameraDevice[]),
        apiFetch<Record<string, Record<string, string[]>>>("/api/settings/calibration").catch(() => ({} as Record<string, Record<string, string[]>>)),
        ...CONFIG_GROUPS.map(g =>
          apiFetch<ConfigCardEntry[]>(`/api/settings/configs/${g}`).catch(() => [] as ConfigCardEntry[])
        ),
      ]);
      setSerialPorts(serial);
      setCameras(cams);
      setCalibrations(cal);
      const nextConfigs = { robot: [], teleop: [], mapper: [], cameras: [] } as Record<ConfigGroup, ConfigCardEntry[]>;
      CONFIG_GROUPS.forEach((g, i) => { nextConfigs[g] = groups[i]; });
      setConfigs(nextConfigs);
    } catch (e) {
      alert(`Failed to refresh: ${e}`);
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => { loadAll(); }, []);

  const handleDelete = async (group: ConfigGroup, name: string) => {
    if (!window.confirm(`Delete ${group}/${name}?`)) return;
    // NOTE: cannot use apiFetch — it calls res.json() unconditionally
    // (client.ts:38), which fails on the 204 No Content response from a
    // successful DELETE. Use raw fetch with explicit status branches.
    const res = await fetch(`/api/settings/configs/${group}/${name}`, {
      method: "DELETE",
      cache: "no-store",
    });
    if (res.status === 204) {
      loadAll();
      return;
    }
    if (res.status === 409) {
      const body = await res.json().catch(() => ({ detail: "in use" }));
      alert(`Cannot delete ${group}/${name}: ${body.detail}`);
      return;
    }
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    alert(`Delete failed: ${body.detail}`);
  };

  const openEditor = (group: ConfigGroup, name: string, mode: ConfigEditorMode) => {
    const cfg = configs[group]?.find(c => c.name === name);
    setEditing({
      config: { name, group, content: cfg?.content ?? {} },
      mode,
    });
  };

  return (
    <>
      <PageHeader
        code="§04"
        title="Settings"
      />
      <div className="flex-1 overflow-auto">
        <div className="max-w-[1200px] mx-auto px-xl py-xl flex flex-col gap-xl">
          <HardwareStatusBlock
            serial={serialPorts}
            cameras={cameras}
            calibrations={calibrations}
            refreshing={refreshing}
            onRefresh={loadAll}
          />
          <ConfigurationsTabs
            configs={configs}
            refreshing={refreshing}
            onRefresh={loadAll}
            onEdit={(g, n) => openEditor(g, n, "edit")}
            onClone={(g, n) => openEditor(g, n, "clone")}
            onNew={(g) => setEditing({ config: { name: "", group: g, content: {} }, mode: "new" })}
            onDelete={handleDelete}
          />
        </div>
      </div>
      <ConfigEditorModal
        config={editing?.config ?? null}
        mode={editing?.mode ?? "edit"}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          loadAll();
        }}
      />
    </>
  );
}
