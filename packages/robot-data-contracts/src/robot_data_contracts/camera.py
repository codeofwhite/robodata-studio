from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CameraStreamV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    source_fps: float = Field(gt=0)
    format: str = "rgb8"


class CameraRoleV1(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    model: str
    calibration_source_serial: str | None = None
    mount: str | None = None
    nominal_vertical_fov_deg: float | None = Field(default=None, gt=0, lt=180)
    stream: CameraStreamV1
    intrinsics: dict[str, float] | None = None
    distortion: dict[str, Any] | list[float] | None = None


class CameraProfileV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["robot_data_camera_profile"] = "robot_data_camera_profile"
    format_version: Literal[1] = 1
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    match_level: Literal["nominal_pending_intrinsics", "intrinsics_matched", "sensor_matched"]
    dataset_fps_default: float = Field(default=10, gt=0)
    roles: dict[str, CameraRoleV1]
    inventory: list[dict[str, Any]] = Field(default_factory=list)
    engine_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_roles(self) -> "CameraProfileV1":
        if not self.roles or not any(role.enabled for role in self.roles.values()):
            raise ValueError("camera profile must contain an enabled role")
        if self.match_level != "nominal_pending_intrinsics":
            for name, role in self.roles.items():
                if role.enabled and not role.intrinsics:
                    raise ValueError(f"camera role {name} requires calibrated intrinsics")
        return self


def load_camera_profile(path: str | Path, *, width: int | None = None, height: int | None = None) -> CameraProfileV1:
    source = Path(path).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("format") == "robot_data_studio_camera_profile":
        payload["format"] = "robot_data_camera_profile"
    profile = CameraProfileV1.model_validate(payload)
    if width is not None and height is not None:
        for name, role in profile.roles.items():
            if role.enabled and (role.stream.width, role.stream.height) != (width, height):
                raise ValueError(f"camera role {name} does not provide enabled {width}x{height} RGB")
    return profile


def camera_profile_metadata(profile: CameraProfileV1, *, source: str | None = None) -> dict[str, Any]:
    value = profile.model_dump(mode="json")
    value.pop("engine_overrides", None)
    value.pop("inventory", None)
    if source is not None:
        value["profile_source"] = source
    return value
