from pathlib import Path
import hashlib
import json

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from robot_data_contracts import EpisodeWriter, AugmentationLineageV1, EvaluatorResultV1, SceneProvenanceV1, SoftwareProvenanceV1
from robot_data_contracts.profiles.franka import franka_feature_specs, FRANKA_JOINT8_ACTION
from robot_data_studio.routes.episodes import router
from robot_data_studio.services import episode_render_service as service
from robot_data_studio.adapters.clothtwin import ClothTwinAdapter


@pytest.fixture
def source(tmp_path, monkeypatch):
    replay={'format_version':1, 'physics_backend':'genesis_rigid',
            'cameras':{'base':{'pose_array':'camera_to_world_base','resolution':[32,32]}}}
    writer=EpisodeWriter(tmp_path/'raw', fps=20, robot_id='franka_panda',control_source='browser_keyboard',
        features=franka_feature_specs(),action_profile=FRANKA_JOINT8_ACTION,camera_names=('base',),
        camera_calibration={'base':{'intrinsics':[20,0,16,0,20,16,0,0,1],'extrinsics':{'camera_to_world':np.eye(4).tolist()}}},
        scene=SceneProvenanceV1(scene_id='rigid_pick_place',seed=0,parameters={'offline_replay':replay}),
        software=SoftwareProvenanceV1(engine_id='genesis',engine_version='test',python_version='test',platform='test',worker_id='test'),
        lineage=AugmentationLineageV1(generation_method='teleoperation'))
    # Backend tests cover contracts and file counts; real GPU smoke covers JPEG encoding.
    monkeypatch.setattr(writer, '_write_rgb', lambda path, rgb: path.write_bytes(b'fixture frame'))
    writer.start('native source')
    values={'native_state':np.zeros(18,np.float32),'policy_state':np.zeros(16,np.float32),
            'operator_action':np.zeros(7,np.float32),'requested_action':np.zeros(8,np.float32),
            'safe_action':np.zeros(8,np.float32),'applied_action':np.zeros(8,np.float32),
            'robot_link_poses':np.array([[0,0,0,1,0,0,0]],np.float32),
            'object_pose':np.array([0,0,0,1,0,0,0],np.float32),'camera_to_world_base':np.eye(4)}
    writer.add_frame(images={'base':np.zeros((32,32,3),np.uint8)},values=values,simulation_time_s=0.)
    path=writer.finish(operator_success=False,evaluator=EvaluatorResultV1(evaluator_id='none',evaluator_version='1',available=False,unavailable_reason='fixture'))
    item={'id':1,'engine_id':'genesis','qa_status':'pending','path':str(path),'fps':20,'num_frames':1}
    monkeypatch.setattr(service,'episode_detail',lambda i:item if i==1 else None)
    return item


def test_render_requires_replay_metadata_and_keeps_source_untouched(source):
    root=Path(source['path']);before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}
    assert service.availability(1)['available']
    assert service.source(1)[2]['trajectory.npz']==before['trajectory.npz']
    assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}
    manifest=json.loads((root/'manifest.json').read_text());manifest['scene']['parameters'].pop('offline_replay')
    (root/'manifest.json').write_text(json.dumps(manifest))
    assert not service.availability(1)['available']


def test_changed_or_rejected_source_blocks_render(source):
    _,_,hashes=service.source(1)
    config={'isaac_episode_source_id':1,'isaac_episode_source_hashes':hashes}
    assert service.validate_job(config)['id']==1
    p=Path(source['path'])/'manifest.json';p.write_text(p.read_text()+'\n')
    with pytest.raises(ValueError,match='发生变化'):service.validate_job(config)
    source['qa_status']='rejected'
    assert not service.availability(1)['available']


def test_offline_launch_uses_gpu_lease_without_collector_port(source,tmp_path):
    _,_,hashes=service.source(1)
    launch=ClothTwinAdapter().build_worker_launch({'isaac_episode_source_id':1,'isaac_episode_source_hashes':hashes,'gpu':3},tmp_path/'render')
    assert any(p.endswith('render_episode.py') for p in launch.command)
    assert launch.env_updates['CUDA_VISIBLE_DEVICES']=='3'
    assert launch.resources==(f'gpu:3',f'output:{(tmp_path/"render").resolve()}')
    assert '--port' not in launch.command
    root=tmp_path/'render';root.mkdir();(root/'render-result.json').write_text('{"status":"completed"}')
    with pytest.raises(ValueError,match='已完成'):
        ClothTwinAdapter().build_worker_launch({'isaac_episode_source_id':1,'isaac_episode_source_hashes':hashes,'gpu':3},root)


def test_render_api_reports_old_episode_and_validates_gpu(source,monkeypatch):
    monkeypatch.setattr(service,'jobs',lambda i:[])
    app=FastAPI();app.include_router(router)
    with TestClient(app) as client:
        assert client.get('/episodes/1/isaac-render').json()['availability']['available']
        assert client.post('/episodes/1/isaac-render',json={'gpu':-1}).status_code==422
        assert client.post('/episodes/999/isaac-render',json={'gpu':1}).status_code==422



def test_completed_job_is_indexed_once_under_concurrent_polling(tmp_path, monkeypatch):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from robot_data_studio.services.worker_manager import worker_manager
    root=tmp_path/'render';root.mkdir()
    (root/'render-result.json').write_text('{"status":"completed"}')
    monkeypatch.setattr(service,'get_session',lambda sid:{'id':sid,'config':{'isaac_episode_source_id':1,'episode_root':str(root)}})
    monkeypatch.setattr(worker_manager,'status',lambda sid:{'status':'stopped','error':None})
    monkeypatch.setattr(service,'validate_job',lambda config:None)
    episodes=[];scans=[]
    monkeypatch.setattr(service,'list_episodes',lambda **kwargs:list(episodes))
    def scan(sid):
        scans.append(sid);time.sleep(.03);episodes.append({'id':9})
    monkeypatch.setattr(service,'scan_session',scan)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results=list(executor.map(lambda _:service.job('render-session'),range(4)))
    assert scans==['render-session']
    assert all(r['episode_id']==9 and r['status']=='completed' for r in results)
