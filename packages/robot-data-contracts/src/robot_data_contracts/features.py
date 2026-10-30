from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FeatureRole(str, Enum):
    NATIVE_STATE = "native_state"
    POLICY_STATE = "policy_state"
    OPERATOR_ACTION = "operator_action"
    REQUESTED_ACTION = "requested_action"
    SAFE_ACTION = "safe_action"
    APPLIED_ACTION = "applied_action"
    AUXILIARY = "auxiliary"


class FeatureSpecV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    role: FeatureRole
    dtype: Literal["float32", "float64", "int64", "int32", "int8", "bool"]
    shape: tuple[int, ...]
    names: tuple[str, ...] = ()
    units: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_dimensions(self) -> "FeatureSpecV1":
        if not self.shape or any(size <= 0 for size in self.shape):
            raise ValueError("feature shape must contain positive dimensions")
        flat = self.shape[0] if len(self.shape) == 1 else None
        if self.names and flat != len(self.names):
            raise ValueError("feature names must match a one-dimensional shape")
        if self.units and len(self.units) not in {1, len(self.names)}:
            raise ValueError("feature units must contain one value or match names")
        return self


class ActionProfileV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    representation: Literal["absolute_joint_position", "delta_joint_position", "end_effector_delta"]
    dimension: int = Field(gt=0)
    names: tuple[str, ...]
    units: tuple[str, ...]
    gripper_semantics: str

    @model_validator(mode="after")
    def validate_dimensions(self) -> "ActionProfileV1":
        if len(self.names) != self.dimension or len(self.units) != self.dimension:
            raise ValueError("action names and units must match dimension")
        return self
