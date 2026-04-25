from __future__ import annotations
from typing import Annotated, Literal
from pydantic import BaseModel, Field
from mimicrec.types import SessionMode, SessionState, SubState


class _BaseSessionRequest(BaseModel):
    dataset: str
    task: str
    robot: str
    cameras: list[str]
    fps: int = 30


class TeleopSessionRequest(_BaseSessionRequest):
    mode: Literal["teleop"] = "teleop"
    teleop: str
    mapper: str


class HandTeachSessionRequest(_BaseSessionRequest):
    mode: Literal["hand_teach"] = "hand_teach"


StartSessionRequest = Annotated[
    TeleopSessionRequest | HandTeachSessionRequest,
    Field(discriminator="mode"),
]


class SaveEpisodeRequest(BaseModel):
    success: bool | None = None
    comment: str | None = None


class ReplayStartRequest(BaseModel):
    dataset: str
    episode_idx: int
    speed: float = Field(default=1.0, ge=0.1, le=5.0)


class CreateDatasetRequest(BaseModel):
    name: str
    fps: int = 30
    joint_names: list[str] = []
    camera_names: list[str] = []


class CreateTaskRequest(BaseModel):
    name: str
    instruction: str = ""


class SessionStatePayload(BaseModel):
    state: str
    sub_state: str | None = None
    mode: str | None = None
    dataset: str | None = None
    task: str | None = None
    robot: str | None = None
    teleop: str | None = None
    mapper: str | None = None
    cameras: list[str] = []
    fps: int | None = None


class DatasetSummary(BaseModel):
    name: str
    num_episodes: int
    total_frames: int


class EpisodeSummary(BaseModel):
    episode_index: int
    task: str
    duration_sec: float
    num_frames: int
    success: bool | None = None
    robot: str
    teleop: str | None = None
    mode: str
    recorded_at: str | None = None
    cameras: list[str] = []


class TaskSummary(BaseModel):
    task_index: int
    task: str
    instruction: str | None = None


class ErrorPayload(BaseModel):
    detail: str
