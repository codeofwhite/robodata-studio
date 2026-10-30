"""Index immutable completed demonstrations; never grant training QA automatically."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from robot_data_contracts.validation import inspect_episode
from ..config import settings
from ..db import transaction
from .asset_service import AssetRegistry, file_digest
from .cloth_catalog_service import catalog, run_path, read

def import_completed(batch=None, run_id=None, dry_run=False):
    candidates = [a for t in catalog()['tasks'] for a in t['attempts'] if a.get('importable') and (batch is None or a['batch']==batch) and (run_id is None or a['run_id']==run_id)]
    prepared, errors = [], []
    registry = AssetRegistry()
    for a in candidates:
        try:
            path = run_path(a['batch'],a['path'])
            record = registry.get(a['asset_id'])
            if registry.integrity(record)['status'] != 'current': raise ValueError('registered evidence is stale')
            delivery = read(path/'delivery_verification.json')
            if file_digest(path/'trajectory.npz') != delivery['trajectory_sha256']: raise ValueError('source trajectory changed')
            for p in sorted(path.glob('episodes/episode_*/manifest.json')):
                if not p.resolve().is_relative_to(path): raise ValueError('episode escapes approved source')
                episode = inspect_episode(p,engine_id='genesis')
                source = episode.manifest.get('scene',{}).get('parameters',{})
                if source.get('source_sha256') != delivery['trajectory_sha256']: raise ValueError('episode source mismatch')
                prepared.append((a,path,p,episode))
        except (OSError, ValueError, KeyError) as e:
            errors.append({'run_id':a['run_id'],'error':str(e)})
    if errors: return {'indexed':0,'skipped':0,'eligible':len(prepared),'errors':errors,'dry_run':dry_run}
    if dry_run: return {'indexed':0,'skipped':0,'eligible':len(prepared),'errors':[],'dry_run':True}
    # Consistent backup via SQLite API includes WAL state, unlike copying studio.db.
    backup_root=settings.data_root/'cloth_unification_v1'/'db_backups';backup_root.mkdir(parents=True,exist_ok=True)
    now=datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(settings.db_path)) as src, sqlite3.connect(backup_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.db')) as dst: src.backup(dst)
    indexed=skipped=0
    with transaction() as db:
        project=db.execute("SELECT id FROM projects WHERE name='local'").fetchone()
        project_id=project['id'] if project else db.execute('INSERT INTO projects(name,root_path,created_at) VALUES (?,?,?)',('local',str(settings.data_root),now)).lastrowid
        for a,path,p,e in prepared:
            exists=db.execute('SELECT path FROM episodes WHERE episode_uuid=?',(e.episode_uuid,)).fetchone()
            if exists:
                if exists['path']!=str(p.parent.resolve()):raise ValueError('episode UUID is already indexed at another path')
                skipped+=1;continue
            dsroot=str((settings.data_root/'datasets'/('cloth_'+a['batch'])).resolve())
            db.execute('INSERT OR IGNORE INTO datasets(project_id,name,root_path,created_at) VALUES (?,?,?,?)',(project_id,'cloth_'+a['batch'],dsroot,now))
            did=db.execute('SELECT id FROM datasets WHERE root_path=?',(dsroot,)).fetchone()['id']
            sid='cloth_import_'+hashlib.sha256(str(path).encode()).hexdigest()[:24]
            config={'episode_root':str(path/'episodes'),'imported_read_only':True,'source_run':a['run_id'],'source_batch':a['batch'],'assisted_grasp':True,'engine_id':'genesis'}
            db.execute("INSERT OR IGNORE INTO sessions(id,dataset_id,adapter_id,scene_id,control_mode,status,target_episodes,config_json,created_at,updated_at) VALUES (?,?,?,?,?,'stopped',?,?,?,?)",(sid,did,'genesis',e.task,'imported',len(list(path.glob('episodes/episode_*/manifest.json'))),json.dumps(config),now,now))
            db.execute("INSERT INTO episodes(session_id,episode_uuid,path,task,operator_success,auto_success,qa_status,failure_reason,num_frames,manifest_json,created_at,indexed_at) VALUES (?,?,?,?,?,?,'pending',?,?,?,?,?)",(sid,e.episode_uuid,str(p.parent.resolve()),e.task,e.operator_success,e.auto_success,e.failure_reason,e.num_frames,json.dumps(e.manifest),e.created_at,now))
            indexed+=1
    return {'indexed':indexed,'skipped':skipped,'eligible':len(prepared),'errors':[],'dry_run':False}
