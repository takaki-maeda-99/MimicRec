from __future__ import annotations
from typing import Literal
import json
import os
import re
from pathlib import Path
import yaml
from pydantic import BaseModel, Field, field_validator

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _interpolate_env(value):
    if isinstance(value, str):
        def repl(m):
            name = m.group(1)
            v = os.environ.get(name)
            if v is None:
                raise ValueError(f"contract references missing env var: {name}")
            return v
        return _ENV_RE.sub(repl, value)
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(v) for v in value]
    return value


# ---- Endpoint ----
class RetrySpec(BaseModel):
    max_attempts: int = 0


class EndpointSpec(BaseModel):
    url: str
    method: Literal["POST"] = "POST"
    timeout_s: float = 5.0
    headers: dict[str, str] = Field(default_factory=dict)
    retry: RetrySpec = Field(default_factory=RetrySpec)

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str) -> str:
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("endpoint.url must be http(s)")
        return v


# ---- Request ----
class ImageSpec(BaseModel):
    field: str
    encoding: Literal["jpeg_base64"] = "jpeg_base64"
    resize: tuple[int, int] = (224, 224)
    jpeg_quality: int = 90


class StatsRef(BaseModel):
    type: Literal["vla_export", "absolute"]
    dataset: str | None = None
    path: str | None = None


class NormalizationSpec(BaseModel):
    method: Literal["none", "minmax_neg1_pos1", "mean_std"] = "none"
    stats_ref: StatsRef | None = None


class StateSpec(BaseModel):
    field: str
    components: list[str]
    normalization: NormalizationSpec = Field(default_factory=NormalizationSpec)


class InstructionSpec(BaseModel):
    field: str


class RequestSpec(BaseModel):
    images: dict[str, ImageSpec]
    state: StateSpec
    instruction: InstructionSpec
    extra_fields: dict[str, str | int | float | bool] = Field(default_factory=dict)


# ---- Response ----
class ChunkSpec(BaseModel):
    expected_size: int
    on_size_mismatch: Literal["use_actual", "reject"] = "use_actual"


class PoseSpec(BaseModel):
    units: Literal["meter_axisangle_rad", "mm_euler_deg"] = "meter_axisangle_rad"


class GripperSpec(BaseModel):
    kind: Literal["absolute", "delta", "binary"]
    units: Literal["normalized_0_1", "percent_0_100", "binary_threshold_0p5"] = "normalized_0_1"


class ActionSpec(BaseModel):
    type: Literal["ee_delta"]
    frame: Literal["ee_local", "world"] = "ee_local"
    pose: PoseSpec = Field(default_factory=PoseSpec)
    gripper: GripperSpec
    components: list[str]
    normalization: NormalizationSpec = Field(default_factory=NormalizationSpec)


class DoneSpec(BaseModel):
    path: str
    type: Literal["bool", "float"] = "float"
    threshold: float = 0.5
    scope: Literal["chunk", "step"] = "chunk"
    action_on_done: Literal["auto_stop", "notify_only"] = "notify_only"


class ResponseSpec(BaseModel):
    actions_path: str
    chunk: ChunkSpec
    action: ActionSpec
    done: DoneSpec | None = None


# ---- Loop ----
class LoopSpec(BaseModel):
    prefetch_threshold: float = 0.5
    max_inflight: int = 1


# Registry of component dims. "Narm"-keyed components require an explicit Narm at resolve time.
_COMPONENT_DIM: dict[str, int | str] = {
    "joint_pos": "Narm",
    "gripper_pos": 1,
    "ee_pos": 3,
    "ee_rotvec": 3,
    "ee_delta": 6,
    "gripper": 1,
}


def _expected_dim(components: list[str], narm: int | None = None) -> int:
    total = 0
    for c in components:
        if c not in _COMPONENT_DIM:
            raise ValueError(f"unknown component '{c}'")
        d = _COMPONENT_DIM[c]
        if d == "Narm":
            if narm is None:
                raise ValueError(f"component '{c}' requires Narm context")
            total += narm
        else:
            total += d
    return total


def _resolve_stats_path(spec: "ContractSpec") -> Path | None:
    """Return the resolved on-disk path for action_stats.json, or None if
    the contract opts out of client-side normalization."""
    if spec.response.action.normalization.method == "none":
        return None
    sr = spec.response.action.normalization.stats_ref
    if sr is None:
        raise ValueError(
            "action.normalization.method != 'none' but stats_ref is missing"
        )
    if sr.type == "vla_export":
        root = Path(
            os.environ.get(
                "MIMICREC_VLA_DEST_ROOT",
                str(Path.home() / "vla-gemma-4" / "data" / "local"),
            )
        ).expanduser()
        return root / sr.dataset / "meta" / "action_stats.json"
    if sr.type == "absolute":
        return Path(sr.path)
    raise ValueError(f"unknown stats_ref.type: {sr.type}")


class ContractSpec(BaseModel):
    name: str
    description: str = ""
    endpoint: EndpointSpec
    request: RequestSpec
    response: ResponseSpec
    loop: LoopSpec = Field(default_factory=LoopSpec)

    @classmethod
    def from_yaml_text(cls, text: str) -> "ContractSpec":
        data = yaml.safe_load(text)
        data = _interpolate_env(data)
        spec = cls.model_validate(data)
        spec._post_validate()
        return spec

    def _post_validate(self) -> None:
        # image field uniqueness
        fields = [img.field for img in self.request.images.values()]
        if len(fields) != len(set(fields)):
            raise ValueError("request.images.<cam>.field values must be unique")
        # done scope MVP=chunk only
        if self.response.done and self.response.done.scope != "chunk":
            raise ValueError(
                f"done.scope='{self.response.done.scope}' not implemented in MVP "
                "(only 'chunk' is supported)"
            )
        # MVP: only meter_axisangle_rad is implemented in the decoder. Rejecting
        # unsupported units at load time prevents a silent 1000x mis-scale or
        # rotation-format mismatch when an operator drops in a contract for a
        # different VLA training stack.
        units = self.response.action.pose.units
        if units != "meter_axisangle_rad":
            raise ValueError(
                f"response.action.pose.units='{units}' not implemented in MVP "
                "(only 'meter_axisangle_rad' is supported)"
            )

    def resolve_action_stats(self) -> dict | None:
        """Load action_stats.json and assert length matches sum(action.components dims).
        Returns None when normalization is disabled (method='none'), so callers
        (lifecycle, ActionDecoder) can pass through unconditionally."""
        path = _resolve_stats_path(self)
        if path is None:
            return None                                  # method=none → no stats needed
        if not path.exists():
            raise FileNotFoundError(f"action_stats.json not found: {path}")
        stats = json.loads(path.read_text())
        expected = _expected_dim(self.response.action.components)
        if len(stats["mean"]) != expected or len(stats["std"]) != expected:
            raise ValueError(
                f"action_stats length mismatch: got mean[{len(stats['mean'])}], "
                f"std[{len(stats['std'])}], expected {expected} from components "
                f"{self.response.action.components}"
            )
        return stats
