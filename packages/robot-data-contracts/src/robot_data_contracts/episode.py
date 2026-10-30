from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .features import ActionProfileV1, FeatureRole, FeatureSpecV1


class SoftwareProvenanceV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    python_version: str
    platform: str
    engine_id: str
    engine_version: str
    worker_id: str
    git_revisions: dict[str, str] = Field(default_factory=dict)
    dependencies: dict[str, str] = Field(default_factory=dict)


class SceneProvenanceV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str
    seed: int = Field(ge=0)
    parameters: dict[str, Any] = Field(default_factory=dict)
    assets: list[dict[str, Any]] = Field(default_factory=list)


class EvaluatorResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evaluator_id: str
    evaluator_version: str
    available: bool
    success: bool | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def validate_availability(self) -> "EvaluatorResultV1":
        if self.available and self.success is None:
            raise ValueError("available evaluator requires success")
        if not self.available and not self.unavailable_reason:
            raise ValueError("unavailable evaluator requires a reason")
        return self


class AugmentationLineageV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_episode_uuid: str | None = None
    generation_method: Literal[
        "teleoperation",
        "scripted",
        "policy_rollout",
        "visual_rerender",
        "physics_replay",
        "retargeted",
    ]
    randomization_spec_id: str | None = None
    randomization_seed: int | None = Field(default=None, ge=0)
    resolved_parameters: dict[str, Any] = Field(default_factory=dict)
    trajectory_modified: bool = False


class EpisodeManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["robot_data_episode"] = "robot_data_episode"
    format_version: Literal[1] = 1
    episode_uuid: str
    episode_index: int = Field(ge=0)
    task: str
    robot_id: str
    control_source: str
    fps: int = Field(gt=0)
    num_frames: int = Field(gt=0)
    features: tuple[FeatureSpecV1, ...]
    action_profile: ActionProfileV1
    camera_names: tuple[str, ...]
    camera_calibration: dict[str, dict[str, Any]]
    scene: SceneProvenanceV1
    software: SoftwareProvenanceV1
    evaluator: EvaluatorResultV1
    lineage: AugmentationLineageV1
    operator_success: bool | None = None
    failure_reason: str | None = None
    created_at: datetime
    timing: str = "observation_t is captured before applied_action_t is submitted"
    timestamp_domains: dict[str, str] = Field(default_factory=lambda: {
        "episode_time_s": "episode-relative fixed-rate timeline",
        "simulation_time_s": "engine simulation clock",
        "control_source_timestamp_ns": "Unix epoch at command source; -1 when unavailable",
        "control_receive_timestamp_ns": "worker monotonic clock; -1 when unavailable",
        "capture_timestamp_ns": "worker monotonic clock",
    })
    image_color_order: Literal["RGB"] = "RGB"

    @model_validator(mode="after")
    def validate_required_roles(self) -> "EpisodeManifestV1":
        roles = {feature.role for feature in self.features}
        required = {
            FeatureRole.NATIVE_STATE, FeatureRole.POLICY_STATE, FeatureRole.OPERATOR_ACTION,
            FeatureRole.REQUESTED_ACTION, FeatureRole.SAFE_ACTION, FeatureRole.APPLIED_ACTION,
        }
        missing = sorted(role.value for role in required - roles)
        if missing:
            raise ValueError(f"episode is missing required feature roles: {missing}")
        if set(self.camera_names) != set(self.camera_calibration):
            raise ValueError("camera_names and camera_calibration keys must match")
        for name, calibration in self.camera_calibration.items():
            if not calibration.get("intrinsics"):
                raise ValueError(f"camera {name} requires intrinsics")
            if not calibration.get("extrinsics"):
                raise ValueError(f"camera {name} requires extrinsics")
        return self
