"""Settings API: device discovery, config editing, calibration status."""
from __future__ import annotations

import asyncio
import glob
import json
from dataclasses import asdict
from pathlib import Path

import cv2
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from omegaconf import OmegaConf

from mimicrec.api.deps import get_configs_root
from mimicrec.cameras.v4l2_caps import enumerate_capabilities
from mimicrec.cameras.opencv_camera import decode_fourcc

router = APIRouter()


# --- Device discovery ---

@router.get("/settings/devices/serial")
async def list_serial_ports(response: Response):
    """List available serial ports."""
    response.headers["Cache-Control"] = "no-store"
    ports = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
    result = []
    for port in ports:
        try:
            import serial
            s = serial.Serial(port, timeout=0.1)
            s.close()
            result.append({"port": port, "available": True})
        except Exception:
            result.append({"port": port, "available": False})
    return result


@router.get("/settings/devices/cameras")
async def list_camera_devices(response: Response):
    """List available camera devices."""
    response.headers["Cache-Control"] = "no-store"
    import cv2
    devices = sorted(glob.glob("/dev/video*"))
    result = []
    for dev in devices:
        dev_id = int(dev.replace("/dev/video", ""))
        cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
        opened = cap.isOpened()
        w, h = 0, 0
        if opened:
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
        result.append({"path": dev, "device_id": dev_id, "available": opened, "width": w, "height": h})
    return result


@router.get("/settings/devices/cameras/{device_id}/capabilities")
async def list_camera_capabilities(device_id: int, response: Response):
    """Enumerate V4L2 capabilities for /dev/video{device_id} via v4l2-ctl.

    Returns 200 with [] if v4l2-ctl is unavailable or returns nothing useful
    so the UI can render gracefully. Returns 404 only when /dev/video{N}
    does not exist on disk.
    """
    response.headers["Cache-Control"] = "no-store"
    path = f"/dev/video{device_id}"
    if path not in glob.glob("/dev/video*"):
        raise HTTPException(status_code=404, detail=f"device {path} not found")

    loop = asyncio.get_running_loop()
    caps = await loop.run_in_executor(None, enumerate_capabilities, path)
    return [asdict(c) for c in caps]


# --- Config CRUD ---

class ConfigUpdate(BaseModel):
    content: dict


@router.get("/settings/configs/{group}")
async def list_group_configs(request: Request, group: str, response: Response):
    """List all configs in a group with their contents."""
    response.headers["Cache-Control"] = "no-store"
    root = get_configs_root(request.app)
    group_dir = root / group
    if not group_dir.is_dir():
        raise FileNotFoundError(f"config group '{group}' not found")
    configs = []
    for f in sorted(group_dir.glob("*.yaml")):
        cfg = OmegaConf.load(f)
        configs.append({
            "name": f.stem,
            "file": str(f),
            "content": OmegaConf.to_container(cfg),
        })
    return configs


@router.get("/settings/configs/{group}/{name}")
async def get_config(request: Request, group: str, name: str, response: Response):
    """Get a single config file's contents."""
    response.headers["Cache-Control"] = "no-store"
    root = get_configs_root(request.app)
    path = root / group / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"config '{group}/{name}' not found")
    cfg = OmegaConf.load(path)
    return {"name": name, "group": group, "content": OmegaConf.to_container(cfg)}


@router.put("/settings/configs/{group}/{name}")
async def update_config(
    request: Request, group: str, name: str, body: ConfigUpdate, response: Response
):
    """Update a config file. For OpenCVCamera configs, validate by opening
    the camera and reading back the negotiated parameters before writing.
    Returns 409 on mismatch. If the camera is busy (in use by another
    session), validation is skipped and an X-Validation-Skipped header is
    set so the UI can warn the user that final validation will happen at
    session_start.
    """
    response.headers["Cache-Control"] = "no-store"
    root = get_configs_root(request.app)
    path = root / group / f"{name}.yaml"

    if (
        group == "cameras"
        and isinstance(body.content, dict)
        and body.content.get("_target_") == "mimicrec.cameras.opencv_camera.OpenCVCamera"
    ):
        await _validate_camera_config_or_409(body.content, response)

    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = OmegaConf.create(body.content)
    OmegaConf.save(cfg, path)
    return {"name": name, "group": group, "content": body.content}


async def _validate_camera_config_or_409(content: dict, response: Response) -> None:
    """Open the camera with the requested parameters, read back, and either
    raise HTTPException(409) on mismatch or set X-Validation-Skipped on busy.
    Returns None when validation passes (the route falls through to write the YAML).
    """
    device_id = int(content.get("device_id", 0))
    width = int(content.get("width", 640))
    height = int(content.get("height", 480))
    pixel_format = content.get("pixel_format")
    capture_fps = content.get("capture_fps")

    def _probe():
        cap = cv2.VideoCapture(f"/dev/video{device_id}", cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            return ("busy", None)
        try:
            if pixel_format is not None:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*pixel_format))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            if capture_fps is not None:
                cap.set(cv2.CAP_PROP_FPS, capture_fps)

            actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            actual_fourcc = decode_fourcc(int(cap.get(cv2.CAP_PROP_FOURCC)))
            actual_fps = int(round(cap.get(cv2.CAP_PROP_FPS)))
        finally:
            cap.release()

        mismatches: list[str] = []
        if actual_w != width or actual_h != height:
            mismatches.append(f"size: requested {width}x{height}, got {actual_w}x{actual_h}")
        if pixel_format is not None and actual_fourcc != pixel_format:
            mismatches.append(f"fourcc: requested {pixel_format}, got {actual_fourcc!r}")
        if capture_fps is not None and actual_fps != capture_fps:
            mismatches.append(f"fps: requested {capture_fps}, got {actual_fps}")
        return ("ok", mismatches)

    loop = asyncio.get_running_loop()
    status, mismatches = await loop.run_in_executor(None, _probe)
    if status == "busy":
        response.headers["X-Validation-Skipped"] = "device-busy"
        return
    if mismatches:
        raise HTTPException(
            status_code=409,
            detail="validation failed: " + "; ".join(mismatches),
        )


@router.post("/settings/configs/{group}/{name}")
async def create_config(request: Request, group: str, name: str, body: ConfigUpdate):
    """Create a new config file."""
    root = get_configs_root(request.app)
    path = root / group / f"{name}.yaml"
    if path.exists():
        raise ValueError(f"config '{group}/{name}' already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = OmegaConf.create(body.content)
    OmegaConf.save(cfg, path)
    return {"name": name, "group": group, "content": body.content}


@router.delete("/settings/configs/{group}/{name}", status_code=204)
async def delete_config(request: Request, group: str, name: str):
    """Delete a config file. Refuses with 409 if the config is currently
    bound to an active recording session — deleting it would leave the
    writer holding a path that no longer exists on disk.
    """
    # Active-session guard. Match against session_meta with the same
    # shape build_state_payload() produces at session.py:42-61.
    # A stale manager left in IDLE after FatalHardwareError is treated
    # as logically gone (matches the session_start path at session.py:81-86).
    meta = getattr(request.app.state, "session_meta", None) or {}
    sm = getattr(request.app.state, "session_manager", None)
    active = (
        sm is not None
        and getattr(sm.session, "state", None) is not None
        and sm.session.state.value != "idle"
        and not sm.session.stopped.is_set()
    )
    if active:
        if group in ("robot", "teleop", "mapper"):
            if meta.get(group) == name:
                raise HTTPException(
                    status_code=409,
                    detail=f"active session uses this config (group={group}, name={name})",
                )
        elif group == "cameras":
            for src in meta.get("slot_assignments", []):
                src_kind = src.get("kind") if isinstance(src, dict) else getattr(src, "kind", None)
                src_device = src.get("device") if isinstance(src, dict) else getattr(src, "device", None)
                if src_kind == "camera" and src_device == name:
                    raise HTTPException(
                        status_code=409,
                        detail=f"active session uses this camera config (name={name})",
                    )

    root = get_configs_root(request.app)
    path = root / group / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"config '{group}/{name}' not found")
    path.unlink()


# --- Calibration ---

@router.get("/settings/calibration")
async def list_calibrations(response: Response):
    """List available calibration files."""
    response.headers["Cache-Control"] = "no-store"
    calib_root = Path.home() / ".cache/huggingface/lerobot/calibration"
    result = {"robots": {}, "teleoperators": {}}
    for category in ["robots", "teleoperators"]:
        cat_dir = calib_root / category
        if not cat_dir.exists():
            continue
        for robot_dir in sorted(cat_dir.iterdir()):
            if robot_dir.is_dir():
                files = [f.stem for f in robot_dir.glob("*.json")]
                result[category][robot_dir.name] = files
    return result


@router.get("/settings/calibration/{category}/{robot_type}/{cal_id}")
async def get_calibration(category: str, robot_type: str, cal_id: str):
    """Get calibration data."""
    calib_root = Path.home() / ".cache/huggingface/lerobot/calibration"
    path = calib_root / category / robot_type / f"{cal_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"calibration not found: {path}")
    return json.loads(path.read_text())
