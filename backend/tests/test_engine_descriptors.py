from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from robot_data_studio.adapters import engine_descriptors
from robot_data_studio.adapters.base import CollectionAdapter, WorkerLaunch


class _HandBuiltAdapter(CollectionAdapter):
    """An adapter that declares its scene parameters as plain dicts."""

    adapter_id = "hand_built"
    label = "Hand built"
    capabilities = {"recording": False}
    control_modes = ("scripted",)
    camera_profile_ids = ()

    def __init__(self, parameters: list[dict]) -> None:
        self.scenes = {
            "scene_one": {
                "label": "Scene one",
                "description": "A scene",
                "family": "general",
                "parameters": parameters,
            }
        }

    def validate_config(self, config: dict) -> None: ...

    def build_collect_command(self, config: dict, output_dir: Path) -> list[str]:
        return []

    def build_worker_launch(self, config: dict, output_dir: Path) -> WorkerLaunch:
        raise NotImplementedError


def test_hand_built_parameter_gains_the_contract_default_for_choices() -> None:
    """A numeric parameter that never mentions `choices` still ships one.

    The session form reads `parameter.choices.length` without a guard, because
    `SceneParameter` declares `choices` with a default. Isaac and RoboVerse built
    their parameters by hand without it, so selecting one of their scenes threw
    `Cannot read properties of undefined (reading 'length')` and the page died.
    """
    adapter = _HandBuiltAdapter(
        [{"key": "height_m", "label": "Height", "unit": "m", "default": 0.25}]
    )
    parameters = adapter._contract_scenes()["scene_one"]["parameters"]
    assert parameters[0]["choices"] == []


def test_a_parameter_the_contract_cannot_express_fails_in_the_backend() -> None:
    """Contract violations surface here rather than in the browser."""
    adapter = _HandBuiltAdapter([{"key": "height_m", "label": "Height"}])
    with pytest.raises(ValidationError):
        adapter._contract_scenes()


def test_every_registered_scene_parameter_carries_choices() -> None:
    for engine in engine_descriptors():
        for scene_id, scene in engine["scenes"].items():
            for parameter in scene["parameters"]:
                assert isinstance(parameter.get("choices"), list), (
                    f"{engine['id']}/{scene_id}/{parameter['key']} has no choices"
                )


def test_every_adapter_ships_a_physics_backend_list() -> None:
    """The session form guards on `.length`, so the key must always be present."""
    for engine in engine_descriptors():
        backends = engine["physics_backends"]
        assert isinstance(backends, list), f"{engine['id']} has no physics_backends key"
        for backend in backends:
            assert backend["id"] and backend["label"], f"{engine['id']}/{backend} is unlabelled"


def test_isaac_advertises_physx_and_newton() -> None:
    isaac = next(engine for engine in engine_descriptors() if engine["id"] == "isaac_sim")
    assert [backend["id"] for backend in isaac["physics_backends"]] == ["physx", "newton", "genesis_ipc"]
