from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from .config import settings


ControlMode = Literal["keyboard", "gello", "scripted"]
EngineId = Literal["genesis", "isaac_sim", "roboverse"]
QaStatus = Literal["pending", "accepted", "rejected"]
ExportFormat = Literal["lerobot", "openpi_lerobot_v21", "rlds", "robomimic"]


class SessionCreate(BaseModel):
    cloth_generation_plan_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    generation_plan_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    engine_id: EngineId = "isaac_sim"
    dataset_name: str = Field(min_length=1, max_length=80)
    scene_id: str = Field(min_length=1, max_length=100)
    control_mode: ControlMode
    target_episodes: int = Field(default=50, ge=1, le=10_000)
    port: int = Field(default=8080, ge=1024, le=65535)
    gpu: int = Field(default=0, ge=0, le=255)
    control_fps: int = Field(default=10, ge=1, le=120)
    sim_dt: float = Field(default=0.01, gt=0, le=0.1)
    physics_steps_per_control: int = Field(default=10, ge=1, le=64)
    width: int = Field(default=640, ge=64, le=4096)
    height: int = Field(default=480, ge=64, le=4096)
    camera_profile_id: str = Field(default="lab_d435i_dual_v1", pattern=r"^[a-z][a-z0-9_]*$")
    renderer_profile_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")
    physics_backend: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")
    # Categorical scene parameters (a garment id, say) arrive as strings; numeric
    # ones as numbers. The scene plugin decides which keys accept what.
    scene_params: dict[str, float | int | str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_generation_mode(self):
        if self.cloth_generation_plan_id or self.generation_plan_id:
            settings.require_extension("generation")
        if self.cloth_generation_plan_id and (self.generation_plan_id or self.engine_id != "isaac_sim" or self.scene_id != "curobo_cloth_replay" or self.control_mode != "scripted"):
            raise ValueError("cloth appearance plans require scripted Isaac curobo_cloth_replay")
        if self.generation_plan_id and (self.engine_id != "isaac_sim" or self.scene_id != "rigid_cube_lift" or self.control_mode != "scripted"):
            raise ValueError("generation plans require scripted Isaac rigid_cube_lift")
        return self

    @model_validator(mode="after")
    def resolve_renderer_profile(self):
        if self.engine_id == "isaac_sim" and self.renderer_profile_id is None:
            self.renderer_profile_id = "isaac_balanced_v1"
        if self.engine_id != "isaac_sim" and self.renderer_profile_id is not None:
            raise ValueError("renderer profiles are currently supported only by Isaac Sim")
        return self

    @model_validator(mode="after")
    def resolve_physics_backend(self):
        # Left None for the adapter to fill from settings, so the deployment-wide
        # default stays in one place (`settings.isaac_physics_backend`).
        if self.engine_id != "isaac_sim" and self.physics_backend is not None:
            raise ValueError("physics backends are currently supported only by Isaac Sim")
        return self

    @field_validator("dataset_name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        cleaned = value.strip()
        if any(part in cleaned for part in ("/", "\\", "..")):
            raise ValueError("dataset_name must be a simple name")
        return cleaned


class QaUpdate(BaseModel):
    qa_status: QaStatus
    failure_reason: str | None = Field(default=None, max_length=240)


class SessionDeleteConfirm(BaseModel):
    confirm_session_id: str = Field(min_length=1, max_length=240)
    delete_accepted_data: bool = False


class ExportCreate(BaseModel):
    dataset_id: int
    episode_ids: list[int] = Field(min_length=1, max_length=100_000)
    format: ExportFormat
    output_name: str = Field(min_length=1, max_length=100)
    repo_id: str | None = Field(default=None, max_length=200)
    images: bool = False
    profile: Literal["physical_joint8", "openpi_franka_joint8", "fastwam_franka_joint8"] = "physical_joint8"

    @model_validator(mode="after")
    def validate_format_profile(self) -> "ExportCreate":
        if self.format in {"lerobot", "openpi_lerobot_v21"} and not self.repo_id:
            raise ValueError("LeRobot exports require repo_id")
        if self.format == "openpi_lerobot_v21" and self.profile != "openpi_franka_joint8":
            raise ValueError("OpenPI LeRobot v2.1 requires profile openpi_franka_joint8")
        if self.format == "lerobot" and self.profile == "openpi_franka_joint8":
            raise ValueError("OpenPI profile requires format openpi_lerobot_v21")
        return self

    @field_validator("output_name")
    @classmethod
    def safe_output_name(cls, value: str) -> str:
        cleaned = value.strip()
        if any(part in cleaned for part in ("/", "\\", "..")):
            raise ValueError("output_name must be a simple name")
        return cleaned

    @field_validator("episode_ids")
    @classmethod
    def distinct_episode_ids(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("episode_ids must not contain duplicates")
        if any(episode_id < 1 for episode_id in value):
            raise ValueError("episode_ids must contain positive IDs")
        return value


class ApiMessage(BaseModel):
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)
