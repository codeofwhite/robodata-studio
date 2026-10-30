"""Resolve independently selected tabletop and background appearance."""
import json
from robot_data_contracts.pbr_material import EnvironmentAppearance
from .pbr_material_service import resolve


def resolve_environment(raw, registry=None):
    if isinstance(raw, str):
        raw = json.loads(raw)
    requested = EnvironmentAppearance.model_validate(raw or {}).model_dump()
    return {target: resolve(value, registry) if value is not None else None
            for target, value in requested.items()}
