import json

import pytest
from robot_data_contracts.asset import AssetDraft
from robot_data_studio.services.asset_service import AssetRegistry
from robot_data_studio.services.garment_appearance import appearance_options, resolve_appearance


@pytest.fixture
def registry(tmp_path):
    textures = tmp_path / 'source' / 'textures'
    textures.mkdir(parents=True)
    for texture in ('cotton', 'linen', 'denim', 'terry'):
        (textures / f'{texture}_color.png').write_bytes(b'existing image ' + texture.encode())
    sources = tmp_path / 'sources.json'
    sources.write_text(json.dumps({'schema_version': 1, 'sources': {
        'robot-cloth-scenes-v1': {'root': str(textures.parent)}}}))
    return AssetRegistry(tmp_path / 'registry', sources)


def garment(appearance=None):
    return AssetDraft(asset_id='MDL-clothforge-test', kind='model', name='Test', tags=['clothforge'],
        change_note='fixture', data={'appearance': appearance} if appearance else {})


def test_legacy_and_saved_appearance_with_session_override(registry):
    assert resolve_appearance(registry, garment())['texture_path'] is None
    options = appearance_options(registry, garment())
    assert [t['id'] for t in options['textures']] == ['none', 'cotton', 'linen', 'denim', 'terry']
    saved = garment({'texture': 'denim', 'color': '#abcdef', 'roughness': .4})
    resolved = resolve_appearance(registry, saved, {'visual_color': '#FFFFFF'})
    assert resolved['texture_path'].endswith('denim_color.png')
    assert resolved['color'] == '#ffffff' and resolved['roughness'] == .4
    assert saved.data['appearance']['color'] == '#abcdef'


@pytest.mark.parametrize('params', [{'visual_texture': '../bad'}, {'visual_color': 'red'},
    {'visual_color': '#abc'}, {'visual_roughness': float('nan')}, {'visual_roughness': True},
    {'visual_roughness': 1.01}])
def test_invalid_appearance_rejected(registry, params):
    with pytest.raises(ValueError):
        resolve_appearance(registry, garment(), params)


def test_saved_texture_hash_and_old_revision_are_preserved(registry):
    resolved = resolve_appearance(registry, garment(), {'visual_texture': 'cotton'})
    saved = garment({k: resolved[k] for k in ('texture', 'color', 'roughness', 'texture_sha256')})
    old, _ = registry.publish(garment())
    new, _ = registry.publish(saved, expected_version=1)
    assert new.version == 2 and 'appearance' not in registry.get(old.asset_id, 1).data
    path = registry.sources()['robot-cloth-scenes-v1']['root'] + '/textures/cotton_color.png'
    from pathlib import Path
    Path(path).write_bytes(b'changed')
    with pytest.raises(ValueError, match='变化'):
        resolve_appearance(registry, new)


def test_appearance_api_publishes_texture_revision_and_serves_thumbnail(registry, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from robot_data_studio.routes.assets import router
    monkeypatch.setattr('robot_data_studio.routes.assets.AssetRegistry', lambda: registry)
    original, _ = registry.publish(garment())
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        options = client.get(f'/assets/{original.asset_id}/appearance-options?version=1')
        assert options.status_code == 200
        assert len(options.json()['textures']) == 5
        thumbnail = client.get('/assets/garment-textures/denim')
        assert thumbnail.status_code == 200 and thumbnail.headers['content-type'] == 'image/png'
        assert thumbnail.content == b'existing image denim'
        draft = garment({'texture': 'denim', 'color': '#FFFFFF', 'roughness': .35})
        response = client.post('/assets', json={'draft': draft.model_dump(), 'expected_version': 1})
        assert response.status_code == 201
        new = response.json()['record']
        assert new['version'] == 2
        assert new['artifacts'][0]['role'] == 'visual_texture'
        assert new['artifacts'][0]['sha256'] == new['data']['appearance']['texture_sha256']
        assert client.get(f'/assets/{original.asset_id}/appearance-options?version=2').json()['appearance']['color'] == '#ffffff'
        assert 'appearance' not in registry.get(original.asset_id, 1).data
        draft.data['appearance']['color'] = 'bad'
        assert client.post('/assets', json={'draft': draft.model_dump(), 'expected_version': 2}).status_code == 422
        assert registry.get(original.asset_id).version == 2
