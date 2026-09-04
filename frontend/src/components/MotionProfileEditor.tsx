import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Code2,
  Network,
  Plus,
  SlidersHorizontal,
  Trash2,
} from "lucide-react";
import { useConfigsWithContent } from "../api/queries";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Select } from "./ui/select";
import {
  createBimanualPreset,
  createSingleArmPreset,
  emptyMotionProfile,
  inferResources,
  normalizeMotionProfile,
  qualifiedResources,
  validateMotionProfile,
  type CatalogEntry,
  type MotionAdapterConfig,
  type MotionCatalogs,
  type MotionGroupConfig,
  type MotionInputConfig,
  type MotionProfileDocument,
  type MotionResourceConfig,
  type ResourceKind,
} from "./motion-profile-model";

interface Props {
  initialContent: Record<string, unknown>;
  onSave: (content: Record<string, unknown>) => Promise<void>;
  onCancel: () => void;
  canSave: boolean;
}

function uniqueId(prefix: string, existing: Record<string, unknown>): string {
  let index = 1;
  let candidate = prefix;
  while (candidate in existing) candidate = `${prefix}_${++index}`;
  return candidate;
}

function renameRecordKey<T>(source: Record<string, T>, previous: string, next: string): Record<string, T> {
  if (!next || next === previous || next in source) return source;
  return Object.fromEntries(
    Object.entries(source).map(([key, value]) => [key === previous ? next : key, value]),
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 min-w-0">
      <span className="text-micro-uppercase uppercase tracking-[0.14em] text-stone font-semibold">{label}</span>
      {children}
    </label>
  );
}

function SectionHeader({ title, count, onAdd }: { title: string; count: number; onAdd: () => void }) {
  return (
    <div className="flex items-center gap-sm">
      <h4 className="text-heading-5 text-ink">{title}</h4>
      <span className="font-mono text-micro text-stone">{count}</span>
      <span className="flex-1 h-px bg-hairline-soft" />
      <Button size="xs" variant="secondary" onClick={onAdd}>
        <Plus className="w-3.5 h-3.5 mr-1" /> Add
      </Button>
    </div>
  );
}

function GraphPreview({ document }: { document: MotionProfileDocument }) {
  const rows = Object.entries(document.motion_groups);
  return (
    <section className="rounded-md border border-hairline bg-surface-soft p-md">
      <header className="flex items-center gap-2 mb-sm">
        <Network className="w-4 h-4 text-brand-tag" />
        <span className="text-body-sm-medium text-ink">Connection preview</span>
        <span className="font-mono text-micro text-stone">SE3Delta routing</span>
      </header>
      <div className="grid grid-cols-[minmax(0,1fr)_24px_minmax(0,1fr)_24px_minmax(0,1.35fr)] gap-y-2 items-stretch">
        <div className="text-micro-uppercase uppercase tracking-[0.14em] text-stone">Input</div>
        <span />
        <div className="text-micro-uppercase uppercase tracking-[0.14em] text-stone">Motion Group</div>
        <span />
        <div className="text-micro-uppercase uppercase tracking-[0.14em] text-stone">Resources</div>
        {rows.length === 0 && (
          <div className="col-span-5 py-md text-center text-caption text-stone border border-dashed border-hairline rounded">
            Add a Motion Group to wire the graph.
          </div>
        )}
        {rows.map(([groupId, group]) => {
          const input = document.inputs[group.input];
          return (
            <div key={groupId} className="contents">
              <div className="rounded border border-hairline bg-canvas px-sm py-2 min-w-0">
                <div className="font-mono text-caption text-ink truncate">{group.input || "—"}</div>
                <div className="text-micro text-stone truncate">{input ? `${input.teleop} · ${input.channel}` : "missing input"}</div>
              </div>
              <div className="grid place-items-center text-stone"><ArrowRight className="w-4 h-4" /></div>
              <div className="rounded border-2 border-ink bg-canvas px-sm py-2 min-w-0">
                <div className="font-mono text-caption text-ink truncate">{groupId}</div>
                <div className="text-micro text-stone truncate">{group.mapper || "no mapper"}</div>
              </div>
              <div className="grid place-items-center text-stone"><ArrowRight className="w-4 h-4" /></div>
              <div className="rounded border border-hairline bg-canvas px-sm py-2 flex flex-wrap gap-1 items-center">
                {group.outputs.length
                  ? group.outputs.map((output) => (
                      <span key={output} className="font-mono text-micro rounded bg-brand-tag/10 text-brand-tag px-1.5 py-1">{output}</span>
                    ))
                  : <span className="text-micro text-brand-error">no output</span>}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export function MotionProfileEditor({ initialContent, onSave, onCancel, canSave }: Props) {
  const robotsQuery = useConfigsWithContent("robot");
  const teleopsQuery = useConfigsWithContent("teleop");
  const mappersQuery = useConfigsWithContent("mapper");
  const catalogs: MotionCatalogs = useMemo(() => ({
    robots: (robotsQuery.data ?? []) as CatalogEntry[],
    teleops: (teleopsQuery.data ?? []) as CatalogEntry[],
    mappers: (mappersQuery.data ?? []) as CatalogEntry[],
  }), [robotsQuery.data, teleopsQuery.data, mappersQuery.data]);
  const [document, setDocument] = useState<MotionProfileDocument>(() =>
    Object.keys(initialContent).length ? normalizeMotionProfile(initialContent) : emptyMotionProfile(),
  );
  const [view, setView] = useState<"visual" | "advanced">("visual");
  const [rawJson, setRawJson] = useState(() => JSON.stringify(document, null, 2));
  const [rawError, setRawError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const next = Object.keys(initialContent).length
      ? normalizeMotionProfile(initialContent)
      : emptyMotionProfile();
    setDocument(next);
    setRawJson(JSON.stringify(next, null, 2));
    setRawError(null);
  }, [initialContent]);

  const issues = useMemo(() => validateMotionProfile(document, catalogs), [document, catalogs]);
  const errors = issues.filter((issue) => issue.severity === "error");
  const warnings = issues.filter((issue) => issue.severity === "warning");
  const resources = qualifiedResources(document);

  const mutate = (fn: (draft: MotionProfileDocument) => void) => {
    setDocument((current) => {
      const draft = structuredClone(current);
      fn(draft);
      return draft;
    });
  };

  const selectPreset = (preset: "single" | "bimanual" | "empty") => {
    if ((Object.keys(document.adapters).length || Object.keys(document.motion_groups).length)
        && !window.confirm("Replace the current graph with this preset?")) return;
    const next = preset === "single"
      ? createSingleArmPreset(catalogs)
      : preset === "bimanual"
        ? createBimanualPreset(catalogs)
        : emptyMotionProfile();
    setDocument(next);
    setRawJson(JSON.stringify(next, null, 2));
  };

  const switchView = (next: "visual" | "advanced") => {
    if (next === "advanced") setRawJson(JSON.stringify(document, null, 2));
    if (next === "visual" && rawError) return;
    setView(next);
  };

  const updateRaw = (value: string) => {
    setRawJson(value);
    try {
      const parsed = JSON.parse(value);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("root must be an object");
      setDocument(normalizeMotionProfile(parsed));
      setRawError(null);
    } catch (error) {
      setRawError(String(error));
    }
  };

  const save = async () => {
    if (!canSave || errors.length || rawError) return;
    setSaving(true);
    try {
      await onSave(document as Record<string, unknown>);
    } finally {
      setSaving(false);
    }
  };

  const addAdapter = () => mutate((draft) => {
    const id = uniqueId("robot", draft.adapters);
    const robot = catalogs.robots[0]?.name ?? "";
    draft.adapters[id] = {
      robot,
      wrapper: robot.includes("rebot") ? "legacy" : "native",
      include_gripper: true,
      resources: inferResources(robot, catalogs),
    };
  });

  const renameAdapter = (previous: string, next: string) => mutate((draft) => {
    if (!next || next === previous || next in draft.adapters) return;
    draft.adapters = renameRecordKey(draft.adapters, previous, next);
    Object.values(draft.motion_groups).forEach((group) => {
      group.outputs = group.outputs.map((output) =>
        output.startsWith(`${previous}.`) ? `${next}.${output.slice(previous.length + 1)}` : output,
      );
    });
    if (draft.home?.adapters?.[previous]) {
      draft.home.adapters = renameRecordKey(draft.home.adapters, previous, next);
    }
  });

  const removeAdapter = (id: string) => mutate((draft) => {
    delete draft.adapters[id];
    Object.values(draft.motion_groups).forEach((group) => {
      group.outputs = group.outputs.filter((output) => !output.startsWith(`${id}.`));
    });
    if (draft.home?.adapters) delete draft.home.adapters[id];
  });

  const setAdapter = (id: string, patch: Partial<MotionAdapterConfig>) => mutate((draft) => {
    Object.assign(draft.adapters[id], patch);
  });

  const setResource = (adapterId: string, resourceId: string, patch: Partial<MotionResourceConfig>) => mutate((draft) => {
    Object.assign(draft.adapters[adapterId].resources[resourceId], patch);
  });

  const renameResource = (adapterId: string, previous: string, next: string) => mutate((draft) => {
    const adapter = draft.adapters[adapterId];
    if (!next || next === previous || next in adapter.resources) return;
    adapter.resources = renameRecordKey(adapter.resources, previous, next);
    Object.values(draft.motion_groups).forEach((group) => {
      group.outputs = group.outputs.map((output) =>
        output === `${adapterId}.${previous}` ? `${adapterId}.${next}` : output,
      );
    });
  });

  const setHomePath = (adapterId: string, posePath: string) => mutate((draft) => {
    draft.home ??= { duration_sec: 2, fps: 30, hold_sec: 0.3, adapters: {} };
    draft.home.adapters ??= {};
    if (!posePath) {
      delete draft.home.adapters[adapterId];
      return;
    }
    const channels = Object.values(draft.motion_groups)
      .filter((group) => group.outputs.some((output) => output.startsWith(`${adapterId}.`)))
      .map((group) => draft.inputs[group.input]?.channel)
      .filter((channel): channel is string => !!channel);
    draft.home.adapters[adapterId] = { pose_path: posePath, channels: [...new Set(channels)] };
  });

  const addInput = () => mutate((draft) => {
    const id = uniqueId("controller", draft.inputs);
    const channel = uniqueId("channel", Object.fromEntries(Object.values(draft.inputs).map((input) => [input.channel, true])));
    draft.inputs[id] = {
      teleop: catalogs.teleops[0]?.name ?? "",
      channel,
      frame: "ee_local",
      control_rate_hz: 60,
    };
    if (!draft.default_channel) draft.default_channel = channel;
  });

  const renameInput = (previous: string, next: string) => mutate((draft) => {
    if (!next || next === previous || next in draft.inputs) return;
    draft.inputs = renameRecordKey(draft.inputs, previous, next);
    Object.values(draft.motion_groups).forEach((group) => {
      if (group.input === previous) group.input = next;
    });
  });

  const removeInput = (id: string) => mutate((draft) => {
    const removedChannel = draft.inputs[id]?.channel;
    delete draft.inputs[id];
    Object.values(draft.motion_groups).forEach((group) => {
      if (group.input === id) group.input = "";
    });
    if (draft.default_channel === removedChannel) draft.default_channel = Object.values(draft.inputs)[0]?.channel ?? "";
  });

  const setInput = (id: string, patch: Partial<MotionInputConfig>) => mutate((draft) => {
    const previousChannel = draft.inputs[id].channel;
    Object.assign(draft.inputs[id], patch);
    if (patch.channel && draft.default_channel === previousChannel) draft.default_channel = patch.channel;
  });

  const addGroup = () => mutate((draft) => {
    const id = uniqueId("motion_group", draft.motion_groups);
    const mapper = catalogs.mappers[0]?.name ?? "";
    draft.motion_groups[id] = {
      input: Object.keys(draft.inputs)[0] ?? "",
      mapper,
      mapper_wrapper: mapper.includes("rebot") ? "legacy" : "native",
      outputs: [],
      auxiliary: ["gripper"],
      control_rate_hz: 60,
    };
  });

  const renameGroup = (previous: string, next: string) => mutate((draft) => {
    draft.motion_groups = renameRecordKey(draft.motion_groups, previous, next);
  });

  const setGroup = (id: string, patch: Partial<MotionGroupConfig>) => mutate((draft) => {
    Object.assign(draft.motion_groups[id], patch);
  });

  return (
    <div className="flex flex-col gap-md">
      <div className="flex flex-wrap items-center gap-xs">
        <div className="inline-flex rounded-full border border-hairline p-0.5 bg-surface-soft">
          <button type="button" onClick={() => switchView("visual")} className={`rounded-full px-3 py-1.5 text-caption ${view === "visual" ? "bg-ink text-on-dark" : "text-steel"}`}>
            <SlidersHorizontal className="inline w-3.5 h-3.5 mr-1" />Visual
          </button>
          <button type="button" onClick={() => switchView("advanced")} className={`rounded-full px-3 py-1.5 text-caption ${view === "advanced" ? "bg-ink text-on-dark" : "text-steel"}`}>
            <Code2 className="inline w-3.5 h-3.5 mr-1" />Advanced JSON
          </button>
        </div>
        <span className="flex-1" />
        <span className="text-micro text-stone mr-1">START FROM</span>
        <Button size="xs" variant="secondary" onClick={() => selectPreset("single")}>Single arm</Button>
        <Button size="xs" variant="secondary" onClick={() => selectPreset("bimanual")}>Bimanual</Button>
        <Button size="xs" variant="ghost" onClick={() => selectPreset("empty")}>Empty</Button>
      </div>

      {view === "advanced" ? (
        <div>
          <textarea
            className="w-full h-[56vh] rounded-md border border-hairline bg-canvas p-md font-mono text-code-sm text-charcoal focus:outline-none focus:border-2 focus:border-ink"
            value={rawJson}
            onChange={(event) => updateRaw(event.target.value)}
          />
          {rawError && <div className="mt-xs text-caption text-brand-error">{rawError}</div>}
        </div>
      ) : (
        <div className="flex flex-col gap-lg max-h-[62vh] overflow-y-auto pr-1">
          <div className="grid grid-cols-3 gap-sm">
            <Field label="State rate">
              <Input type="number" min={1} value={document.state_rate_hz} onChange={(event) => mutate((draft) => { draft.state_rate_hz = Number(event.target.value); })} />
            </Field>
            <Field label="Default channel">
              <Select value={document.default_channel} onChange={(event) => mutate((draft) => { draft.default_channel = event.target.value; })}>
                <option value="">Select…</option>
                {[...new Set(Object.values(document.inputs).map((input) => input.channel))].map((channel) => <option key={channel} value={channel}>{channel}</option>)}
              </Select>
            </Field>
            <Field label="Home duration">
              <Input type="number" min={0.1} step={0.1} value={document.home?.duration_sec ?? 2} onChange={(event) => mutate((draft) => { draft.home ??= { adapters: {} }; draft.home.duration_sec = Number(event.target.value); })} />
            </Field>
          </div>

          <GraphPreview document={document} />

          <section className="flex flex-col gap-sm">
            <SectionHeader title="Hardware adapters" count={Object.keys(document.adapters).length} onAdd={addAdapter} />
            {Object.entries(document.adapters).map(([id, adapter]) => (
              <div key={id} className="rounded-md border border-hairline bg-canvas p-md flex flex-col gap-sm">
                <div className="grid grid-cols-[1fr_1.4fr_0.8fr_auto] gap-sm items-end">
                  <Field label="Adapter ID"><Input value={id} onChange={(event) => renameAdapter(id, event.target.value)} /></Field>
                  <Field label="Robot config">
                    <Select value={adapter.robot} onChange={(event) => {
                      const robot = event.target.value;
                      setAdapter(id, { robot, wrapper: robot.includes("rebot") ? "legacy" : "native", resources: inferResources(robot, catalogs) });
                    }}>
                      <option value="">Select…</option>
                      {catalogs.robots.map((entry) => <option key={entry.name} value={entry.name}>{entry.name}</option>)}
                    </Select>
                  </Field>
                  <Field label="Adapter API">
                    <Select value={adapter.wrapper} onChange={(event) => setAdapter(id, { wrapper: event.target.value as MotionAdapterConfig["wrapper"] })}>
                      <option value="native">native resources</option>
                      <option value="legacy">legacy wrapper</option>
                    </Select>
                  </Field>
                  <Button size="sm" variant="ghost" aria-label={`Remove ${id}`} onClick={() => removeAdapter(id)}><Trash2 className="w-4 h-4 text-brand-error" /></Button>
                </div>
                <div className="rounded bg-surface-soft p-sm flex flex-col gap-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-micro-uppercase uppercase tracking-[0.14em] text-stone">Exposed resources</span>
                    <button type="button" className="text-caption text-steel hover:text-ink" onClick={() => mutate((draft) => {
                      const resources = draft.adapters[id].resources;
                      const name = uniqueId("resource", resources);
                      resources[name] = { kind: "joint", unit: "rad", joint_names: [] };
                    })}>+ resource</button>
                  </div>
                  {Object.entries(adapter.resources).map(([resourceId, resource]) => (
                    <div key={resourceId} className="grid grid-cols-[0.8fr_0.65fr_1.8fr_auto] gap-xs items-center">
                      <Input className="h-8 font-mono text-caption" value={resourceId} onChange={(event) => renameResource(id, resourceId, event.target.value)} />
                      <Select className="h-8 text-caption" value={resource.kind} onChange={(event) => setResource(id, resourceId, { kind: event.target.value as ResourceKind, joint_names: event.target.value === "joint" ? resource.joint_names ?? [] : undefined })}>
                        <option value="joint">joint</option><option value="scalar">scalar</option><option value="planar">planar</option>
                      </Select>
                      {resource.kind === "joint" ? (
                        <Input className="h-8 font-mono text-caption" value={(resource.joint_names ?? []).join(", ")} placeholder="joint1, joint2, …" onChange={(event) => setResource(id, resourceId, { joint_names: event.target.value.split(",").map((value) => value.trim()).filter(Boolean), unit: "rad" })} />
                      ) : <span className="text-caption text-stone">{resource.kind === "planar" ? "x · y · yaw" : "single mechanism value"}</span>}
                      <button type="button" className="p-1 text-stone hover:text-brand-error" onClick={() => mutate((draft) => {
                        delete draft.adapters[id].resources[resourceId];
                        Object.values(draft.motion_groups).forEach((group) => { group.outputs = group.outputs.filter((output) => output !== `${id}.${resourceId}`); });
                      })}><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  ))}
                </div>
                <Field label="Calibrated Home pose (optional)">
                  <Input value={document.home?.adapters?.[id]?.pose_path ?? ""} placeholder="configs/robot_name/idle_pose.yaml" onChange={(event) => setHomePath(id, event.target.value)} />
                </Field>
              </div>
            ))}
          </section>

          <section className="flex flex-col gap-sm">
            <SectionHeader title="Motion inputs" count={Object.keys(document.inputs).length} onAdd={addInput} />
            {Object.entries(document.inputs).map(([id, input]) => (
              <div key={id} className="rounded-md border border-hairline bg-canvas p-md grid grid-cols-[1fr_1.3fr_0.8fr_0.8fr_0.65fr_auto] gap-sm items-end">
                <Field label="Input ID"><Input value={id} onChange={(event) => renameInput(id, event.target.value)} /></Field>
                <Field label="Teleop"><Select value={input.teleop} onChange={(event) => setInput(id, { teleop: event.target.value })}><option value="">Select…</option>{catalogs.teleops.map((entry) => <option key={entry.name} value={entry.name}>{entry.name}</option>)}</Select></Field>
                <Field label="Channel"><Input value={input.channel} onChange={(event) => setInput(id, { channel: event.target.value })} /></Field>
                <Field label="Frame"><Select value={input.frame} onChange={(event) => setInput(id, { frame: event.target.value as MotionInputConfig["frame"] })}><option value="ee_local">ee_local</option><option value="base">base</option><option value="world">world</option></Select></Field>
                <Field label="Hz"><Input type="number" min={1} value={input.control_rate_hz} onChange={(event) => setInput(id, { control_rate_hz: Number(event.target.value) })} /></Field>
                <Button size="sm" variant="ghost" onClick={() => removeInput(id)}><Trash2 className="w-4 h-4 text-brand-error" /></Button>
              </div>
            ))}
          </section>

          <section className="flex flex-col gap-sm">
            <SectionHeader title="Motion Groups" count={Object.keys(document.motion_groups).length} onAdd={addGroup} />
            {Object.entries(document.motion_groups).map(([id, group]) => (
              <div key={id} className="rounded-md border-2 border-hairline bg-canvas p-md flex flex-col gap-sm">
                <div className="grid grid-cols-[1fr_1fr_1.3fr_0.75fr_0.55fr_auto] gap-sm items-end">
                  <Field label="Group ID"><Input value={id} onChange={(event) => renameGroup(id, event.target.value)} /></Field>
                  <Field label="Input"><Select value={group.input} onChange={(event) => setGroup(id, { input: event.target.value })}><option value="">Select…</option>{Object.keys(document.inputs).map((inputId) => <option key={inputId} value={inputId}>{inputId}</option>)}</Select></Field>
                  <Field label="Mapper"><Select value={group.mapper} onChange={(event) => { const mapper = event.target.value; setGroup(id, { mapper, mapper_wrapper: mapper.includes("rebot") ? "legacy" : "native" }); }}><option value="">Select…</option>{catalogs.mappers.map((entry) => <option key={entry.name} value={entry.name}>{entry.name}</option>)}</Select></Field>
                  <Field label="Mapper API"><Select value={group.mapper_wrapper} onChange={(event) => setGroup(id, { mapper_wrapper: event.target.value as MotionGroupConfig["mapper_wrapper"] })}><option value="native">native</option><option value="legacy">legacy</option></Select></Field>
                  <Field label="Hz"><Input type="number" min={1} value={group.control_rate_hz} onChange={(event) => setGroup(id, { control_rate_hz: Number(event.target.value) })} /></Field>
                  <Button size="sm" variant="ghost" onClick={() => mutate((draft) => { delete draft.motion_groups[id]; })}><Trash2 className="w-4 h-4 text-brand-error" /></Button>
                </div>
                <div>
                  <div className="text-micro-uppercase uppercase tracking-[0.14em] text-stone mb-1">Claimed output resources</div>
                  <div className="flex flex-wrap gap-xs">
                    {resources.map((resource) => {
                      const selected = group.outputs.includes(resource.name);
                      return (
                        <label key={resource.name} className={`inline-flex items-center gap-1.5 rounded border px-2 py-1 cursor-pointer font-mono text-caption ${selected ? "border-ink bg-surface text-ink" : "border-hairline text-stone"}`}>
                          <input type="checkbox" checked={selected} onChange={(event) => setGroup(id, { outputs: event.target.checked ? [...group.outputs, resource.name] : group.outputs.filter((output) => output !== resource.name) })} />
                          {resource.name}<span className="text-micro opacity-60">{resource.kind}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              </div>
            ))}
          </section>
        </div>
      )}

      <div className="rounded-md border border-hairline bg-surface-soft p-sm max-h-28 overflow-y-auto">
        {errors.length === 0 && warnings.length === 0 ? (
          <div className="flex items-center gap-2 text-caption text-brand-green-deep"><CheckCircle2 className="w-4 h-4" />Graph is valid.</div>
        ) : (
          <div className="flex flex-col gap-1">
            {issues.map((issue, index) => (
              <div key={`${issue.path}-${index}`} className={`flex items-start gap-2 text-caption ${issue.severity === "error" ? "text-brand-error" : "text-brand-warn"}`}>
                <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                <span><span className="font-mono">{issue.path}</span> — {issue.message}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex justify-between items-center gap-sm border-t border-hairline pt-md">
        <span className="text-caption text-stone">
          {errors.length ? `${errors.length} error${errors.length === 1 ? "" : "s"} must be fixed` : `${warnings.length} warning${warnings.length === 1 ? "" : "s"}`}
        </span>
        <div className="flex gap-xs">
          <Button variant="secondary" onClick={onCancel}>Cancel</Button>
          <Button disabled={!canSave || !!errors.length || !!rawError || saving} onClick={save}>{saving ? "Saving…" : "Save profile"}</Button>
        </div>
      </div>
    </div>
  );
}
