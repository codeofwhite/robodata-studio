"""Orchestrate recorded Genesis cloth states through the Isaac rendering worker."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import threading
from uuid import uuid4

from ..config import PROJECT_ROOT, settings
from ..db import transaction
from ..models import SessionCreate
from .episode_scanner import episode_detail, list_episodes, scan_session
from .session_service import create_session, get_session, list_sessions

_lock = threading.Lock()
SCENE = 'curobo_cloth_replay'


def modules():
    source = str(settings.generation_root / 'src')
    if source not in sys.path:
        sys.path.append(source)
    from robot_data_generation import cloth_appearance
    return cloth_appearance


def _source(episode_id):
    item = episode_detail(episode_id)
    if not item or item['qa_status'] == 'rejected':
        raise ValueError('衣物源 Episode 不存在或已被拒绝')
    manifest = item['manifest']
    raw = manifest.get('scene', {}).get('parameters', {}).get('source_demo_trajectory')
    if not raw:
        raise ValueError('请选择带有原生 cuRobo 记录的衣物 Episode')
    run = Path(raw).resolve().parent
    allowed = settings.cloth_expert_root.resolve()
    if not run.is_relative_to(allowed) or '/garment_' not in run.as_posix():
        raise ValueError('首版仅支持本地已交付的 cuRobo 衣物任务')
    snapshot = modules().source_snapshot(run, Path(item['path']))
    return item, {**snapshot, 'episode_id': episode_id}


def sources():
    result, unavailable = [], []
    for item in list_episodes(engine_id='genesis'):
        if 'garment_' not in item['scene_id'] or item['control_source'] != 'scripted_curobo_physics':
            continue
        try:
            detail, _ = _source(item['id'])
            result.append({key: detail[key] for key in ('id', 'episode_uuid', 'task', 'num_frames', 'qa_status')})
        except (OSError, ValueError, KeyError) as error:
            unavailable.append({'id': item['id'], 'reason': str(error)})
    return {'items': result, 'unavailable': unavailable}


def plan_directory(plan_id):
    if not re.fullmatch(r'[0-9a-f]{32}', plan_id):
        raise ValueError('invalid cloth generation plan ID')
    return settings.data_root / 'cloth_generation' / plan_id


def preview(payload):
    ids = payload['episode_ids']
    if len(ids) != len(set(ids)):
        raise ValueError('源 Episode 不能重复')
    plan_id = uuid4().hex
    planner = modules()
    from .pbr_material_service import resolve
    from .surface_appearance import resolve_environment
    appearances = [{**resolve({k: v for k, v in raw.items() if k not in {'environment', 'camera_lighting'}}),
                    'environment': resolve_environment(raw.get('environment')),
                    'camera_lighting': raw.get('camera_lighting')} for raw in payload['appearances']]
    plan = planner.build_plan(plan_id, [_source(i)[1] for i in ids], appearances,
                              PROJECT_ROOT / 'assets/sources/robot-cloth-scenes-v1/textures')
    root = plan_directory(plan_id)
    root.mkdir(parents=True)
    planner.write_json(root / 'plan.json', plan)
    planner.write_json(root / 'metadata.json', {'plan_sha256': planner.digest(root / 'plan.json')})
    return get_plan(plan_id)


def get_plan(plan_id, *, check_sources=False):
    root = plan_directory(plan_id)
    planner = modules()
    if planner.digest(root / 'plan.json') != json.loads((root / 'metadata.json').read_text())['plan_sha256']:
        raise ValueError('衣物计划在预览后已变化')
    plan = json.loads((root / 'plan.json').read_text())
    planner.validate_plan(plan, check_sources=check_sources)
    if check_sources:
        for source in plan['sources']:
            item = episode_detail(source['episode_id'])
            if not item or item['qa_status'] == 'rejected' or item['episode_uuid'] != source['episode_uuid']:
                raise ValueError('衣物源示范已被拒绝或替换')
    return {'plan_id': plan_id, 'plan': plan, 'total_attempts': len(plan['attempts'])}


def validate_session(config):
    if config['scene_id'] != SCENE or config['control_mode'] != 'scripted':
        raise ValueError('衣物外观计划只能用于 scripted 录制状态重渲染')
    snapshot = get_plan(config['cloth_generation_plan_id'], check_sources=True)
    if config['target_episodes'] != snapshot['total_attempts']:
        raise ValueError('衣物批次数量与计划不匹配')


def report_for(session):
    root = Path(session['config']['episode_root'])
    plan_id = session['config']['cloth_generation_plan_id']
    snapshot = get_plan(plan_id)
    path = root / 'cloth_generation_report.json'
    if not path.exists():
        return None
    report = json.loads(path.read_text())
    if report['plan_id'] != plan_id or report['plan_sha256'] != modules().digest(plan_directory(plan_id) / 'plan.json'):
        raise ValueError('衣物批次报告与计划不匹配')
    ids = [row['attempt_id'] for row in report['results']]
    allowed = {row['attempt_id'] for row in snapshot['plan']['attempts']}
    if len(set(ids)) != len(ids) or not set(ids).issubset(allowed):
        raise ValueError('衣物报告包含重复或未知尝试')
    return report


def start(plan_id, payload):
    from .worker_manager import worker_manager
    snapshot = get_plan(plan_id, check_sources=True)
    with _lock:
        session = next((s for s in list_sessions() if s['config'].get('cloth_generation_plan_id') == plan_id), None)
        if session is None:
            session = create_session(SessionCreate(engine_id='isaac_sim', dataset_name=payload['dataset_name'],
                scene_id=SCENE, control_mode='scripted', cloth_generation_plan_id=plan_id,
                target_episodes=snapshot['total_attempts'], gpu=payload['gpu'], control_fps=10, width=960, height=960))
            with transaction() as connection:
                connection.execute('UPDATE sessions SET collector_url = NULL WHERE id = ?', (session['id'],))
        elif session['dataset_name'] != payload['dataset_name'] or session['config']['gpu'] != payload['gpu']:
            raise ValueError('该衣物计划已绑定会话，请重新预览以更改 GPU 或数据集')
        report = report_for(session)
        if report and report['status'] == 'completed':
            raise ValueError('衣物批次已完成，请创建新计划')
        worker_manager.start(session['id'])
    return job(session['id'])


def job(session_id):
    from .worker_manager import worker_manager
    session = get_session(session_id)
    if not session:
        raise KeyError(session_id)
    if not session['config'].get('cloth_generation_plan_id'):
        raise ValueError('not a cloth generation session')
    snapshot = get_plan(session['config']['cloth_generation_plan_id'])
    # Observe process completion before reading its final atomic report. Reading
    # in the opposite order can return a stopped worker with a stale 1/2 count.
    worker = worker_manager.status(session_id)
    report = report_for(session)
    episodes = {Path(e['path']).resolve(): e for e in list_episodes(session_id=session_id)}
    rows = []
    for row in report['results'] if report else []:
        item = episodes.get(Path(row['episode_path']).resolve()) if row['episode_path'] else None
        rows.append({**row, 'episode_id': item['id'] if item else None, 'qa_status': item['qa_status'] if item else None})
    log = Path(session['config']['episode_root']) / 'collector.log'
    progress = None
    if log.is_file():
        matches = list(re.finditer(r'(PBR_PROGRESS|RENDER_PROGRESS)\s+(\d+)\s+(\d+)', log.read_text(errors='replace')))
        if matches:
            last = matches[-1]
            progress = {'stage': 'render' if last[1] == 'PBR_PROGRESS' else 'export',
                        'frame': int(last[2]) + 1, 'total_frames': int(last[3])}
    return {'session': session, 'worker': worker, 'plan_id': snapshot['plan_id'],
            'total': snapshot['total_attempts'], 'completed': len(rows),
            'succeeded': sum(r['status'] == 'succeeded' for r in rows), 'results': rows,
            'frame_progress': progress,
            'report_status': report['status'] if report else None}


def jobs():
    return [job(s['id']) for s in list_sessions() if s['config'].get('cloth_generation_plan_id')]


def scan(session_id):
    job(session_id)
    return scan_session(session_id)
