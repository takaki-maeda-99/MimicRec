from __future__ import annotations
import importlib
from pathlib import Path

from omegaconf import OmegaConf

from mimicrec.cameras.manager import CameraManager
from mimicrec.errors import InvalidTransitionError
from mimicrec.recording.dataset_layout import init_dataset
from mimicrec.session.lifecycle import SessionManager
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
    # (replay safety, kinematics for EE pose). Strip them before passing.
    _robot_meta_keys = {"_target_", "replay", "kinematics"}
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

    error_bus = ErrorBus()
    cm = CameraManager(cameras=cams, error_bus=error_bus)

    # Replay safety
    replay_safety = None
    if "replay" in robot_cfg:
        replay_safety = ReplaySafetyConfig.from_robot_cfg(
            robot_cfg, dof=robot.dof, dt_sec=1.0 / req.fps
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
    if not ds_root.exists():
        init_dataset(ds_root, fps=req.fps,
                     joint_names=robot.joint_names, camera_names=list(req.cameras))

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
    app.state.resolved_config = resolved
    app.state.session_meta = {
        "dataset": req.dataset,
        "task": req.task,
        "robot": req.robot,
        "teleop": teleop_name,
        "mapper": mapper_name,
        "cameras": list(req.cameras),
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
        fk=fk,
        task=req.task or "default",
        instruction=getattr(req, "instruction", "") or "",
    )
    return sm
