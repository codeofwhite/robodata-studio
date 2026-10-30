"""Generate trouser style previews; publish geometry only on explicit save."""
import json
import os
from pathlib import Path
import subprocess
from uuid import UUID, uuid4

import numpy as np
from robot_data_contracts.asset import AssetArtifact, AssetDraft, AssetReference

from ..config import settings
from .asset_service import AssetRegistry
from .cloth_run_service import newton_cloth_run_manager
from .garment_appearance import resolve_appearance, texture_artifact

SOURCE = 'clothforge-trouser-styles-v1'
SOURCES = {'trousers':SOURCE,'tshirt':'clothforge-tshirt-styles-v1','skirt':'clothforge-skirt-styles-v1'}
CONFIGS = {'trousers':'trouser_styles_v1.json','tshirt':'tshirt_styles_v1.json','skirt':'skirt_styles_v1.json'}


def options(category="trousers"):
    return json.loads((settings.clothforge_root / 'configs' / CONFIGS[category]).read_text())


def folder(preview_id,category="trousers"):
    token = UUID(preview_id).hex
    return Path(AssetRegistry().sources()[SOURCES[category]]['root']) / token


def preview(payload,category="trousers"):
    _, model, manifest, _ = newton_cloth_run_manager._selection(payload['asset_id'], payload['version'])
    if manifest['category'] != category:
        raise ValueError('请选择对应类别的衣物模型')
    spec = options(category)
    style = next((s for s in spec['styles'] if s['id'] == payload['style_id']), None)
    if style is None:
        raise ValueError('请选择已配置的衣物款式')
    parameters = {**manifest['parameters'], **style['defaults']}
    for key, value in payload['parameters'].items():
        if key not in spec['fields']:
            raise ValueError('未知衣物参数：' + key)
        field = spec['fields'][key]
        if not field['min'] <= value <= field['max']:
            raise ValueError(field['label'] + '超出调整范围')
        parameters[key] = value
    if category == 'skirt':
        parameters['hem_width_m'] = parameters['waist_width_m'] + 2 * parameters['hem_flare_m']
    preview_id = uuid4().hex
    root = folder(preview_id,category); root.mkdir(parents=True)
    config = json.loads((settings.clothforge_root / 'configs/pilot_v1.json').read_text())
    config.update(mesh_edge_m=spec['mesh_edge_m'], initial_half_depth_m=spec['initial_half_depth_m'])
    request = {'category':category,'id': category+'-' + style['id'] + '-' + preview_id, 'seed': spec['seed'],
               'style_id': style['id'], 'style_name': style['name'], 'parameters': parameters, 'config': config,
               'parent_asset_id': model.asset_id, 'parent_version': model.version}
    (root / 'request.json').write_text(json.dumps(request, ensure_ascii=False, indent=2))
    cache = root.parent / '.matplotlib'; cache.mkdir(exist_ok=True)
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'MPLCONFIGDIR': str(cache),
           'PYTHONPATH': os.pathsep.join([str(settings.clothforge_root / 'src'), str(settings.clothforge_root / 'third_party/GarmentCode')])}
    result = subprocess.run([str(settings.clothforge_root / '.venv-generation/bin/python'), '-B', '-m', 'clothforge',
                             'generate-one', '--request', str(root / 'request.json'), '--output', str(root / 'garment')],
                            cwd=settings.clothforge_root, env=env, capture_output=True, text=True, timeout=90)
    (root / 'generation.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError('衣物生成失败：' + result.stderr[-1000:])
    with np.load(root / 'garment/mesh.npz', allow_pickle=False) as data:
        uv = data['rest_triangles'][..., :2].copy()
        low, high = uv.reshape(-1, 2).min(0), uv.reshape(-1, 2).max(0)
        mesh = {'vertices': data['vertices'].tolist(), 'faces': data['faces'].tolist(), 'uv': ((uv-low)/(high-low)).tolist()}
    return {'preview_id': preview_id, 'style_id': style['id'], 'parameters': parameters, 'mesh': mesh}


def save(preview_id, appearance,category="trousers"):
    root = folder(preview_id,category); garment = root / 'garment'
    manifest = json.loads((garment / 'manifest.json').read_text())
    request = json.loads((root / 'request.json').read_text())
    registry = AssetRegistry()
    model_id = 'MDL-clothforge-' + manifest['id']
    length_label = {'trousers':'裤长','tshirt':'衣长','skirt':'裙长'}[category]
    name = manifest['style_name'] + f" · {length_label} {manifest['parameters']['length_m']*100:.0f} cm"
    def artifact(name, role):
        return AssetArtifact(source_id=SOURCES[category], path=f'{preview_id}/garment/{name}', role=role)
    entries = [artifact(n, r) for n, r in [('mesh.npz','simulation_mesh'),('manifest.json','provenance'),
        ('pattern.json','sewing_pattern'),('seams.json','seams'),('model.glb','model'),('model.obj','model_obj'),
        ('preview.png','preview'),('preview.html','interactive_preview')]]
    refs = [AssetReference(asset_id=request['parent_asset_id'], version=request['parent_version'], role='parent_geometry')]
    draft = AssetDraft(asset_id=model_id, kind='model', name=name, tags=['clothforge',category,manifest['style_id']],
        engines=['newton_vbd'], data={'category':category,'style_id':manifest['style_id'],'style_name':manifest['style_name'],
        'parameters':manifest['parameters'],'geometry_metrics':manifest['geometry_metrics'],'units':'m','seed':manifest['seed'],
        'appearance':appearance}, artifacts=entries, references=refs, change_note='保存衣物款式与真实几何')
    resolved = resolve_appearance(registry, draft)
    if resolved.get('material_id'):
        refs.append(AssetReference(asset_id=resolved['material_id'],version=resolved['material_version'],role='visual_material'))
    elif resolved['texture'] != 'none':
        entries.append(texture_artifact(registry, resolved['texture']))
    from robot_data_contracts.pbr_material import Appearance
    draft.data['appearance'] = {k:v for k,v in resolved.items() if k in Appearance.model_fields or k=='texture_sha256'}
    draft.references=refs; draft.artifacts=entries
    # Material configs use the existing naming and geometry-reference contract.
    drafts = [draft]
    for material in ['light','medium','heavy']:
        config = json.loads((garment / f'config-{material}.json').read_text())
        drafts.append(AssetDraft(asset_id=f"CFG-clothforge-{manifest['id']}-{material}",kind='config',name=name+' / '+material,
            tags=['clothforge',category,manifest['style_id']],engines=['newton_vbd'],data={'parameters':config},
            artifacts=[artifact(f'config-{material}.json','configuration')], references=[
                AssetReference(asset_id=model_id,version=1,role='geometry'),
                AssetReference(asset_id='MAT-clothforge-'+material,version=1,role='material')],change_note='保存款式材料配置'))
    for item in drafts:
        item.artifacts=[registry.inspect_artifact(a) for a in item.artifacts]
    for item in drafts:
        record,_=registry.publish(item,expected_version=0,idempotent=True)
        if item.kind=='model':model=record
    return {'record':model.model_dump(mode='json')}
