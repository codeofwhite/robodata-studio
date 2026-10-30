"""Register explicit ClothForge conversions with immutable dataset provenance."""
import json
from pathlib import Path

from robot_data_contracts.asset import AssetArtifact, AssetDraft, AssetReference
from .asset_service import AssetRegistry

SOURCE = 'garmentcodedata-v2-phase2'


def import_converted(registry=None):
    registry = registry or AssetRegistry()
    root = Path(registry.sources()[SOURCE]['root'])
    report = json.loads((root/'conversion_report.json').read_text())
    created = unchanged = 0
    imported = []
    for row in report['results']:
        if row['status'] != 'converted' or not row['runnable'] or row['sample_id'] not in report['config']['registration_samples']:
            continue
        folder = root/'garments'/row['sample_id']
        manifest = json.loads((folder/'manifest.json').read_text())
        mid = 'MDL-clothforge-'+manifest['id']
        def artifact(name, role):
            return registry.inspect_artifact(AssetArtifact(source_id=SOURCE,
                path=f"garments/{row['sample_id']}/{name}",role=role))
        entries = [artifact(n,r) for n,r in [('mesh.npz','simulation_mesh'),('manifest.json','provenance'),
                   ('pattern.json','sewing_pattern'),('seams.json','seams'),('model.glb','model'),
                   ('model.obj','model_obj'),('preview.png','preview'),('preview.html','interactive_preview')]]
        drafts = [AssetDraft(asset_id=mid,kind='model',name=manifest['name'],
            description='GarmentCodeData v2 源版片经 ClothForge 重建；来源 PLY 保留，物理运行单独记录。',
            tags=['clothforge','garmentcodedata','v2',manifest['category']],engines=['newton_vbd'],
            data={'category':manifest['category'],'parameters':manifest['parameters'],
                  'geometry_metrics':manifest['geometry_metrics'],'units':'m','seed':manifest['seed'],
                  'provenance':manifest['provenance'],'parameter_semantics':manifest['parameter_semantics'],'supports_style_editing':False,
                  'physical_validation':'not_run'},artifacts=entries,
            change_note='导入 GarmentCodeData 重建几何，保留原设计结构与转换来源')]
        for material in ['light','medium','heavy']:
            cid=f"CFG-clothforge-{manifest['id']}-{material}"
            config=json.loads((folder/f'config-{material}.json').read_text())
            drafts.append(AssetDraft(asset_id=cid,kind='config',name=manifest['name']+' / '+material,
                tags=['clothforge','garmentcodedata',manifest['category']],engines=['newton_vbd'],
                data={'parameters':config},artifacts=[artifact(f'config-{material}.json','configuration')],
                references=[AssetReference(asset_id=mid,version=1,role='geometry'),
                            AssetReference(asset_id='MAT-clothforge-'+material,version=1,role='material')],
                change_note='导入转换衣物的已有合成材料配置，未映射上游材料') )
        for draft in drafts:
            _,changed=registry.publish(draft,expected_version=0,idempotent=True)
            created+=int(changed);unchanged+=int(not changed)
        imported.append({'sample_id':row['sample_id'],'asset_id':mid,'version':1,'category':manifest['category']})
    return {'created':created,'unchanged':unchanged,'models':imported}
