import json
from types import SimpleNamespace
from pathlib import Path
import pytest
from robot_data_studio.services import cloth_episode_importer as importer
from robot_data_studio.services import cloth_catalog_service as catalog
from robot_data_studio.services import session_service
from robot_data_studio.services.worker_manager import worker_manager
from robot_data_studio.db import transaction
from robot_data_studio.services.asset_service import file_digest

@pytest.fixture
def source(isolated_settings,monkeypatch):
    run=isolated_settings.data_root/'expert_demos/curobo-cloth-v1/tabletop_v2/tasks/flat/v001/runs/run-test'
    episode=run/'episodes/episode_000000';episode.mkdir(parents=True)
    (episode/'manifest.json').write_text('{}');(run/'trajectory.npz').write_bytes(b'original immutable source')
    sha=file_digest(run/'trajectory.npz');(run/'delivery_verification.json').write_text(json.dumps({'trajectory_sha256':sha}))
    item={'importable':True,'batch':'tabletop_v2','path':'tasks/flat/v001/runs/run-test','run_id':'run-test','asset_id':'VAL-test'}
    monkeypatch.setattr(importer,'catalog',lambda:{'tasks':[{'attempts':[item]}]})
    monkeypatch.setattr(importer,'AssetRegistry',lambda:SimpleNamespace(get=lambda _:None,integrity=lambda _:{'status':'current'}))
    monkeypatch.setattr(importer,'inspect_episode',lambda *a,**k:SimpleNamespace(episode_uuid='episode-unique',task='flat',operator_success=None,auto_success=True,failure_reason=None,num_frames=2,created_at='2026-09-18',manifest={'scene':{'parameters':{'source_sha256':sha}}}))
    return run

def test_import_is_idempotent_and_preserves_qa_and_sources(source):
    before=(source/'trajectory.npz').read_bytes()
    assert importer.import_completed(dry_run=True)['eligible']==1
    with transaction() as db:assert db.execute('SELECT count(*) FROM episodes').fetchone()[0]==0
    assert importer.import_completed()['indexed']==1
    with transaction() as db:
        row=db.execute('SELECT * FROM episodes').fetchone();assert row['qa_status']=='pending'
        db.execute("UPDATE episodes SET qa_status='accepted'")
    assert importer.import_completed()['skipped']==1
    with transaction() as db:assert db.execute('SELECT qa_status FROM episodes').fetchone()[0]=='accepted'
    assert (source/'trajectory.npz').read_bytes()==before

def test_changed_source_refuses_import(source):
    (source/'trajectory.npz').write_bytes(b'changed')
    report=importer.import_completed();assert report['indexed']==0 and report['errors']
    with transaction() as db:assert db.execute('SELECT count(*) FROM episodes').fetchone()[0]==0

def test_imported_session_cannot_launch_move_or_delete(source):
    importer.import_completed()
    with transaction() as db:sid=db.execute('SELECT id FROM sessions').fetchone()[0]
    for action in [session_service.trash_session,session_service.restore_session,worker_manager.start]:
        with pytest.raises(ValueError,match='[Ii]mported'):action(sid)
    with pytest.raises(ValueError,match='[Ii]mported'):session_service.permanently_delete_session(sid,confirm_session_id=sid,delete_accepted_data=True)
    assert (source/'trajectory.npz').exists()

def test_catalog_rejects_path_escape(isolated_settings):
    with pytest.raises(ValueError):catalog.run_path('tabletop_v2','../../studio.db')

def test_catalog_includes_registered_camera_videos(isolated_settings,monkeypatch):
    base=catalog.root()/'tabletop_v2'
    run=base/'tasks/flat/v001/runs/demo';run.mkdir(parents=True)
    (base/'manifest.json').write_text(json.dumps({'tasks':[{'task':'flat','name':'Flat','variant':'v001','attempts':[{'path':'tasks/flat/v001/runs/demo','registered':True,'asset_id':'VAL-demo','run_id':'demo'}]}]}))
    record=SimpleNamespace(asset_id='VAL-demo',version=1,artifacts=[SimpleNamespace(role=role,path=path) for role,path in [('video_overview_4x','overview.mp4'),('video_front','front.mp4'),('trajectory','trajectory.npz')]])
    monkeypatch.setattr(catalog,'AssetRegistry',lambda:SimpleNamespace(get=lambda _:record))
    media=catalog.catalog()['tasks'][0]['attempts'][0]['media']
    assert [m['role'] for m in media]==['video','video']
    assert media[1]['url']=='/assets/VAL-demo/versions/1/artifacts/1'
    assert media[0]['label']=='video_overview_4x'


def test_accepted_import_resolves_for_export_without_copy(source,monkeypatch):
    from robot_data_studio.services.export_service import _resolve_selected_episodes
    importer.import_completed()
    with transaction() as db:
        row=db.execute('SELECT e.id,s.dataset_id FROM episodes e JOIN sessions s ON s.id=e.session_id').fetchone()
        with pytest.raises(ValueError,match='not QA-accepted'):_resolve_selected_episodes(row['dataset_id'],[row['id']])
        db.execute("UPDATE episodes SET qa_status='accepted'")
    monkeypatch.setattr(catalog,'catalog',lambda:{'tasks':[{'attempts':[{'importable':True,'batch':'tabletop_v2','run_id':'run-test','path':'tasks/flat/v001/runs/run-test'}]}]})
    selected=_resolve_selected_episodes(row['dataset_id'],[row['id']])
    assert selected[0]['source']==source/'episodes/episode_000000'
    with transaction() as db:db.execute('UPDATE episodes SET path=?',(str(source),))
    with pytest.raises(ValueError,match='does not match'):_resolve_selected_episodes(row['dataset_id'],[row['id']])
