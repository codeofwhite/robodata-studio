"""Renderer-independent appearance requests and immutable PBR map snapshots."""
from pathlib import Path
import hashlib

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Appearance(BaseModel):
    model_config = ConfigDict(extra='forbid')
    texture: str = Field(default='none', pattern=r'^(none|cotton|linen|denim|terry)$')
    color: str = Field(default='#386ba1', pattern=r'^#[0-9a-fA-F]{6}$')
    roughness: float = Field(default=.9, ge=0, le=1, allow_inf_nan=False)
    material_id: str | None = Field(default=None, pattern=r'^MAT-[a-z0-9][a-z0-9_-]{0,119}$')
    material_version: int | None = Field(default=None, ge=1)
    color_mode: str = Field(default='original', pattern=r'^(original|tint)$')
    roughness_multiplier: float = Field(default=1, ge=0, le=2, allow_inf_nan=False)
    normal_strength: float = Field(default=1, ge=0, le=2, allow_inf_nan=False)
    uv_scale: float = Field(default=1, ge=.1, le=50, allow_inf_nan=False)

    @model_validator(mode='after')
    def pinned_material(self):
        if bool(self.material_id) != bool(self.material_version):
            raise ValueError('材质 ID 和版本必须同时指定')
        return self


class EnvironmentAppearance(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tabletop: Appearance | None = None
    background: Appearance | None = None

    @model_validator(mode='after')
    def surface_textures(self):
        for value in (self.tabletop, self.background):
            if value is not None and value.texture != 'none':
                raise ValueError('环境表面请选择 PBR 材质或纯色')
        return self


from .camera_lighting import CameraLightingRequest


class AppearanceVariant(Appearance):
    environment: EnvironmentAppearance | None = None
    camera_lighting: CameraLightingRequest | None = None


def verify_maps(appearance):
    for entry in appearance.get('maps', {}).values():
        digest = hashlib.sha256(Path(entry['path']).read_bytes()).hexdigest()
        if digest != entry['sha256']:
            raise ValueError('PBR map changed: ' + entry['path'])
