"""Rewrite a LeRobot info.json for VLA-compat output (pure)."""
from __future__ import annotations

import copy
from typing import Any

from mimicrec.adapters.types import ProprioLayout

ACTION_NAMES = ["ee_dx", "ee_dy", "ee_dz", "ee_drx", "ee_dry", "ee_drz", "gripper"]


def to_vla_info(
    info: dict[str, Any],
    *,
    robot_type: str,
    gripper_convention: dict,
    proprio_layout: ProprioLayout,
    n_proprio: int,
) -> dict[str, Any]:
    """Return a deep-copied info dict with action/observation.state for the
    VLA-compat schema and the recording-time adapter declarations carried
    through to the export.

    The input `info` dict is not mutated.
    """
    new = copy.deepcopy(info)
    new["robot_type"] = robot_type
    new["gripper_convention"] = gripper_convention
    new["proprio_layout"] = {
        "columns": list(proprio_layout.columns),
        "output_names": list(proprio_layout.output_names),
        "gripper_via_column": proprio_layout.gripper_via_column,
        "gripper_index_in_column": proprio_layout.gripper_index_in_column,
    }
    features = new.setdefault("features", {})

    features["action"] = {
        "dtype": "float32", "shape": [7], "names": list(ACTION_NAMES),
    }

    obs_names = list(proprio_layout.output_names)
    if len(obs_names) != n_proprio:
        raise ValueError(
            f"proprio name/shape mismatch: layout.output_names has {len(obs_names)} "
            f"entries but n_proprio={n_proprio}"
        )
    features["observation.state"] = {
        "dtype": "float32", "shape": [n_proprio], "names": obs_names,
    }

    features["language_instruction"] = {
        "dtype": "string", "shape": [1], "names": None,
    }
    return new
