from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkerDescriptorV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract: Literal["robot_data_worker"] = "robot_data_worker"
    contract_version: Literal[1] = 1
    worker_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    engine_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    entrypoint: str
    control_modes: tuple[str, ...]
    capabilities: dict[str, bool]
