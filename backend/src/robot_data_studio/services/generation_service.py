"""Studio orchestration for the existing rigid-cube generation planner."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
import uuid
from pathlib import Path

from ..config import settings
from ..db import transaction
from ..models import SessionCreate
from .episode_scanner import episode_detail, list_episodes, scan_session
from .session_service import create_session, get_session, list_sessions
from .worker_runtime import write_json_atomic

_lock = threading.Lock()


def generation_modules():
    source = settings.generation_root / 'src'
    if not (source / 'robot_data_generation').is_dir():
        raise ValueError(f'robot-data-generation source unavailable: {source}')
    if str(source) not in sys.path:
        sys.path.append(str(source))
    from robot_data_generation import generation_plan, models, source_episode
    return generation_plan, models, source_episode


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _source(episode_id):
    item = episode_detail(episode_id)
    if item is None:
        raise ValueError(f'源 Episode 不存在：{episode_id}')
    session = get_session(item['session_id'])
    if not session or session['status'] == 'trashed' or item['qa_status'] != 'accepted' or item['engine_id'] != 'isaac_sim':
        raise ValueError(f'源 Episode 必须是已审核通过的 Isaac 示范：{episode_id}')
    _, models, loader = generation_modules()
    ref = models.SourceEpisodeRefV1(path=item['path'], episode_uuid=item['episode_uuid'])
    trajectory = loader.load_source_trajectory(ref)
    root = Path(item['path'])
    identity = {'episode_id': episode_id, 'episode_uuid': ref.episode_uuid,
                'manifest_sha256': _digest(root / 'manifest.json'), 'trajectory_sha256': _digest(root / 'trajectory.npz')}
    return item, ref, trajectory, identity


def sources():
    available, unavailable = [], []
    for item in list_episodes(qa_status='accepted', engine_id='isaac_sim'):
        if item['scene_id'] != 'rigid_cube_lift':
            continue
        try:
            detail, _, trajectory, _ = _source(item['id'])
            available.append({'id': item['id'], 'episode_uuid': item['episode_uuid'], 'task': item['task'],
                'session_id': item['session_id'], 'num_frames': trajectory.length,
                'close_frame': trajectory.phases.close_frame, 'lift_frame': trajectory.phases.lift_frame})
        except (OSError, ValueError, KeyError) as error:
            unavailable.append({'id': item['id'], 'reason': str(error)})
    return {'items': available, 'unavailable': unavailable}


def plan_directory(plan_id):
    if not re.fullmatch(r'[0-9a-f]{32}', plan_id):
        raise ValueError('invalid generation plan ID')
    return settings.data_root / 'generation' / plan_id


def preview(payload):
    planner, models, _ = generation_modules()
    ids = payload['episode_ids']
    if len(set(ids)) != len(ids):
        raise ValueError('源 Episode 不能重复')
    selected = [_source(i) for i in ids]
    plan_id = uuid.uuid4().hex
    config = models.RigidCubeLiftConfigV1(spec_id='studio_cube_' + plan_id,
        attempts_per_source=payload['attempts_per_source'], randomization_seed=payload['seed'],
        transition_frames=10, object_xy={'range_m': payload['range_m']},
        sources=tuple(item[1] for item in selected))
    plan = planner.build_nominal_plan(config) if payload['mode'] == 'nominal' else planner.build_generation_plan(config)
    root = plan_directory(plan_id)
    root.mkdir(parents=True)
    planner.write_json_atomic(root / 'config.json', config)
    planner.write_json_atomic(root / 'plan.json', plan)
    write_json_atomic(root / 'metadata.json', {'plan_id': plan_id, 'request': payload,
        'sources': [item[3] for item in selected], 'plan_sha256': _digest(root / 'plan.json')})
    return get_plan(plan_id)


def get_plan(plan_id):
    root = plan_directory(plan_id)
    metadata = json.loads((root / 'metadata.json').read_text())
    if _digest(root / 'plan.json') != metadata['plan_sha256']:
        raise ValueError('generation plan changed after preview')
    planner, _, _ = generation_modules()
    plan = planner.load_generation_plan(root / 'plan.json')
    return {**metadata, 'plan': plan.model_dump(mode='json'), 'total_attempts': len(plan.attempts)}


def validate_sources(plan_id):
    snapshot = get_plan(plan_id)
    for identity in snapshot['sources']:
        *_, current = _source(identity['episode_id'])
        if current != identity:
            raise ValueError('源示范在计划预览后已变化，请重新预览')
    return snapshot


def generation_session(config):
    plan_id = config.get('generation_plan_id')
    if not plan_id:
        return None
    if config['scene_id'] != 'rigid_cube_lift' or config['control_mode'] != 'scripted' or config.get('physics_backend') != 'physx':
        raise ValueError('generation requires scripted Isaac rigid_cube_lift with PhysX')
    snapshot = validate_sources(plan_id)
    if config['control_fps'] != snapshot['plan']['execution']['control_hz'] or config['target_episodes'] != snapshot['total_attempts']:
        raise ValueError('session execution settings differ from generation plan')
    return snapshot


def report_for(session):
    plan_id = session['config'].get('generation_plan_id')
    if not plan_id:
        raise ValueError('not a generation session')
    get_plan(plan_id)
    planner, _, _ = generation_modules()
    path = Path(session['config']['episode_root']) / 'generation_batch_report.json'
    if not path.exists():
        return None
    return planner.load_batch_report(path, plan=planner.load_generation_plan(plan_directory(plan_id) / 'plan.json')).model_dump(mode='json')


def start(plan_id, payload):
    from .worker_manager import worker_manager
    snapshot = validate_sources(plan_id)
    with _lock:
        session = next((s for s in list_sessions() if s['config'].get('generation_plan_id') == plan_id), None)
        if session is None:
            session = create_session(SessionCreate(engine_id='isaac_sim', dataset_name=payload['dataset_name'],
                scene_id='rigid_cube_lift', control_mode='scripted', generation_plan_id=plan_id,
                target_episodes=snapshot['total_attempts'], gpu=payload['gpu'], control_fps=20,
                camera_profile_id='lab_d435i_dual_v1', renderer_profile_id='isaac_performance_v1', physics_backend='physx'))
            with transaction() as connection:
                connection.execute('UPDATE sessions SET collector_url = NULL WHERE id = ?', (session['id'],))
        elif session['dataset_name'] != payload['dataset_name'] or session['config']['gpu'] != payload['gpu']:
            raise ValueError('该计划已绑定会话；修改数据集或 GPU 请重新预览计划')
        report = report_for(session)
        if report and report['status'] == 'completed':
            raise ValueError('批次已完成；重新执行请创建新计划')
        worker_manager.start(session['id'])
    return job(session['id'])


def job(session_id):
    from .worker_manager import worker_manager
    session = get_session(session_id)
    if session is None:
        raise KeyError(session_id)
    if not session['config'].get('generation_plan_id'):
        raise ValueError('not a generation session')
    report = report_for(session)
    results = report['results'] if report else []
    plan = get_plan(session['config']['generation_plan_id'])
    succeeded = sum(r['status'] == 'succeeded' for r in results)
    gate = (succeeded == len(results) if plan['plan']['nominal_only'] else succeeded * 2 >= plan['total_attempts']) if report and report['status'] == 'completed' else None
    episodes = {Path(e['path']).resolve(): e for e in list_episodes(session_id=session_id)}
    attempts = {a['attempt_id']: a for a in plan['plan']['attempts']}
    linked = []
    for result in results:
        entry = episodes.get(Path(result['episode_path']).resolve()) if result.get('episode_path') else None
        linked.append({**result, 'offset_m': attempts[result['attempt_id']]['object_xy_offset_m'],
            'source_episode_uuid': attempts[result['attempt_id']]['source_episode_uuid'],
            'episode_id': entry['id'] if entry else None, 'qa_status': entry['qa_status'] if entry else None})
    return {'session': session, 'worker': worker_manager.status(session_id), 'plan_id': plan['plan_id'],
        'total': plan['total_attempts'], 'completed': len(results), 'succeeded': succeeded,
        'failed': len(results) - succeeded, 'gate_passed': gate, 'report_status': report['status'] if report else None,
        'results': linked, 'log_path': str(Path(session['config']['episode_root']) / 'collector.log')}


def jobs():
    return [job(s['id']) for s in list_sessions() if s['config'].get('generation_plan_id')]


def scan(session_id):
    session = get_session(session_id)
    if not session:
        raise KeyError(session_id)
    report_for(session)
    return scan_session(session_id)
