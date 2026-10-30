from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RendererSetting = bool | int | float | str


class RendererProfileV1(BaseModel):
    """Import-safe renderer selection and explicit Kit setting overrides."""

    model_config = ConfigDict(extra="forbid")
    format: Literal["robot_data_renderer_profile"] = "robot_data_renderer_profile"
    format_version: Literal[1] = 1
    profile_version: int = Field(default=1, ge=1)
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    engine_id: Literal["isaac_sim"] = "isaac_sim"
    rendering_mode: Literal["performance", "balanced", "quality"]
    kit_settings: dict[str, RendererSetting] = Field(default_factory=dict)


def load_renderer_profile(path: str | Path) -> RendererProfileV1:
    source = Path(path).expanduser().resolve()
    return RendererProfileV1.model_validate_json(source.read_bytes())


def renderer_profile_metadata(profile: RendererProfileV1, *, source: str | Path | None = None) -> dict:
    value = profile.model_dump(mode="json")
    if source is not None:
        path = Path(source).expanduser().resolve()
        value["profile_source"] = str(path)
        value["profile_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        value["profile_sha256"] = hashlib.sha256(canonical).hexdigest()
    return value
