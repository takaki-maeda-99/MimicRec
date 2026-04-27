"""Rewrite a LeRobot info.json for VLA-compat output (pure)."""
from __future__ import annotations

import copy
from typing import Any

GRIPPER_AXIS_NAME = "gripper"


def to_vla_info(info: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copied info dict with action/observation.state at shape [7]
    and a ``language_instruction`` feature added.

    The input dict is not mutated.
    """
    new = copy.deepcopy(info)
    features = new.setdefault("features", {})

    for key in ("action", "observation.state"):
        spec = features.get(key)
        if spec is None:
            spec = {"dtype": "float32", "shape": [7], "names": []}
            features[key] = spec
        names = list(spec.get("names") or [])
        # Ensure exactly 6 joint names + "gripper" — if input listed 6, append gripper;
        # if input already listed 7 with gripper at the end, leave it.
        if names and names[-1] != GRIPPER_AXIS_NAME:
            names = names[:6] + [GRIPPER_AXIS_NAME]
        elif not names:
            names = [f"joint_{i}" for i in range(6)] + [GRIPPER_AXIS_NAME]
        spec["names"] = names
        spec["shape"] = [7]
        spec["dtype"] = "float32"

    features["language_instruction"] = {
        "dtype": "string",
        "shape": [1],
        "names": None,
    }

    return new
