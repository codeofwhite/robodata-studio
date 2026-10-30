from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class SceneParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    unit: str = ""
    # Numeric parameters bound the range; a parameter that carries `choices` is
    # categorical instead and leaves both bounds unset.
    minimum: float | None = None
    maximum: float | None = None
    default: float | int | str
    step: float | None = None
    scale: Literal["linear", "log"] = "linear"
    choices: list[str] = Field(default_factory=list)


class SceneDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    description: str
    family: str
    parameters: list[SceneParameter] = Field(default_factory=list)


class ScenePluginDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: Literal["robot_data_scene_plugin"] = "robot_data_scene_plugin"
    contract_version: Literal[1] = 1
    plugin_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    engine_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    scenes: list[SceneDescriptor]


@runtime_checkable
class SceneRuntime(Protocol):
    scene_id: str
    task_instruction: str
    state_names: list[str]
    action_names: list[str]
    camera_names: list[str]

    def reset(self) -> None: ...

    def observe(self) -> Any: ...

    def render(self) -> dict[str, Any]: ...

    def apply_action(self, action: Any, physics_steps: int) -> None: ...

    def evaluate(self) -> tuple[bool, dict[str, Any]]: ...

    def status_metrics(self) -> dict[str, float | bool]: ...

    def geometry_metadata(self) -> dict[str, Any]: ...

    def resolved_scene_spec(self) -> dict[str, Any]: ...


@runtime_checkable
class ScenePlugin(Protocol):
    plugin_id: str
    engine_id: str

    def describe(self) -> ScenePluginDescriptor: ...

    def validate(
        self, scene_id: str, parameters: Mapping[str, float | int | str]
    ) -> dict[str, float | int | str]: ...

    def create(
        self, runtime_config: Any, scene_id: str, parameters: Mapping[str, float | int | str]
    ) -> SceneRuntime: ...
