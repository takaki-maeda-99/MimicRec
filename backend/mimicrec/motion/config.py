"""YAML profile loader for multi-adapter SE3Delta motion graphs."""
from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path

from omegaconf import OmegaConf

from mimicrec.adapters.robot import RobotMode
from mimicrec.motion.input import LegacyTeleopMotionSource, MotionTeleopRouter
from mimicrec.motion.legacy import LegacyRobotResourceAdapter, SE3DeltaToLegacyMapper
from mimicrec.motion.runtime import MotionGroup, MotionInput, MotionRuntime
from mimicrec.util.error_bus import ErrorBus
from mimicrec.util.latest_value import LatestValue


ROBOT_META_KEYS = {
    "_target_",
    "replay",
    "kinematics",
    "inference_safety",
    "teleop_home",
}


def _instantiate(target: str, kwargs: dict):
    module_name, class_name = target.rsplit(".", 1)
    return getattr(importlib.import_module(module_name), class_name)(**kwargs)


def _resolved_kwargs(config: dict, repo_root: Path) -> dict:
    result = {key: value for key, value in config.items() if key != "_target_"}
    for key, value in list(result.items()):
        if (
            isinstance(value, str)
            and (key.endswith("_path") or key in {"urdf_path"})
            and not Path(value).is_absolute()
        ):
            result[key] = str((repo_root / value).resolve())
        elif key.endswith("package_dirs") and isinstance(value, list):
            result[key] = [
                str((repo_root / item).resolve())
                if isinstance(item, str) and not Path(item).is_absolute()
                else item
                for item in value
            ]
    return result


@dataclass(frozen=True)
class BuiltMotionProfile:
    name: str
    runtime: MotionRuntime
    teleop_router: MotionTeleopRouter
    resources: dict[str, dict]
    motion_groups: dict[str, dict]
    home: dict
    resolved_config: dict


def build_motion_profile(
    name: str,
    *,
    configs_root: Path,
    error_bus: ErrorBus | None = None,
    document: dict | None = None,
) -> BuiltMotionProfile:
    if document is None:
        profile_path = configs_root / "motion_profiles" / f"{name}.yaml"
        raw = OmegaConf.to_container(OmegaConf.load(profile_path), resolve=True)
    else:
        raw = OmegaConf.to_container(OmegaConf.create(document), resolve=True)
    if not isinstance(raw, dict):
        raise ValueError(f"motion profile {name!r} must be a mapping")
    repo_root = configs_root.parent

    adapters = {}
    resource_schema: dict[str, dict] = {}
    resolved_adapters: dict[str, dict] = {}
    for adapter_id, entry_raw in (raw.get("adapters") or {}).items():
        entry = dict(entry_raw)
        robot_name = str(entry["robot"])
        robot_raw = OmegaConf.to_container(
            OmegaConf.load(configs_root / "robot" / f"{robot_name}.yaml"),
            resolve=True,
        )
        robot_kwargs = {
            key: value for key, value in robot_raw.items() if key not in ROBOT_META_KEYS
        }
        robot = _instantiate(str(robot_raw["_target_"]), robot_kwargs)
        wrapper = str(entry.get("wrapper", "native"))
        if wrapper == "legacy":
            safe_mode = RobotMode(str(entry.get("safe_mode", "gravity_comp")))
            adapter = LegacyRobotResourceAdapter(
                robot,
                include_gripper=bool(entry.get("include_gripper", True)),
                safe_mode=safe_mode,
            )
        elif wrapper == "native":
            adapter = robot
        else:
            raise ValueError(f"unknown adapter wrapper {wrapper!r}")
        adapters[str(adapter_id)] = adapter
        resolved_adapters[str(adapter_id)] = {
            "profile": entry,
            "robot": robot_raw,
        }
        declared = entry.get("resources") or {}
        for local_name, spec in declared.items():
            if local_name not in adapter.resource_names:
                raise ValueError(
                    f"adapter {adapter_id!r} does not expose {local_name!r}"
                )
            resource_schema[f"{adapter_id}.{local_name}"] = dict(spec)

    channels = {}
    motion_inputs = []
    input_slots: dict[str, LatestValue] = {}
    resolved_inputs: dict[str, dict] = {}
    input_entries = raw.get("inputs") or {}
    for input_name, entry_raw in input_entries.items():
        entry = dict(entry_raw)
        teleop_name = str(entry["teleop"])
        teleop_raw = OmegaConf.to_container(
            OmegaConf.load(configs_root / "teleop" / f"{teleop_name}.yaml"),
            resolve=True,
        )
        teleop = _instantiate(
            str(teleop_raw["_target_"]),
            {key: value for key, value in teleop_raw.items() if key != "_target_"},
        )
        channel = str(entry.get("channel", input_name))
        if channel in channels:
            raise ValueError(f"duplicate motion input channel {channel!r}")
        channels[channel] = teleop
        source = LegacyTeleopMotionSource(
            teleop,
            frame=str(entry.get("frame", "ee_local")),
            default_rate_hz=float(entry.get("control_rate_hz", 60.0)),
        )
        slot = LatestValue()
        input_slots[str(input_name)] = slot
        motion_inputs.append(MotionInput(str(input_name), source, slot))
        resolved_inputs[str(input_name)] = {"profile": entry, "teleop": teleop_raw}
    if not channels:
        raise ValueError("motion profile must declare at least one input")
    default_channel = str(raw.get("default_channel", next(iter(channels))))
    router = MotionTeleopRouter(channels, default_channel=default_channel)

    motion_groups = []
    motion_group_schema: dict[str, dict] = {}
    resolved_groups: dict[str, dict] = {}
    for group_name, entry_raw in (raw.get("motion_groups") or {}).items():
        entry = dict(entry_raw)
        input_name = str(entry["input"])
        if input_name not in input_slots:
            raise ValueError(
                f"motion group {group_name!r} references unknown input {input_name!r}"
            )
        mapper_name = str(entry["mapper"])
        mapper_raw = OmegaConf.to_container(
            OmegaConf.load(configs_root / "mapper" / f"{mapper_name}.yaml"),
            resolve=True,
        )
        outputs = tuple(str(output) for output in entry["outputs"])
        mapper_config = dict(mapper_raw)
        mapper_config.update(dict(entry.get("mapper_args") or {}))
        # Resource-qualified outputs belong to the profile, not a reusable
        # mapper YAML. Inject conventional endpoint arguments when present so
        # renaming an adapter in the visual editor changes the executable
        # graph as well as its diagram.
        arm_outputs = [output for output in outputs if output.endswith(".arm")]
        gripper_outputs = [
            output for output in outputs if output.endswith(".gripper")
        ]
        planar_outputs = [
            output for output in outputs if output.endswith(".drive")
        ]
        if "arm_resource" in mapper_config and len(arm_outputs) == 1:
            mapper_config["arm_resource"] = arm_outputs[0]
        if "gripper_resource" in mapper_config and len(gripper_outputs) <= 1:
            mapper_config["gripper_resource"] = (
                gripper_outputs[0] if gripper_outputs else None
            )
        if "drive_resource" in mapper_config and len(planar_outputs) == 1:
            mapper_config["drive_resource"] = planar_outputs[0]
        mapper = _instantiate(
            str(mapper_config["_target_"]),
            _resolved_kwargs(mapper_config, repo_root),
        )
        mapper_wrapper = str(entry.get("mapper_wrapper", "native"))
        if mapper_wrapper == "legacy":
            if len(arm_outputs) != 1 or len(gripper_outputs) > 1:
                raise ValueError(
                    f"legacy mapper group {group_name!r} needs one arm and "
                    "at most one gripper output"
                )
            mapper = SE3DeltaToLegacyMapper(
                mapper,
                arm_resource=arm_outputs[0],
                gripper_resource=(gripper_outputs[0] if gripper_outputs else None),
                target_frame=str(mapper_config.get("delta_frame", "base")),
                world_to_base_rotation=entry.get("world_to_base_rotation"),
            )
        elif mapper_wrapper != "native":
            raise ValueError(f"unknown mapper wrapper {mapper_wrapper!r}")
        motion_groups.append(MotionGroup(
            name=str(group_name),
            input_slot=input_slots[input_name],
            mapper=mapper,
            output_resources=outputs,
            control_rate_hz=float(entry.get("control_rate_hz", 60.0)),
        ))
        motion_group_schema[str(group_name)] = {
            "input": input_name,
            "outputs": list(outputs),
            "auxiliary": list(entry.get("auxiliary", ["gripper"])),
        }
        resolved_groups[str(group_name)] = {
            "profile": entry,
            "mapper": mapper_config,
        }

    runtime = MotionRuntime(
        adapters=adapters,
        motion_groups=motion_groups,
        motion_inputs=motion_inputs,
        error_bus=error_bus,
        state_rate_hz=float(raw.get("state_rate_hz", 60.0)),
    )
    missing_schema = set(runtime.resource_names) - set(resource_schema)
    if missing_schema:
        raise ValueError(
            f"motion profile lacks recording schema for {sorted(missing_schema)}"
        )
    resolved = {
        "motion_profile": raw,
        "adapters": resolved_adapters,
        "inputs": resolved_inputs,
        "motion_groups": resolved_groups,
    }
    home = dict(raw.get("home") or {})
    if home:
        adapters_home = home.get("adapters") or {}
        if not isinstance(adapters_home, dict):
            raise ValueError("motion profile home.adapters must be a mapping")
        resolved_targets: dict[str, dict] = {}
        for adapter_id, target_raw in adapters_home.items():
            if adapter_id not in adapters:
                raise ValueError(
                    f"home target references unknown adapter {adapter_id!r}"
                )
            target = dict(target_raw)
            pose_path = target.get("pose_path")
            if pose_path is not None:
                path = Path(str(pose_path))
                if not path.is_absolute():
                    path = repo_root / path
                pose_doc = OmegaConf.to_container(OmegaConf.load(path), resolve=True)
                if not isinstance(pose_doc, dict):
                    raise ValueError(f"home pose {path} must be a mapping")
                target["joint_names"] = list(pose_doc.get("joint_names") or [])
                target["joint_pos"] = list(pose_doc["joint_pos_rad"])
                if pose_doc.get("gripper_pos") is not None:
                    target["gripper_pos"] = float(pose_doc["gripper_pos"])
                target["pose_path"] = str(path.resolve())
            if "joint_pos" not in target:
                raise ValueError(
                    f"home target for adapter {adapter_id!r} needs joint_pos or pose_path"
                )
            home_channels = tuple(str(item) for item in target.get("channels") or ())
            unknown_channels = set(home_channels) - set(channels)
            if unknown_channels:
                raise ValueError(
                    f"home target for adapter {adapter_id!r} references unknown "
                    f"channels {sorted(unknown_channels)}"
                )
            target["channels"] = list(home_channels)
            resolved_targets[str(adapter_id)] = target
        home["adapters"] = resolved_targets
        resolved["home"] = home
    return BuiltMotionProfile(
        name=name,
        runtime=runtime,
        teleop_router=router,
        resources=resource_schema,
        motion_groups=motion_group_schema,
        home=home,
        resolved_config=resolved,
    )
