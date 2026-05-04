from __future__ import annotations
from typing import Literal
import yaml
from pydantic import BaseModel, Field, field_validator


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
        return cls.model_validate(data)
