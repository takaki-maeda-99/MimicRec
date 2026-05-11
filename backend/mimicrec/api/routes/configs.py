from __future__ import annotations
from fastapi import APIRouter, Request
from omegaconf import OmegaConf
from mimicrec.api.deps import get_configs_root

router = APIRouter()


@router.get("/configs/camera_roles")
async def camera_roles(request: Request) -> dict:
    """Returns the global slot vocabulary defined in
    configs/camera_roles.yaml. Used by the frontend to populate the
    slot dropdown in the session config form."""
    configs_root = get_configs_root(request.app)
    path = configs_root / "camera_roles.yaml"
    if not path.exists():
        return {"roles": []}
    cfg = OmegaConf.load(path)
    roles = list(cfg.roles) if hasattr(cfg, "roles") else []
    return {"roles": roles}


@router.get("/configs/{group}")
async def list_configs(request: Request, group: str):
    configs_root = get_configs_root(request.app)
    group_dir = configs_root / group
    if not group_dir.is_dir():
        raise FileNotFoundError(f"config group '{group}' not found")
    return [p.stem for p in sorted(group_dir.glob("*.yaml"))]
