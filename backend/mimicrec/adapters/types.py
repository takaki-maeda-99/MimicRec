from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class GripperConvention:
    """Per-robot raw-gripper → unit-gripper [0,1] mapping declaration.

    Forward map: action_gripper = clip((raw - closed_at) / (open_at - closed_at), 0, 1).
    Works for both closed_at < open_at (SO-101) and closed_at > open_at (reBot).
    """
    closed_at: float
    open_at: float

    def __post_init__(self):
        if abs(self.open_at - self.closed_at) < 1e-9:
            raise ValueError(f"GripperConvention has zero span: {self}")


@dataclass(frozen=True)
class ProprioLayout:
    """Declarative composition for observation.state at export time.

    `columns` is the ordered tuple of parquet column names whose values are
    concatenated row-by-row to form observation.state.

    `output_names` is the full per-dim name list for the resulting vector,
    in concat order. Length agreement with the actual concat dim is
    validated at runtime in _build_observation_state (cannot be checked
    here because list-column widths come from parquet data).

    `gripper_via_column` and `gripper_index_in_column` locate the raw
    gripper value the action label normalizes from. For SO-101 the gripper
    is at joint_pos[5] (offset 5 of the joint_pos list). For reBot it is
    the only entry of the scalar gripper_pos column (offset 0).
    """
    columns: tuple[str, ...]
    output_names: tuple[str, ...]
    gripper_via_column: str
    gripper_index_in_column: int

    def __post_init__(self):
        if self.gripper_via_column not in self.columns:
            raise ValueError(
                f"gripper_via_column {self.gripper_via_column!r} not in columns {self.columns}"
            )
        if self.gripper_index_in_column < 0:
            raise ValueError(
                f"gripper_index_in_column must be >= 0, got {self.gripper_index_in_column}"
            )
