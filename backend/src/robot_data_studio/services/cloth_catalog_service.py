"""Read completed and diagnostic cloth runs without executing task code."""
from pathlib import Path
import json
import sqlite3
from ..config import settings
from .asset_service import AssetRegistry, is_video_artifact

BATCHES = ('tabletop_v2', 'folding_v3', 'fixtures_v4')

def root():
    return (settings.data_root / 'expert_demos/curobo-cloth-v1').resolve()

def run_path(batch, relative):
    if batch not in BATCHES:
        raise ValueError('unknown cloth batch')
    base = root() / batch
    path = (base / relative).resolve()
    if not path.is_relative_to(base) or len(path.relative_to(base).parts) != 5 or path.relative_to(base).parts[0] != 'tasks' or path.parent.name != 'runs':
        raise ValueError('invalid cloth run path')
    return path

def read(path):
    return json.loads(path.read_text()) if path.is_file() else {}

def catalog():
    registry = AssetRegistry()
    indexed = {}
    if settings.db_path.is_file():
        with sqlite3.connect('file:' + str(settings.db_path) + '?mode=ro', uri=True) as db:
            indexed = {r[0]: {'id': r[1], 'qa_status': r[2]} for r in db.execute('SELECT episode_uuid,id,qa_status FROM episodes')}
    tasks, issues = [], []
    for batch in BATCHES:
        try:
            manifest = read(root() / batch / 'manifest.json')
        except (OSError, ValueError) as e:
            issues.append({'batch': batch, 'error': str(e)}); continue
        for task in manifest.get('tasks', []):
            attempts = []
            for item in task.get('attempts', []):
                try:
                    path = run_path(batch, item['path'])
                    evaluation = read(path / 'evaluation.json')
                    delivery = read(path / 'delivery_verification.json')
                    episodes = [read(p) for p in sorted(path.glob('episodes/episode_*/manifest.json'))]
                    record = registry.get(item['asset_id']) if item.get('registered') and item.get('asset_id') else None
                    media = []
                    if record:
                        for i, a in enumerate(record.artifacts):
                            is_video = is_video_artifact(a.role, a.path)
                            if is_video or a.role == 'preview':
                                media.append({'role':'video' if is_video else a.role,'label':a.role,'path':a.path,'url':f'/assets/{record.asset_id}/versions/{record.version}/artifacts/{i}'})
                    attempts.append({**item, 'batch': batch, 'numeric_success': evaluation.get('success'),
                        'delivery_passed': delivery.get('passed') is True,
                        'failed_gates': evaluation.get('failed_gates', item.get('failed_gates', [])),
                        'media': media, 'episodes': [{'uuid':e.get('episode_uuid'), 'fps': e.get('fps'), **indexed.get(e.get('episode_uuid'), {'id':None,'qa_status':'not_indexed'})} for e in episodes],
                        'importable': bool(record and delivery.get('passed') is True and evaluation.get('success') is True and episodes),
                        'assisted_grasp': manifest.get('assisted_grasp', True), 'runnable': False})
                except (OSError, ValueError, KeyError) as e:
                    attempts.append({**item,'batch':batch,'error':str(e),'importable':False,'media':[],'episodes':[]})
            tasks.append({'batch':batch,'task':task['task'],'name':task['name'],'variant':task['variant'],'attempts':attempts})
    return {'tasks':tasks,'issues':issues,'summary':{'delivered':sum(a.get('delivery_passed',False) for t in tasks for a in t['attempts']),
        'indexed':sum(e['id'] is not None for t in tasks for a in t['attempts'] for e in a['episodes'])}}
