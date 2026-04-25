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
    robot_kwargs = {k: v for k, v in OmegaConf.to_container(robot_cfg).items()
                   if k not in ("_target_", "replay")}
    robot = instantiate_adapter(str(robot_cfg._target_), **robot_kwargs)

    # Teleop + mapper (only for TELEOP mode)
    teleop = None
    mapper = None
    teleop_name = getattr(req, "teleop", None)
    mapper_name = getattr(req, "mapper", None)
    if teleop_name:
        teleop_cfg = OmegaConf.load(configs_root / "teleop" / f"{teleop_name}.yaml")
        teleop_kwargs = {k: v for k, v in OmegaConf.to_container(teleop_cfg).items()
                        if k not in ("_target_",)}
        teleop = instantiate_adapter(str(teleop_cfg._target_), **teleop_kwargs)
    if mapper_name:
        mapper_cfg = OmegaConf.load(configs_root / "mapper" / f"{mapper_name}.yaml")
        mapper = instantiate_adapter(str(mapper_cfg._target_))

    # Cameras
    cams = {}
    for cam_name in req.cameras:
        cam_cfg = OmegaConf.load(configs_root / "cameras" / f"{cam_name}.yaml")
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

    # Dataset
    ds_root = datasets_root / req.dataset
    if not ds_root.exists():
        init_dataset(ds_root, fps=req.fps,
                     joint_names=robot.joint_names, camera_names=list(req.cameras))

    # Resolved config snapshot
    resolved = {"robot": OmegaConf.to_container(robot_cfg)}

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
    )
    return sm
