from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from robot_data_contracts import WorkerDescriptorV1
from robot_data_contracts.scene import SceneParameter

from ..camera_profiles import camera_profile_descriptors
from ..physics_backends import physics_backend_descriptors
from ..render_profiles import renderer_profile_descriptors


@dataclass(frozen=True)
class WorkerReadiness:
    kind: str
    timeout_s: float
    host: str | None = None
    port: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "timeout_s": self.timeout_s,
            "host": self.host,
            "port": self.port,
        }


@dataclass(frozen=True)
class WorkerLaunch:
    command: list[str]
    cwd: Path
    env_updates: dict[str, str] = field(default_factory=dict)
    unset_env: tuple[str, ...] = ()
    readiness: WorkerReadiness = field(
        default_factory=lambda: WorkerReadiness(kind="process", timeout_s=10.0)
    )
    resources: tuple[str, ...] = ()


class CollectionAdapter(ABC):
    adapter_id: str
    label: str
    capabilities: dict[str, bool]
    scenes: dict[str, dict[str, Any]]
    control_modes: tuple[str, ...]
    camera_profile_ids: tuple[str, ...]
    renderer_profile_ids: tuple[str, ...] = ()
    physics_backends: tuple[str, ...] = ()

    def descriptor(self) -> dict[str, Any]:
        worker = WorkerDescriptorV1(
            worker_id=f"gello_remote_{self.adapter_id}", engine_id=self.adapter_id,
            entrypoint=self.worker_entrypoint, control_modes=self.control_modes,
            capabilities=self.capabilities,
        )
        return {
            "id": self.adapter_id,
            "label": self.label,
            "capabilities": self.capabilities,
            "control_modes": list(self.control_modes),
            "scenes": self._contract_scenes(),
            "camera_profiles": camera_profile_descriptors(self.camera_profile_ids),
            "renderer_profiles": renderer_profile_descriptors(self.renderer_profile_ids),
            "physics_backends": physics_backend_descriptors(self.physics_backends),
            "worker": worker.model_dump(mode="json"),
        }

    def _contract_scenes(self) -> dict[str, dict[str, Any]]:
        # Adapters declare their scenes as plain dicts, and the session form reads
        # `parameter.choices.length` without a guard because SceneParameter gives
        # `choices` a default. Genesis resolves its parameters through the scene
        # plugin and so always carried it; the Isaac and RoboVerse adapters built
        # theirs by hand and omitted it, which crashed the page on selecting any
        # of their scenes. Resolve every parameter through the contract here, at
        # the single point where all adapters are serialized: a parameter that
        # cannot satisfy the contract now fails loudly in the backend.
        return {
            scene_id: {
                **scene,
                "parameters": [
                    SceneParameter.model_validate(parameter).model_dump(mode="json")
                    for parameter in scene.get("parameters", [])
                ],
            }
            for scene_id, scene in self.scene_descriptors().items()
        }

    @property
    def worker_entrypoint(self) -> str:
        return f"gello_remote.{self.adapter_id}_worker"

    def scene_descriptors(self) -> dict[str, dict[str, Any]]:
        return self.scenes

    @abstractmethod
    def validate_config(self, config: dict[str, Any]) -> None: ...

    @abstractmethod
    def build_collect_command(self, config: dict[str, Any], output_dir: Path) -> list[str]: ...

    @abstractmethod
    def build_worker_launch(self, config: dict[str, Any], output_dir: Path) -> WorkerLaunch: ...
