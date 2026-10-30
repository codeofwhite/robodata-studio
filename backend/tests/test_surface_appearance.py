import json
from pathlib import Path

import pytest
from robot_data_contracts.pbr_material import AppearanceVariant
from robot_data_contracts.usd_surface import validate_environment
from robot_data_studio.services.surface_appearance import resolve_environment
from robot_data_studio.services.asset_service import AssetRegistry
from robot_data_studio.services import pbr_material_service as service


def test_original_and_solid_surfaces_are_independent():
    assert resolve_environment(None) == {'tabletop': None, 'background': None}
    value = resolve_environment({'tabletop': {'color': '#c09966', 'roughness': .2}})
    assert value['tabletop']['color'] == '#c09966' and value['background'] is None
    assert resolve_environment(json.dumps({'tabletop': {'color': '#c09966', 'roughness': .2}})) == value
    validate_environment(value)
    with pytest.raises(ValueError):
        AppearanceVariant(environment={'background': {'texture': 'cotton'}})
    with pytest.raises(ValueError):
        AppearanceVariant(environment={'tabletop': {'material_id': 'MAT-wood'}})


def test_environment_plan_pins_material_and_detects_changed_maps(tmp_path):
    from test_pbr_materials import png
    sources = tmp_path/'sources.json'
    sources.write_text(json.dumps({'schema_version': 1, 'sources': {'cc0-surfaces-v1': {'root': str(tmp_path/'maps')}}}))
    registry = AssetRegistry(tmp_path/'registry', sources)
    material = service.import_material('wood', {role: png() for role in service.ROLES}, category='tabletop', registry=registry)
    value = resolve_environment({'tabletop': {'material_id': material['asset_id'], 'material_version': 1}}, registry)
    validate_environment(value)
    assert value['tabletop']['material_content_sha256']
    assert set(value['tabletop']['maps']) == set(service.ROLES)
    Path(value['tabletop']['maps']['normal']['path']).write_bytes(png(12))
    with pytest.raises(ValueError, match='changed'):
        validate_environment(value)
