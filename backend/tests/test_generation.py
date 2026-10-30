import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from robot_data_studio.adapters.isaac_sim import IsaacSimAdapter
from robot_data_studio.routes.generation import router
from robot_data_studio.services import generation_service as service
from robot_data_studio.services.session_service import get_session
from robot_data_studio.services.worker_manager import worker_manager


@pytest.fixture
def source(isolated_settings, tmp_path, monkeypatch):
    root = tmp_path / 'accepted-source'
    root.mkdir()
    (root / 'manifest.json').write_text('{}')
    (root / 'trajectory.npz').write_bytes(b'immutable trajectory')
    item = dict(id=1, session_id='original', path=str(root), episode_uuid='source-uuid',
        engine_id='isaac_sim', qa_status='accepted', scene_id='rigid_cube_lift', task='lift cube')
    original_detail, original_session = service.episode_detail, service.get_session
    monkeypatch.setattr(service, 'episode_detail', lambda i: item if i == 1 else original_detail(i))
    monkeypatch.setattr(service, 'get_session', lambda i: {'status': 'stopped'} if i == 'original' else original_session(i))
    _, _, loader = service.generation_modules()
    monkeypatch.setattr(loader, 'load_source_trajectory', lambda ref: SimpleNamespace(length=120, phases=SimpleNamespace(close_frame=30,lift_frame=60)))
    return item


def preview(mode='xy'):
    return service.preview(dict(episode_ids=[1], mode=mode, attempts_per_source=2, range_m=.02, seed=42))


def draft(plan):
    from robot_data_studio.models import SessionCreate
    from robot_data_studio.services.session_service import create_session
    return create_session(SessionCreate(engine_id='isaac_sim', dataset_name='generated', scene_id='rigid_cube_lift',
        control_mode='scripted', generation_plan_id=plan['plan_id'], target_episodes=plan['total_attempts'],
        control_fps=20, physics_backend='physx'))


def test_deterministic_plan_and_source_snapshot(source):
    first, second = preview(), preview()
    assert first['total_attempts'] == 2
    assert [a['object_xy_offset_m'] for a in first['plan']['attempts']] == [a['object_xy_offset_m'] for a in second['plan']['attempts']]
    nominal = preview('nominal')
    assert nominal['total_attempts'] == 1 and nominal['plan']['attempts'][0]['object_xy_offset_m'] == [0,0]
    Path(source['path'], 'trajectory.npz').write_bytes(b'changed')
    with pytest.raises(ValueError, match='变化'):
        service.validate_sources(first['plan_id'])


def test_nonaccepted_sources_and_changed_plan_are_rejected(source):
    plan = preview()
    source['qa_status'] = 'rejected'
    with pytest.raises(ValueError, match='审核'):
        service.validate_sources(plan['plan_id'])
    source['qa_status'] = 'accepted'
    path = service.plan_directory(plan['plan_id']) / 'plan.json'
    path.write_text(path.read_text() + '\n')
    with pytest.raises(ValueError, match='changed'):
        service.get_plan(plan['plan_id'])
    with pytest.raises(ValueError):
        service.plan_directory('../outside')


def test_launch_has_native_plan_marker_and_gpu_locks_and_resume(source):
    snapshot = preview()
    session = draft(snapshot)
    root = Path(session['config']['episode_root'])
    adapter = IsaacSimAdapter()
    launch = adapter.build_worker_launch(session['config'], root)
    assert launch.command[launch.command.index('--control-source')+1] == 'trajectory'
    assert '--headless' in launch.command and '--resume-generation' not in launch.command
    assert launch.readiness.kind == 'marker'
    assert launch.resources == ('simulator:global', 'gpu:0', f'output:{root.resolve()}')
    assert str(service.settings.generation_root / 'src') in launch.env_updates['PYTHONPATH']
    planner, _, _ = service.generation_modules()
    plan_path = service.plan_directory(snapshot['plan_id']) / 'plan.json'
    report = planner.new_batch_report(planner.load_generation_plan(plan_path),plan_path)
    planner.write_json_atomic(root / 'generation_batch_report.json',report)
    assert '--resume-generation' in adapter.build_worker_launch(session['config'],root).command
    report = report.model_copy(update={'plan_sha256':'0'*64})
    planner.write_json_atomic(root / 'generation_batch_report.json',report)
    with pytest.raises(ValueError, match='digest'):
        adapter.build_worker_launch(session['config'],root)


def test_api_preview_start_progress_failure_and_scan(source, monkeypatch):
    monkeypatch.setattr(service, 'list_episodes', lambda **kw: [source] if kw.get('qa_status') else [])
    monkeypatch.setattr(worker_manager, 'start', lambda session_id: {'status':'starting'})
    monkeypatch.setattr(worker_manager, 'status', lambda session_id: {'status':'stopped'})
    monkeypatch.setattr(service, 'scan_session', lambda session_id: {'indexed':1,'invalid':0})
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as client:
        assert client.get('/generation/sources').json()['items'][0]['id'] == 1
        payload = dict(episode_ids=[1],mode='xy',attempts_per_source=2,range_m=.02,seed=42)
        response = client.post('/generation/plans',json=payload)
        assert response.status_code == 201
        plan_id=response.json()['plan_id']
        started=client.post(f'/generation/plans/{plan_id}/start',json={'dataset_name':'generated','gpu':0})
        assert started.status_code==200
        session=started.json()['session'];sid=session['id']
        assert get_session(sid)['collector_url'] is None
        assert client.post(f'/generation/plans/{plan_id}/start',json={'dataset_name':'generated','gpu':0}).json()['session']['id']==sid
        planner, models, _ = service.generation_modules()
        path=service.plan_directory(plan_id)/'plan.json';plan=planner.load_generation_plan(path)
        report=planner.new_batch_report(plan,path)
        for attempt in plan.attempts:
            report=planner.record_attempt_result(report,models.AttemptResultV1(attempt_id=attempt.attempt_id,status='failed',error='grasp failed'))
        planner.write_json_atomic(Path(session['config']['episode_root'])/'generation_batch_report.json',report)
        result=client.get(f'/generation/jobs/{sid}').json()
        assert result['completed']==2 and result['failed']==2 and result['gate_passed'] is False
        assert result['results'][0]['error']=='grasp failed'
        assert client.post(f'/generation/plans/{plan_id}/start',json={'dataset_name':'generated','gpu':0}).status_code==409
        assert client.post(f'/generation/jobs/{sid}/scan').json()['indexed']==1
        assert client.post('/generation/plans',json={**payload,'episode_ids':[1,1]}).status_code==409


def test_scan_real_episodes_are_pending(source):
    import numpy as np
    from robot_data_contracts import (AugmentationLineageV1, EpisodeWriter, EvaluatorResultV1,
        SceneProvenanceV1, SoftwareProvenanceV1)
    from robot_data_contracts.profiles.franka import FRANKA_JOINT8_ACTION, franka_feature_specs
    session = draft(preview())
    writer = EpisodeWriter(Path(session['config']['episode_root']), fps=10, robot_id='franka_panda',
        control_source='scripted', features=franka_feature_specs(), action_profile=FRANKA_JOINT8_ACTION,
        camera_names=(), camera_calibration={}, scene=SceneProvenanceV1(scene_id='rigid_cube_lift',seed=42),
        software=SoftwareProvenanceV1(python_version='test',platform='test',engine_id='isaac_sim',engine_version='test',worker_id='test'),
        lineage=AugmentationLineageV1(generation_method='retargeted',parent_episode_uuid='source-uuid'))
    writer.start('lift cube')
    writer.add_frame(images={}, values={'native_state':np.zeros(18,np.float32),'policy_state':np.zeros(16,np.float32),
        'operator_action':np.zeros(7,np.float32),'requested_action':np.zeros(8,np.float32),
        'safe_action':np.zeros(8,np.float32),'applied_action':np.zeros(8,np.float32)},
        simulation_time_s=0.,control_source_timestamp_ns=10)
    writer.finish(operator_success=None,evaluator=EvaluatorResultV1(evaluator_id='cube',evaluator_version='test',available=True,success=True))
    result=service.scan(session['id'])
    assert result['indexed']==1 and result['invalid']==0
    episodes=service.list_episodes(session_id=session['id'])
    assert episodes[0]['auto_success']==1 and episodes[0]['qa_status']=='pending'
