export type ResourceKind = "joint" | "scalar" | "planar";

export interface MotionResourceConfig {
  kind: ResourceKind;
  joint_names?: string[];
  unit?: string;
}

export interface MotionAdapterConfig {
  robot: string;
  wrapper: "legacy" | "native";
  include_gripper?: boolean;
  safe_mode?: string;
  resources: Record<string, MotionResourceConfig>;
}

export interface MotionInputConfig {
  teleop: string;
  channel: string;
  frame: "ee_local" | "base" | "world";
  control_rate_hz: number;
}

export interface MotionGroupConfig {
  input: string;
  mapper: string;
  mapper_wrapper: "legacy" | "native";
  outputs: string[];
  auxiliary: string[];
  control_rate_hz: number;
  mapper_args?: Record<string, unknown>;
}

export interface MotionHomeTarget {
  pose_path?: string;
  joint_pos?: number[];
  joint_names?: string[];
  gripper_pos?: number;
  channels?: string[];
}

export interface MotionProfileDocument {
  version: number;
  default_channel: string;
  state_rate_hz: number;
  adapters: Record<string, MotionAdapterConfig>;
  inputs: Record<string, MotionInputConfig>;
  motion_groups: Record<string, MotionGroupConfig>;
  home?: {
    duration_sec?: number;
    fps?: number;
    hold_sec?: number;
    adapters?: Record<string, MotionHomeTarget>;
  };
  [key: string]: unknown;
}

export interface CatalogEntry {
  name: string;
  content: Record<string, unknown>;
}

export interface MotionCatalogs {
  robots: CatalogEntry[];
  teleops: CatalogEntry[];
  mappers: CatalogEntry[];
}

export interface ProfileIssue {
  severity: "error" | "warning";
  path: string;
  message: string;
}

const REBOT_JOINTS = ["joint1", "joint2", "joint3", "joint4", "joint5", "joint6"];
const SO101_JOINTS = [
  "shoulder_pan",
  "shoulder_lift",
  "elbow_flex",
  "wrist_flex",
  "wrist_roll",
];

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function finiteNumber(value: unknown, fallback: number): number {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

export function emptyMotionProfile(): MotionProfileDocument {
  return {
    version: 1,
    default_channel: "",
    state_rate_hz: 60,
    adapters: {},
    inputs: {},
    motion_groups: {},
  };
}

export function normalizeMotionProfile(content: Record<string, unknown>): MotionProfileDocument {
  const source = structuredClone(content);
  const adapters: Record<string, MotionAdapterConfig> = {};
  Object.entries(record(source.adapters)).forEach(([id, rawValue]) => {
    const raw = record(rawValue);
    const resources: Record<string, MotionResourceConfig> = {};
    Object.entries(record(raw.resources)).forEach(([name, resourceValue]) => {
      const resource = record(resourceValue);
      const kind = ["joint", "scalar", "planar"].includes(String(resource.kind))
        ? String(resource.kind) as ResourceKind
        : "joint";
      resources[name] = {
        ...resource,
        kind,
        joint_names: kind === "joint" ? stringArray(resource.joint_names) : undefined,
      } as MotionResourceConfig;
    });
    adapters[id] = {
      ...raw,
      robot: String(raw.robot ?? ""),
      wrapper: raw.wrapper === "legacy" ? "legacy" : "native",
      resources,
    } as MotionAdapterConfig;
  });

  const inputs: Record<string, MotionInputConfig> = {};
  Object.entries(record(source.inputs)).forEach(([id, rawValue]) => {
    const raw = record(rawValue);
    const frame = ["ee_local", "base", "world"].includes(String(raw.frame))
      ? String(raw.frame) as MotionInputConfig["frame"]
      : "ee_local";
    inputs[id] = {
      ...raw,
      teleop: String(raw.teleop ?? ""),
      channel: String(raw.channel ?? id),
      frame,
      control_rate_hz: finiteNumber(raw.control_rate_hz, 60),
    } as MotionInputConfig;
  });

  const motionGroups: Record<string, MotionGroupConfig> = {};
  Object.entries(record(source.motion_groups)).forEach(([id, rawValue]) => {
    const raw = record(rawValue);
    motionGroups[id] = {
      ...raw,
      input: String(raw.input ?? ""),
      mapper: String(raw.mapper ?? ""),
      mapper_wrapper: raw.mapper_wrapper === "legacy" ? "legacy" : "native",
      outputs: stringArray(raw.outputs),
      auxiliary: Array.isArray(raw.auxiliary) ? stringArray(raw.auxiliary) : ["gripper"],
      control_rate_hz: finiteNumber(raw.control_rate_hz, 60),
      mapper_args: Object.keys(record(raw.mapper_args)).length
        ? record(raw.mapper_args)
        : undefined,
    } as MotionGroupConfig;
  });

  const normalized: MotionProfileDocument = {
    ...source,
    version: finiteNumber(source.version, 1),
    default_channel: String(source.default_channel ?? ""),
    state_rate_hz: finiteNumber(source.state_rate_hz, 60),
    adapters,
    inputs,
    motion_groups: motionGroups,
  };
  const homeRaw = record(source.home);
  if (Object.keys(homeRaw).length) {
    normalized.home = {
      ...homeRaw,
      duration_sec: finiteNumber(homeRaw.duration_sec, 2),
      fps: finiteNumber(homeRaw.fps, 30),
      hold_sec: finiteNumber(homeRaw.hold_sec, 0.3),
      adapters: record(homeRaw.adapters) as Record<string, MotionHomeTarget>,
    };
  }
  return normalized;
}

export function inferResources(robotName: string, catalogs: MotionCatalogs): Record<string, MotionResourceConfig> {
  const robot = catalogs.robots.find((entry) => entry.name === robotName)?.content ?? {};
  const target = String(robot._target_ ?? "").toLowerCase();
  const kinematics = record(robot.kinematics);
  const configuredNames = stringArray(kinematics.joint_names);
  const jointNames = configuredNames.length
    ? configuredNames
    : target.includes("so101") || robotName.includes("so101")
      ? SO101_JOINTS
      : target.includes("rebot") || robotName.includes("rebot")
        ? REBOT_JOINTS
        : [];
  const resources: Record<string, MotionResourceConfig> = {};
  if (jointNames.length) resources.arm = { kind: "joint", unit: "rad", joint_names: jointNames };
  resources.gripper = { kind: "scalar" };
  return resources;
}

function firstName(entries: CatalogEntry[], preferred: string, fallback = ""): string {
  return entries.find((entry) => entry.name === preferred)?.name
    ?? entries[0]?.name
    ?? fallback;
}

export function createSingleArmPreset(catalogs: MotionCatalogs): MotionProfileDocument {
  const robot = firstName(catalogs.robots, "rebotarm");
  const teleop = firstName(catalogs.teleops, "quest_ros");
  const mapper = firstName(catalogs.mappers, "delta_ee_to_rebotarm");
  return {
    version: 1,
    default_channel: "right",
    state_rate_hz: 60,
    adapters: {
      robot: {
        robot,
        wrapper: robot.includes("rebot") ? "legacy" : "native",
        include_gripper: true,
        safe_mode: "gravity_comp",
        resources: inferResources(robot, catalogs),
      },
    },
    inputs: {
      controller: { teleop, channel: "right", frame: "ee_local", control_rate_hz: 60 },
    },
    motion_groups: {
      hand: {
        input: "controller",
        mapper,
        mapper_wrapper: mapper.includes("rebot") ? "legacy" : "native",
        outputs: ["robot.arm", "robot.gripper"],
        auxiliary: ["gripper"],
        control_rate_hz: 60,
      },
    },
  };
}

export function createBimanualPreset(catalogs: MotionCatalogs): MotionProfileDocument {
  const rebot = firstName(catalogs.robots, "rebotarm");
  const so101 = firstName(catalogs.robots, "so101_daemon", rebot);
  const quest = firstName(catalogs.teleops, "quest_ros");
  const rebotMapper = firstName(catalogs.mappers, "delta_ee_to_rebotarm");
  const soMapper = firstName(catalogs.mappers, "se3_delta_to_so101", rebotMapper);
  return {
    version: 1,
    default_channel: "right",
    state_rate_hz: 60,
    adapters: {
      right_robot: {
        robot: rebot,
        wrapper: "legacy",
        include_gripper: true,
        safe_mode: "gravity_comp",
        resources: inferResources(rebot, catalogs),
      },
      left_robot: {
        robot: so101,
        wrapper: "native",
        resources: inferResources(so101, catalogs),
      },
    },
    inputs: {
      right_controller: { teleop: quest, channel: "right", frame: "ee_local", control_rate_hz: 60 },
      left_controller: { teleop: quest, channel: "left", frame: "ee_local", control_rate_hz: 60 },
    },
    motion_groups: {
      right_hand: {
        input: "right_controller",
        mapper: rebotMapper,
        mapper_wrapper: "legacy",
        outputs: ["right_robot.arm", "right_robot.gripper"],
        auxiliary: ["gripper"],
        control_rate_hz: 60,
      },
      left_hand: {
        input: "left_controller",
        mapper: soMapper,
        mapper_wrapper: "native",
        outputs: ["left_robot.arm", "left_robot.gripper"],
        auxiliary: ["gripper"],
        control_rate_hz: 60,
      },
    },
  };
}

export function qualifiedResources(document: MotionProfileDocument): Array<{
  name: string;
  kind: ResourceKind;
}> {
  return Object.entries(document.adapters).flatMap(([adapterId, adapter]) =>
    Object.entries(adapter.resources).map(([resourceName, resource]) => ({
      name: `${adapterId}.${resourceName}`,
      kind: resource.kind,
    })),
  );
}

export function validateMotionProfile(
  document: MotionProfileDocument,
  catalogs: MotionCatalogs,
): ProfileIssue[] {
  const issues: ProfileIssue[] = [];
  const error = (path: string, message: string) => issues.push({ severity: "error", path, message });
  const warning = (path: string, message: string) => issues.push({ severity: "warning", path, message });
  const idPattern = /^[A-Za-z][A-Za-z0-9_-]*$/;

  const adapters = Object.entries(document.adapters);
  const inputs = Object.entries(document.inputs);
  const groups = Object.entries(document.motion_groups);
  if (!adapters.length) error("adapters", "Add at least one hardware adapter.");
  if (!inputs.length) error("inputs", "Add at least one motion input.");
  if (!groups.length) error("motion_groups", "Add at least one Motion Group.");

  const robotNames = new Set(catalogs.robots.map((entry) => entry.name));
  const teleopNames = new Set(catalogs.teleops.map((entry) => entry.name));
  const mapperNames = new Set(catalogs.mappers.map((entry) => entry.name));
  const channels = new Set(inputs.map(([, input]) => input.channel));
  const resources = new Set(qualifiedResources(document).map((resource) => resource.name));
  const resourceKinds = new Map(qualifiedResources(document).map((resource) => [resource.name, resource.kind]));

  adapters.forEach(([id, adapter]) => {
    if (!idPattern.test(id)) error(`adapters.${id}`, "Adapter ID must start with a letter and use letters, numbers, _ or -.");
    if (!robotNames.has(adapter.robot)) error(`adapters.${id}.robot`, `Robot config '${adapter.robot}' does not exist.`);
    const resourceEntries = Object.entries(adapter.resources);
    if (!resourceEntries.length) error(`adapters.${id}.resources`, "Expose at least one named resource.");
    resourceEntries.forEach(([name, resource]) => {
      if (!idPattern.test(name)) error(`adapters.${id}.resources.${name}`, "Resource name is not path-safe.");
      if (resource.kind === "joint" && !(resource.joint_names?.length)) {
        error(`adapters.${id}.resources.${name}`, "Joint resources need joint names.");
      }
      if (resource.kind === "joint" && resource.joint_names?.length === 5) {
        warning(`adapters.${id}.resources.${name}`, "Five-DoF arms cannot reproduce every SE(3) orientation; use a soft-orientation mapper.");
      }
    });
    if (!document.home?.adapters?.[id]) {
      warning(`home.adapters.${id}`, "No calibrated Home target; this adapter will hold its current pose.");
    }
  });

  inputs.forEach(([id, input]) => {
    if (!idPattern.test(id)) error(`inputs.${id}`, "Input ID is not path-safe.");
    if (!teleopNames.has(input.teleop)) error(`inputs.${id}.teleop`, `Teleop config '${input.teleop}' does not exist.`);
    if (!input.channel) error(`inputs.${id}.channel`, "Channel is required.");
    if (!(input.control_rate_hz > 0)) error(`inputs.${id}.control_rate_hz`, "Control rate must be positive.");
  });
  if (inputs.length && !channels.has(document.default_channel)) {
    error("default_channel", "Default channel must match one of the input channels.");
  }

  const owners = new Map<string, string>();
  groups.forEach(([id, group]) => {
    if (!idPattern.test(id)) error(`motion_groups.${id}`, "Motion Group ID is not path-safe.");
    if (!document.inputs[group.input]) error(`motion_groups.${id}.input`, `Input '${group.input}' does not exist.`);
    if (!mapperNames.has(group.mapper)) error(`motion_groups.${id}.mapper`, `Mapper config '${group.mapper}' does not exist.`);
    if (!group.outputs.length) error(`motion_groups.${id}.outputs`, "Select at least one output resource.");
    group.outputs.forEach((output) => {
      if (!resources.has(output)) error(`motion_groups.${id}.outputs`, `Resource '${output}' does not exist.`);
      const previous = owners.get(output);
      if (previous) error(`motion_groups.${id}.outputs`, `'${output}' is already claimed by '${previous}'.`);
      else owners.set(output, id);
    });
    const mapper = catalogs.mappers.find((entry) => entry.name === group.mapper)?.content ?? {};
    if ("arm_resource" in mapper && !group.outputs.some((output) => resourceKinds.get(output) === "joint")) {
      error(`motion_groups.${id}.outputs`, "This mapper needs a joint/arm output.");
    }
    if ("drive_resource" in mapper && !group.outputs.some((output) => resourceKinds.get(output) === "planar")) {
      error(`motion_groups.${id}.outputs`, "This mapper needs a planar drive output.");
    }
    if (group.mapper_wrapper === "legacy" && group.outputs.filter((output) => resourceKinds.get(output) === "joint").length !== 1) {
      error(`motion_groups.${id}.outputs`, "Legacy mappers require exactly one joint/arm output.");
    }
    if (!(group.control_rate_hz > 0)) error(`motion_groups.${id}.control_rate_hz`, "Control rate must be positive.");
  });

  Object.entries(document.home?.adapters ?? {}).forEach(([adapterId, target]) => {
    if (!document.adapters[adapterId]) error(`home.adapters.${adapterId}`, "Home target references a missing adapter.");
    (target.channels ?? []).forEach((channel) => {
      if (!channels.has(channel)) error(`home.adapters.${adapterId}.channels`, `Channel '${channel}' does not exist.`);
    });
    if (!target.pose_path && !target.joint_pos?.length) {
      error(`home.adapters.${adapterId}`, "Home target needs a pose path or explicit joint positions.");
    }
  });
  if (!(document.state_rate_hz > 0)) error("state_rate_hz", "State rate must be positive.");
  return issues;
}
