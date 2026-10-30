"""Managed, source-preserving Isaac rendering of canonical Genesis Episodes."""
from pathlib import Path
import hashlib
import json
import threading

import numpy as np
from robot_data_contracts.validation import inspect_episode
from ..config import settings
from ..db import transaction
from ..models import SessionCreate
from .episode_scanner import episode_detail, list_episodes, scan_session
from .session_service import create_session, get_session, list_sessions


_index_lock = threading.Lock()

def source(episode_id):
    item = episode_detail(episode_id)
    if not item or item['engine_id'] != 'genesis':
        raise ValueError('请选择 Genesis 原生采集的 Episode')
    if item['qa_status'] == 'rejected':
        raise ValueError('已拒绝的 Episode 不用于渲染')
    root = Path(item['path'])
    episode = inspect_episode(root / 'manifest.json', engine_id='genesis')
    manifest = episode.manifest
    replay = manifest['scene']['parameters'].get('offline_replay')
    if not replay or replay.get('format_version') != 1:
        raise ValueError('缺少离线重建信息，请使用更新后的单臂 Genesis 原生采集器重新采集')
    if manifest['lineage']['generation_method'] == 'visual_rerender':
        raise ValueError('请选择原始采集 Episode，而非已渲染的派生数据')
    if manifest['robot_id'] != 'franka_panda':
        raise ValueError('首轮离线渲染仅支持单臂 Franka')
    with np.load(root / 'trajectory.npz', allow_pickle=False) as z:
        required = {'native_state','robot_link_poses'} | {c['pose_array'] for c in replay['cameras'].values()}
        required.add('cloth_particles' if 'cloth' in replay else 'object_pose')
        if required - set(z.files):
            raise ValueError('缺少重放状态：' + ', '.join(sorted(required-set(z.files))))
        for name in required:
            if len(z[name]) != episode.num_frames or not np.isfinite(z[name]).all():
                raise ValueError('重放状态长度或有限性错误：'+name)
        if 'cloth' in replay:
            faces = np.asarray(replay['cloth']['faces'])
            if z['cloth_particles'].shape[1:] != (replay['cloth']['num_vertices'],3) or faces.ndim!=2 or faces.shape[1]!=3 or faces.min()<0 or faces.max()>=replay['cloth']['num_vertices']:
                raise ValueError('衣物拓扑与逐帧顶点不匹配')
    hashes = {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ['manifest.json','trajectory.npz']}
    return {**item, "fps": manifest["fps"], "manifest": manifest}, replay, hashes


def availability(episode_id):
    try:
        item, replay, _ = source(episode_id)
        return {'available':True, 'reason':None, 'frames':item['num_frames'],
                'physics_backend':replay['physics_backend']}
    except (OSError, ValueError, KeyError) as error:
        return {'available':False, 'reason':str(error)}


def validate_job(config):
    item, _, hashes = source(config['isaac_episode_source_id'])
    if hashes != config['isaac_episode_source_hashes']:
        raise ValueError('源 Episode 在创建渲染任务后发生变化')
    return item


def start(episode_id, gpu):
    from .worker_manager import worker_manager
    item, replay, hashes = source(episode_id)
    original = get_session(item['session_id'])
    # Reuse managed sessions and GPU leases; no new queue or database schema.
    payload = SessionCreate(engine_id='genesis', dataset_name=(original['dataset_name'][:65]+'_isaac'),
        scene_id=item['scene_id'], control_mode='keyboard', target_episodes=1, gpu=gpu,
        control_fps=item['fps'], sim_dt=original['config'].get('sim_dt',.01),
        physics_steps_per_control=original['config'].get('physics_steps_per_control',10),
        width=replay['cameras']['base']['resolution'][0],height=replay['cameras']['base']['resolution'][1],
        camera_profile_id=original['config'].get('camera_profile_id','lab_d435i_dual_v1'),
        scene_params=original['config'].get('scene_params',{}))
    session = create_session(payload)
    config = {**session['config'], 'isaac_episode_source_id':episode_id,
              'isaac_episode_source_hashes':hashes,'control_mode':'scripted'}
    with transaction() as db:
        db.execute("UPDATE sessions SET config_json=?, control_mode='scripted', collector_url=NULL WHERE id=?",
                   (json.dumps(config),session['id']))
    worker_manager.start(session['id'])
    return job(session['id'])


def jobs(episode_id):
    return [job(s['id']) for s in list_sessions()
            if s['config'].get('isaac_episode_source_id') == episode_id]


def job(session_id):
    from .worker_manager import worker_manager
    session = get_session(session_id)
    if not session or 'isaac_episode_source_id' not in session['config']:
        raise KeyError(session_id)
    worker = worker_manager.status(session_id)
    root = Path(session['config']['episode_root'])
    progress_path, result_path = root/'progress.json', root/'render-result.json'
    result = json.loads(result_path.read_text()) if result_path.is_file() else None
    progress = json.loads(progress_path.read_text()) if progress_path.is_file() else None
    if result and result['status']=='completed':
        validate_job(session['config'])
        # Browser polling and status clients can observe completion concurrently.
        # Index once under a lock instead of racing the scanner's read/insert pair.
        with _index_lock:
            if not list_episodes(session_id=session_id):
                scan_session(session_id)
    episodes = list_episodes(session_id=session_id)
    status = result['status'] if result else worker['status']
    if status=='stopped' and not result:
        status='failed'
    return {'session_id':session_id,'source_episode_id':session['config']['isaac_episode_source_id'],
            'status':status,'worker':worker,'progress':progress,'result':result,
            'episode_id':episodes[0]['id'] if episodes else None,
            'error':result.get('error') if result else worker.get('error'),
            'log_path':str(root/'collector.log')}
