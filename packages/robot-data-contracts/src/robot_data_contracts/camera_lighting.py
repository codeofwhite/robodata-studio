"""Concrete visual parameters and deterministic plan-time sampling."""
import hashlib
import random
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class CameraLightingValues(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    fov_offset_deg: float = Field(default=0, ge=-15, le=15)
    camera_x_m: float = Field(default=0, ge=-.3, le=.3)
    camera_y_m: float = Field(default=0, ge=-.3, le=.3)
    camera_z_m: float = Field(default=0, ge=-.3, le=.3)
    camera_rx_deg: float = Field(default=0, ge=-20, le=20)
    camera_ry_deg: float = Field(default=0, ge=-20, le=20)
    camera_rz_deg: float = Field(default=0, ge=-20, le=20)
    exposure_ev: float = Field(default=0, ge=-3, le=3)
    white_balance_k: float | None = Field(default=None, ge=2000, le=10000)
    light_intensity_multiplier: float = Field(default=1, ge=.2, le=3)
    light_temperature_k: float | None = Field(default=None, ge=2000, le=10000)

class CameraLightingRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    mode: Literal['fixed', 'uniform'] = 'fixed'
    seed: int = Field(default=0, ge=0, le=2147483647)
    values: CameraLightingValues = Field(default_factory=CameraLightingValues)
    ranges: dict[str, tuple[float, float]] = Field(default_factory=dict)

    @model_validator(mode='after')
    def valid_ranges(self):
        if self.mode == 'fixed' and self.ranges:
            raise ValueError('固定配置不能包含采样范围')
        for key, (low, high) in self.ranges.items():
            if key not in CameraLightingValues.model_fields or low > high:
                raise ValueError('未知参数或采样下限大于上限：' + key)
            for endpoint in (low, high):
                CameraLightingValues.model_validate({**self.values.model_dump(), key: endpoint})
        return self

def sample(request, *, source_index=0, appearance_index=0):
    config = CameraLightingRequest.model_validate(request or {})
    values = config.values.model_dump()
    derived = int.from_bytes(hashlib.sha256(f'{config.seed}:{source_index}:{appearance_index}'.encode()).digest()[:8], 'big')
    rng = random.Random(derived)
    if config.mode == 'uniform':
        for key in sorted(config.ranges):
            values[key] = rng.uniform(*config.ranges[key])
    return {'request': config.model_dump(mode='json'), 'sample_seed': derived,
            'values': CameraLightingValues.model_validate(values).model_dump()}

def validate_resolved(value):
    if value is None:
        return
    if set(value) != {'request', 'sample_seed', 'values'}:
        raise ValueError('无效相机与光照快照')
    CameraLightingRequest.model_validate(value['request'])
    CameraLightingValues.model_validate(value['values'])
