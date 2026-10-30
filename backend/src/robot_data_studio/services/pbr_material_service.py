"""Local, immutable three-map fabric materials in the existing asset registry."""
import struct
from pathlib import Path
from uuid import uuid4

from robot_data_contracts.asset import AssetArtifact, AssetDraft
from robot_data_contracts.pbr_material import Appearance
from .asset_service import AssetRegistry
from ..config import settings

ROLES = ('base_color', 'normal', 'roughness')
SOURCE = 'cc0-fabrics-v1'


def png_dimensions(content):
    if len(content) < 33 or content[:8] != b'\x89PNG\r\n\x1a\n' or content[12:16] != b'IHDR':
        raise ValueError('请选择 PNG 贴图')
    width, height = struct.unpack('>II', content[16:24])
    if not 1 <= width <= 8192 or not 1 <= height <= 8192 or len(content) > 32*1024*1024:
        raise ValueError('贴图最大为 8192×8192、32 MB')
    return [width, height]


def import_material(name, images, *, origin='', license_name='CC0-1.0', asset_id=None, registry=None, category='fabric'):
    registry = registry or AssetRegistry()
    if category not in ('fabric', 'tabletop', 'background'):
        raise ValueError('未知材质分类')
    source_id = SOURCE if category == 'fabric' else 'cc0-surfaces-v1'
    if set(images) != set(ROLES):
        raise ValueError('需要 BaseColor、OpenGL Normal 和 Roughness 三张贴图')
    dimensions = {role: png_dimensions(content) for role, content in images.items()}
    if len({tuple(size) for size in dimensions.values()}) != 1:
        raise ValueError('三张贴图分辨率需要一致')
    if not name.strip() or len(name) > 200:
        raise ValueError('请填写材质名称（最多 200 字符）')
    asset_id = asset_id or 'MAT-local-' + category + '-' + uuid4().hex[:12]
    # Each import owns a new immutable payload directory, including reimports.
    root = Path(registry.sources()[source_id]['root'])
    relative = Path(uuid4().hex)
    directory = root / relative
    directory.mkdir(parents=True)
    artifacts = []
    for role, content in images.items():
        (directory / (role + '.png')).write_bytes(content)
        artifacts.append(AssetArtifact(source_id=source_id, path=(relative / (role + '.png')).as_posix(), role='pbr_' + role))
    draft = AssetDraft(asset_id=asset_id, kind='material', name=name,
        description='表面 PBR 外观材质；物理材料参数另行配置。', tags=['pbr', category], engines=['isaac_sim'],
        data={'pbr_schema_version': 1, 'category': category, 'license': license_name, 'origin': origin,
              'normal_convention': 'OpenGL', 'dimensions_px': dimensions['base_color'],
              'color_space': {'base_color': 'sRGB', 'normal': 'raw', 'roughness': 'raw'}},
        artifacts=artifacts, change_note='导入三贴图 PBR 材质')
    record, created = registry.publish(draft)
    return describe(record, registry)


def describe(record, registry):
    if record.kind != 'material' or record.data.get('pbr_schema_version') != 1:
        raise ValueError('请选择 PBR 材质资产')
    entries = {a.role.removeprefix('pbr_'): a for a in record.artifacts if a.role.startswith('pbr_')}
    if set(entries) != set(ROLES):
        raise ValueError('材质缺少必需贴图')
    maps = {role: {'artifact': registry.inspect_artifact(a).model_dump(),
                   'url': f'/pbr-materials/{record.asset_id}/maps/{role}?version={record.version}'} for role, a in entries.items()}
    return {'asset_id': record.asset_id, 'version': record.version, 'name': record.name,
            'data': {**record.data, 'category': record.data.get('category', 'fabric')}, 'maps': maps}


def catalog():
    registry = AssetRegistry()
    latest = {}
    for record in registry.all():
        if record.kind == 'material' and record.data.get('pbr_schema_version') == 1:
            latest[record.asset_id] = record
    return [describe(record, registry) for record in latest.values()]


def resolve(raw, registry=None):
    request = Appearance.model_validate(raw).model_dump()
    if not request['material_id']:
        return request
    registry = registry or AssetRegistry()
    record = registry.get(request['material_id'], request['material_version'])
    described = describe(record, registry)
    maps = {}
    for role, entry in described['maps'].items():
        artifact = AssetArtifact.model_validate(entry['artifact'])
        maps[role] = {'path': str(registry.artifact_path(artifact)), 'sha256': artifact.sha256}
    return {**request, 'maps': maps, 'material_content_sha256': record.content_sha256,
            'material_origin': record.data['origin'], 'material_license': record.data['license']}
