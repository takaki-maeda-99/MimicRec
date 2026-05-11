from __future__ import annotations
import importlib
from pathlib import Path

from fastapi import HTTPException
from omegaconf import OmegaConf

from mimicrec.cameras.manager import CameraManager
from mimicrec.errors import InvalidTransitionError
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.session.lifecycle import SessionManager
from mimicrec.session.replay import GripperBinarize
from mimicrec.session.replay_safety import ReplaySafetyConfig
from mimicrec.types import SessionMode
from mimicrec.util.error_bus import ErrorBus


def get_configs_root(app) -> Path:
    root = getattr(app.state, "configs_root", None)
    if root is None:
        import os
        root = Path(os.environ.get("MIMICREC_CONFIGS_ROOT", "configs"))
    return root


def get_datasets_root(app) -> Path:
    root = getattr(app.state, "datasets_root", None)
    if root is None:
        import os
        root = Path(os.environ.get("MIMICREC_DATASETS_ROOT", "datasets"))
    return root


def get_vla_dest_root(app) -> Path:
    root = getattr(app.state, "vla_dest_root", None)
    if root is None:
        import os
        root = Path(os.environ.get("MIMICREC_VLA_DEST_ROOT", "~/vla-gemma-4/data/local"))
    return Path(root).expanduser()


def get_session_manager(app) -> SessionManager:
    sm = getattr(app.state, "session_manager", None)
    if sm is None:
        raise InvalidTransitionError("no active session")
    return sm


def get_session_manager_or_none(app):
    return getattr(app.state, "session_manager", None)


def instantiate_adapter(target_str: str, **kwargs):
    """Import and instantiate a class from a dotted path like 'mimicrec.adapters.mock_robot.MockRobotAdapter'."""
    module_path, class_name = target_str.rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls(**kwargs)


async def create_session_from_request(app, req) -> SessionManager:
    """Build a SessionManager from a StartSessionRequest."""
    configs_root = get_configs_root(app)
    datasets_root = get_datasets_root(app)

    # Load robot config and instantiate
    robot_cfg = OmegaConf.load(configs_root / "robot" / f"{req.robot}.yaml")
    # Robot YAML may carry blocks that are not adapter constructor kwargs
    # (replay safety, kinematics for EE pose, inference_safety for the
    # closed-loop VLA inference filter). Strip them before passing.
    _robot_meta_keys = {"_target_", "replay", "kinematics", "inference_safety"}
    robot_kwargs = {k: v for k, v in OmegaConf.to_container(robot_cfg).items()
                   if k not in _robot_meta_keys}
    robot = instantiate_adapter(str(robot_cfg._target_), **robot_kwargs)

    # Teleop + mapper (only for TELEOP mode)
    teleop = None
    mapper = None
    teleop_cfg = None
    mapper_cfg = None
    teleop_name = getattr(req, "teleop", None)
    mapper_name = getattr(req, "mapper", None)
    if teleop_name:
        teleop_cfg = OmegaConf.load(configs_root / "teleop" / f"{teleop_name}.yaml")
        teleop_kwargs = {k: v for k, v in OmegaConf.to_container(teleop_cfg).items()
                        if k not in ("_target_",)}
        teleop = instantiate_adapter(str(teleop_cfg._target_), **teleop_kwargs)
    if mapper_name:
        mapper_cfg = OmegaConf.load(configs_root / "mapper" / f"{mapper_name}.yaml")
        mapper_kwargs = {k: v for k, v in OmegaConf.to_container(mapper_cfg).items()
                        if k not in ("_target_",)}
        # Resolve URDF / package-dir paths relative to the repo root
        # (mirrors the robot kinematics block below).
        for k in ("so101_urdf_path", "rebotarm_urdf_path"):
            v = mapper_kwargs.get(k)
            if isinstance(v, str) and not Path(v).is_absolute():
                mapper_kwargs[k] = str((configs_root.parent / v).resolve())
        pkg_dirs = mapper_kwargs.get("rebotarm_package_dirs")
        if isinstance(pkg_dirs, list):
            mapper_kwargs["rebotarm_package_dirs"] = [
                str((configs_root.parent / d).resolve())
                if isinstance(d, str) and not Path(d).is_absolute() else d
                for d in pkg_dirs
            ]
        mapper = instantiate_adapter(str(mapper_cfg._target_), **mapper_kwargs)

    # Cameras
    cams = {}
    cam_cfgs: dict[str, object] = {}
    for cam_name in req.cameras:
        cam_cfg = OmegaConf.load(configs_root / "cameras" / f"{cam_name}.yaml")
        cam_cfgs[cam_name] = OmegaConf.to_container(cam_cfg)
        cam_kwargs = {k: v for k, v in OmegaConf.to_container(cam_cfg).items()
                     if k not in ("_target_",)}
        cam_kwargs.setdefault("name", cam_name)
        cams[cam_name] = instantiate_adapter(str(cam_cfg._target_), **cam_kwargs)

    # GoPros (NEW)
    overlap = set(req.cameras) & set(getattr(req, "gopros", []))
    if overlap:
        raise HTTPException(status_code=400,
                            detail=f"name overlap between cameras and gopros: {sorted(overlap)}")

    gopro_devices: list = []
    for g_name in getattr(req, "gopros", []):
        try:
            g_cfg = OmegaConf.load(configs_root / "gopros" / f"{g_name}.yaml")
            g_kwargs = {k: v for k, v in OmegaConf.to_container(g_cfg).items()
                        if k not in ("_target_",)}
            g_kwargs.setdefault("name", g_name)
            gopro_devices.append(instantiate_adapter(str(g_cfg._target_), **g_kwargs))
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400,
                                detail=f"GoPro config '{g_name}' invalid: {e}") from e

    error_bus = ErrorBus()

    from mimicrec.recording.dataset_layout import dataset_paths as _ds_paths
    _paths = _ds_paths(datasets_root / req.dataset)
    _paths.pending_dir.mkdir(parents=True, exist_ok=True)

    gopro_registry = None
    if gopro_devices:
        from mimicrec.gopro.registry import GoProDeviceRegistry
        try:
            gopro_registry = GoProDeviceRegistry(
                devices=gopro_devices, paths=_paths, errors=error_bus,
            )
        except ValueError as e:
            raise HTTPException(status_code=400,
                                detail=f"GoPro registry invalid: {e}") from e

        await gopro_registry.start()
        for name, src in gopro_registry.preview_sources().items():
            cams[name] = src

    cm = CameraManager(cameras=cams, error_bus=error_bus)

    # Replay safety
    replay_safety = None
    if "replay" in robot_cfg:
        replay_safety = ReplaySafetyConfig.from_robot_cfg(
            robot_cfg, dof=robot.dof, dt_sec=1.0 / req.fps
        )

    gripper_binarize = None
    if "replay" in robot_cfg and "gripper_binarize" in robot_cfg.replay:
        gb = robot_cfg.replay.gripper_binarize
        if bool(gb.get("enabled", False)):
            gripper_binarize = GripperBinarize(
                threshold=float(gb.threshold),
                open_value=float(gb.open_value),
                closed_value=float(gb.closed_value),
                dwell_delta=float(gb.get("dwell_delta", 0.0)),
            )

    # Forward kinematics for EE pose recording (optional; requires placo).
    # Robot config may declare a `kinematics:` block with urdf_path etc.;
    # paths are resolved relative to MIMICREC_CONFIGS_ROOT's parent (repo root).
    fk = None
    kin_cfg = robot_cfg.get("kinematics", None) if hasattr(robot_cfg, "get") else None
    if kin_cfg is None and "kinematics" in robot_cfg:
        kin_cfg = robot_cfg["kinematics"]
    if kin_cfg is not None:
        from mimicrec.kinematics import load_kinematics
        kin_dict = OmegaConf.to_container(kin_cfg)
        urdf = kin_dict.get("urdf_path") if isinstance(kin_dict, dict) else None
        if urdf and not Path(urdf).is_absolute():
            kin_dict["urdf_path"] = str((configs_root.parent / urdf).resolve())
        fk = load_kinematics(kin_dict)

    # Dataset
    ds_root = datasets_root / req.dataset
    # NOTE: pending_dir.mkdir (above) may have already created ds_root.
    # Guard on info.json presence rather than directory existence so that
    # init_dataset is called even when the pending dir was pre-created.
    info_path = ds_root / "meta" / "info.json"
    if not info_path.exists():
        # Capture per-adapter declarations if available (None for mock adapters).
        rt = type(robot).__name__
        gc = (
            robot.default_gripper_convention()
            if hasattr(robot, "default_gripper_convention") else None
        )
        pl = (
            robot.proprio_layout()
            if hasattr(robot, "proprio_layout") else None
        )
        camera_resolutions = {
            cam_name: (
                int(cam_cfgs[cam_name].get("width", 640)),
                int(cam_cfgs[cam_name].get("height", 480)),
            )
            for cam_name in req.cameras
        }
        init_dataset(
            ds_root, fps=req.fps,
            joint_names=robot.joint_names,
            camera_names=list(req.cameras),
            robot_type=rt,
            gripper_convention=(
                {"closed_at": gc.closed_at, "open_at": gc.open_at} if gc else None
            ),
            proprio_layout=(
                {
                    "columns": list(pl.columns),
                    "output_names": list(pl.output_names),
                    "gripper_via_column": pl.gripper_via_column,
                    "gripper_index_in_column": pl.gripper_index_in_column,
                } if pl else None
            ),
            camera_resolutions=camera_resolutions,
            gopro_specs=gopro_registry.gopro_specs() if gopro_registry else None,
        )
    else:
        # Existing dataset — its features schema is fixed at creation time.
        # Reject session start if robot type, fps, or camera/gopro set differs
        # from what info.json declares. Without this guard you can:
        #   - record episode 3 with a different robot than episodes 0-2
        #   - add cameras mid-dataset that aren't in info.json (orphan files
        #     on disk that no loader will read)
        # → produces silently-broken datasets. LeRobot v3 expects one schema.
        import json as _json
        try:
            info = _json.loads(info_path.read_text())
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"dataset '{req.dataset}' info.json is unreadable: {e}",
            ) from e

        existing_robot_type = info.get("robot_type")
        actual_robot_type = type(robot).__name__
        if existing_robot_type and existing_robot_type != actual_robot_type:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"dataset '{req.dataset}' was created with robot_type="
                    f"{existing_robot_type!r}; this request uses {actual_robot_type!r}. "
                    f"Create a new dataset for a different robot."
                ),
            )

        existing_fps = info.get("fps")
        if existing_fps and int(existing_fps) != int(req.fps):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"dataset '{req.dataset}' fps={existing_fps}; this request "
                    f"fps={req.fps}. Cannot change fps mid-dataset."
                ),
            )

        existing_image_keys = {
            k.removeprefix("observation.images.")
            for k in info.get("features", {})
            if k.startswith("observation.images.")
        }
        requested_images = set(req.cameras) | set(getattr(req, "gopros", []))
        if existing_image_keys != requested_images:
            missing = sorted(existing_image_keys - requested_images)
            extra = sorted(requested_images - existing_image_keys)
            parts: list[str] = []
            if missing:
                parts.append(f"missing {missing}")
            if extra:
                parts.append(f"unexpected {extra} (not in dataset schema)")
            raise HTTPException(
                status_code=400,
                detail=(
                    f"dataset '{req.dataset}' was created with cameras+gopros="
                    f"{sorted(existing_image_keys)}; request differs ({'; '.join(parts)}). "
                    f"Create a new dataset to use a different camera set."
                ),
            )

    # Resolved config snapshot
    resolved: dict[str, object] = {"robot": OmegaConf.to_container(robot_cfg)}
    if teleop_cfg is not None:
        resolved["teleop"] = OmegaConf.to_container(teleop_cfg)
    if mapper_cfg is not None:
        resolved["mapper"] = OmegaConf.to_container(mapper_cfg)
    if cam_cfgs:
        resolved["cameras"] = cam_cfgs

    # Store metadata in app.state for payload building
    app.state.error_bus = error_bus
    app.state.camera_manager = cm
    app.state.gopro_registry = gopro_registry
    app.state.resolved_config = resolved
    app.state.session_meta = {
        "dataset": req.dataset,
        "task": req.task,
        "robot": req.robot,
        "teleop": teleop_name,
        "mapper": mapper_name,
        "cameras": list(req.cameras),
        "gopros": list(getattr(req, "gopros", [])),
        "fps": req.fps,
    }

    mode = SessionMode(req.mode)

    sm = SessionManager(
        dataset_root=ds_root,
        robot=robot,
        teleop=teleop,
        mapper=mapper,
        cameras=cm,
        mode=mode,
        fps=req.fps,
        error_bus=error_bus,
        resolved_config=resolved,
        replay_safety=replay_safety,
        gripper_binarize=gripper_binarize,
        fk=fk,
        task=req.task or "default",
        instruction=getattr(req, "instruction", "") or "",
        coordinator=getattr(app.state, "push_coordinator", None),
        ds_name=req.dataset,
        app=app,
        gopro_registry=gopro_registry,
    )
    return sm
