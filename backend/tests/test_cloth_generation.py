import json
import ast
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from robot_data_studio.adapters.isaac_sim import IsaacSimAdapter
from robot_data_studio.routes.cloth_generation import router
from robot_data_studio.services import cloth_generation_service as service
from robot_data_studio.services.worker_manager import worker_manager


@pytest.fixture
def source(isolated_settings, tmp_path, monkeypatch):
    run = tmp_path / 'experts/folding/tasks/garment_flip/v004/runs/source'
    episode = run / 'episodes/episode_000000';episode.mkdir(parents=True)
    manifest = {'episode_uuid': 'parent-uuid', 'num_frames': 3, 'scene': {'parameters': {'source_demo_trajectory': str(run / 'trajectory.npz')}}}
    (episode / 'manifest.json').write_text(json.dumps(manifest))
    for name in ('trajectory.npz', 'physics.jsonl', 'config.json', 'scene_binding.json', 'source_manifest.json'):
        (run / name).write_text('{}')
    (run / 'evaluation.json').write_text('{"success":true}')
    planner = service.modules()
    (run / 'delivery_verification.json').write_text(json.dumps({'passed': True, 'native_episode': str(episode), 'trajectory_sha256': planner.digest(run / 'trajectory.npz')}))
    item = dict(id=148, path=str(episode), manifest=manifest, episode_uuid='parent-uuid', num_frames=3,
        task='garment_flip', qa_status='pending', scene_id='SCN-garment_flip@v1', control_source='scripted_curobo_physics')
    original_root = service.settings.cloth_expert_root
    object.__setattr__(service.settings, 'cloth_expert_root', tmp_path / 'experts')
    monkeypatch.setattr(service, 'episode_detail', lambda i: item if i == 148 else None)
    yield item
    object.__setattr__(service.settings, 'cloth_expert_root', original_root)


def preview():
    return service.preview({'episode_ids': [148], 'appearances': [{'texture': 'none', 'color': '#123456', 'roughness': .9}]})


def test_api_environment_variant_round_trip(source):
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as client:
        response = client.post('/cloth-generation/plans', json={'episode_ids':[148], 'appearances':[
            {'environment':{'tabletop':{'color':'#b87e42'},'background':{'color':'#eeeeee'}}}]})
        assert response.status_code == 201, response.text
        attempt = response.json()['plan']['attempts'][0]
        assert attempt['environment']['tabletop']['color'] == '#b87e42'
        assert attempt['environment']['background']['color'] == '#eeeeee'


def test_pending_delivered_source_launch_and_report_resume(source, monkeypatch):
    monkeypatch.setattr(worker_manager, 'start', lambda sid: {})
    monkeypatch.setattr(worker_manager, 'status', lambda sid: {'status': 'stopped'})
    snapshot = preview()
    job = service.start(snapshot['plan_id'], {'dataset_name': 'cloth_generated', 'gpu': 2})
    session = job['session'];root = Path(session['config']['episode_root'])
    assert session['collector_url'] is None and source['qa_status'] == 'pending'
    launch = IsaacSimAdapter().build_worker_launch(session['config'], root)
    assert 'robot_data_generation.cloth_appearance_runner' in launch.command
    assert launch.readiness.kind == 'marker' and launch.env_updates['CUDA_VISIBLE_DEVICES'] == '2'
    assert launch.resources == ('simulator:global', 'gpu:2', f'output:{root.resolve()}')
    assert service.start(snapshot['plan_id'], {'dataset_name': 'cloth_generated', 'gpu': 2})['session']['id'] == session['id']
    planner = service.modules()
    planner.write_json(root / 'cloth_generation_report.json', {'plan_id': snapshot['plan_id'],
        'plan_sha256': planner.digest(service.plan_directory(snapshot['plan_id']) / 'plan.json'), 'status': 'completed',
        'results': [{'attempt_id': snapshot['plan']['attempts'][0]['attempt_id'], 'status': 'failed', 'episode_path': None, 'error': 'render failure'}]})
    final = service.job(session['id'])
    assert final['completed'] == 1 and final['succeeded'] == 0
    (root / 'collector.log').write_text('PBR_PROGRESS 25 100\nRENDER_PROGRESS 50 100\n')
    assert service.job(session['id'])['frame_progress'] == {'stage': 'export', 'frame': 51, 'total_frames': 100}
    with pytest.raises(ValueError, match='已完成'):
        service.start(snapshot['plan_id'], {'dataset_name': 'cloth_generated', 'gpu': 2})


def test_changed_source_and_qa_rejection_invalidate_plan(source):
    snapshot = preview()
    source['qa_status'] = 'rejected'
    with pytest.raises(ValueError, match='拒绝'):
        service.get_plan(snapshot['plan_id'], check_sources=True)
    source['qa_status'] = 'pending'
    Path(source['path'], 'manifest.json').write_text('{}')
    with pytest.raises(ValueError, match='变化'):
        service.get_plan(snapshot['plan_id'], check_sources=True)
    with pytest.raises(ValueError):
        service.plan_directory('../outside')


def test_terminal_worker_reads_final_report_after_status(source, monkeypatch):
    monkeypatch.setattr(worker_manager, 'start', lambda sid: {})
    monkeypatch.setattr(worker_manager, 'status', lambda sid: {'status': 'running'})
    snapshot = preview()
    initial = service.start(snapshot['plan_id'], {'dataset_name': 'cloth_generated', 'gpu': 2})
    root = Path(initial['session']['config']['episode_root'])
    planner = service.modules()
    def completed(sid):
        planner.write_json(root / 'cloth_generation_report.json', {'plan_id': snapshot['plan_id'],
            'plan_sha256': planner.digest(service.plan_directory(snapshot['plan_id']) / 'plan.json'),
            'status': 'completed', 'results': [{'attempt_id': snapshot['plan']['attempts'][0]['attempt_id'],
            'status': 'succeeded', 'episode_path': str(root / 'episode_000000'), 'error': None}]})
        return {'status': 'stopped', 'resources': []}
    monkeypatch.setattr(worker_manager, 'status', completed)
    final = service.job(initial['session']['id'])
    assert final['worker']['status'] == 'stopped'
    assert final['report_status'] == 'completed'
    assert final['completed'] == final['total'] == final['succeeded'] == 1


def test_api_plan_and_real_episode_scan_keep_parent_and_pending(source, monkeypatch):
    monkeypatch.setattr(worker_manager, 'start', lambda sid: {})
    monkeypatch.setattr(worker_manager, 'status', lambda sid: {'status': 'stopped'})
    monkeypatch.setattr(service, 'sources', lambda: [source])
    app = FastAPI();app.include_router(router, prefix='/api')
    with TestClient(app) as client:
        response = client.post('/api/cloth-generation/plans', json={'episode_ids': [148], 'appearances': [{'texture': 'none'}]})
        assert response.status_code == 201, response.text
        snapshot = response.json()
        started = client.post(f"/api/cloth-generation/plans/{snapshot['plan_id']}/start", json={'dataset_name': 'cloth_generated', 'gpu': 2})
        assert started.status_code == 200, started.text
        session = started.json()['session']
        from robot_data_contracts.episode import AugmentationLineageV1, EvaluatorResultV1
        from robot_data_contracts.franka_writer import FrankaEpisodeWriter
        writer = FrankaEpisodeWriter(session['config']['episode_root'], fps=10, engine_id='genesis', engine_version='source physics',
            scene_id='garment_flip', control_source='scripted_curobo_physics', camera_names=[], operator_command_names=['q'],
            run_metadata={'camera_resolution': [8, 8]}, lineage=AugmentationLineageV1(parent_episode_uuid='parent-uuid', generation_method='visual_rerender'))
        writer.start('garment_flip')
        writer.add_frame(images={}, state=np.zeros(18), action=np.zeros(9), operator_command=[0], sim_time=0)
        writer._writer.finish(operator_success=None, evaluator=EvaluatorResultV1(evaluator_id='inherited', evaluator_version='1', available=True, success=True))
        scanned = client.post(f"/api/cloth-generation/jobs/{session['id']}/scan")
        assert scanned.status_code == 200 and scanned.json()['indexed'] == 1, scanned.text
        entries = service.list_episodes(session_id=session['id'])
        assert entries[0]['qa_status'] == 'pending'
        detail = json.loads(Path(entries[0]['path'], 'manifest.json').read_text())
        assert detail['lineage']['generation_method'] == 'visual_rerender' and detail['lineage']['parent_episode_uuid'] == 'parent-uuid'
        invalid = client.post('/api/cloth-generation/plans', json={'episode_ids': [148], 'appearances': [{'roughness': 2}]})
        assert invalid.status_code == 422


def test_renderer_preload_supports_archive_and_frozen_arrays(tmp_path):
    renderer = Path(__file__).parents[2] / 'expert_demos/curobo_cloth_v1/render_pbr.py'
    body = next(node.body for node in ast.parse(renderer.read_text()).body if isinstance(node, ast.Try))
    start = next(i for i, node in enumerate(body) if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'loaded' for target in node.targets))
    end = next(i for i in range(start, len(body)) if isinstance(body[i], ast.For)
               and isinstance(body[i].target, ast.Name) and body[i].target.id == 'array')
    loader = compile(ast.Module(body=body[start:end + 1], type_ignores=[]), str(renderer), 'exec')
    np.savez(tmp_path / 'trajectory.npz', tick=np.arange(3), qpos=np.ones((3, 1, 9)))
    namespace = {'np': np, 'run': tmp_path}
    exec(loader, namespace)
    archived = namespace['data']
    assert all(not value.flags.writeable for value in archived.values())
    frozen = {name: value.copy() for name, value in archived.items()}
    class FrozenLoad:
        @staticmethod
        def load(*args, **kwargs):
            return frozen
    namespace = {'np': FrozenLoad, 'run': tmp_path}
    exec(loader, namespace)
    assert namespace['data'] is frozen
    assert all(not value.flags.writeable for value in frozen.values())
    assert all(np.array_equal(archived[key], frozen[key]) for key in archived)


@pytest.mark.parametrize('fps', [2, 5, 10])
def test_legacy_folding_renderer_transform_still_compiles(fps):
    root = Path(__file__).parents[2] / 'expert_demos/curobo_cloth_v1'
    wrapper = ast.parse((root / 'folding_v3/render.py').read_text())
    main = next(node for node in wrapper.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    # Execute the actual wrapper transformations, stopping before any artifact
    # writes, simulator imports or native execution.
    transforms = []
    for node in main.body:
        if not isinstance(node, ast.If):
            continue
        condition = ast.unparse(node.test)
        if condition == 'fps != 10' or condition == 'fast':
            transforms.append(node)
        elif condition == 'cached_robot':
            first = next(i for i, item in enumerate(node.body) if isinstance(item, ast.Assign)
                         and any(isinstance(t, ast.Name) and t.id == 'marker' for t in item.targets))
            transforms.extend(node.body[first:-1])  # exclude sys.path mutation
    source = (root / 'render_pbr.py').read_text()
    assert source.count('  for _ in range(2):app.update()') == 1
    assert source.count('rt_subframes=4') == 1
    namespace = {'source': source, 'fps': fps, 'fast': True}
    exec(compile(ast.Module(body=transforms, type_ignores=[]), str(root / 'folding_v3/render.py'), 'exec'), namespace)
    compile(namespace['source'], '<legacy-renderer>', 'exec')
    assert 'rt_subframes=4' not in namespace['source']
    assert f"'video_time_s':frame/{fps}" in namespace['source']


def test_api_camera_lighting_plan_resolves_uniform_values(source):
    from robot_data_contracts.camera_lighting import sample
    app = FastAPI(); app.include_router(router)
    requested = {'mode':'uniform','seed':42,'ranges':{'exposure_ev':[-.25,.25],'white_balance_k':[4000,7000]}}
    with TestClient(app) as client:
        response = client.post('/cloth-generation/plans', json={'episode_ids':[148], 'appearances':[{'camera_lighting':requested}]})
        assert response.status_code == 201, response.text
        resolved = response.json()['plan']['attempts'][0]['camera_lighting']
        assert resolved == sample(requested)
        plan_id = response.json()['plan_id']
        assert client.get('/cloth-generation/plans/'+plan_id).json()['plan']['attempts'][0]['camera_lighting'] == resolved
