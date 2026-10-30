from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from robot_data_contracts.asset import AssetArtifact, AssetDraft, AssetReference
from robot_data_studio.services.asset_service import AssetRegistry, file_digest, AssetIntegrityError
from robot_data_studio.services.cloth_run_service import NewtonClothRunManager, ClothRunError, _json_hash
from robot_data_studio.services.validation_overview import validation_overview


@pytest.fixture
def garment(tmp_path, request):
    garment_id, category = getattr(request, 'param', ('tshirt-000', 'tshirt'))
    source, runs = tmp_path / 'pilot', tmp_path / 'runs'
    source.mkdir(); runs.mkdir()
    folder = source / 'generation/garments' / garment_id; folder.mkdir(parents=True)
    (folder / 'mesh.npz').write_bytes(b'frozen mesh')
    (folder / 'manifest.json').write_text(json.dumps({'id': garment_id, 'category': category, 'mesh_sha256': file_digest(folder / 'mesh.npz')}))
    (folder / 'preview.html').write_text('<html><script>document.body.dataset.loaded="true"</script></html>')
    sources = tmp_path / 'sources.json'
    sources.write_text(json.dumps({'schema_version': 1, 'sources': {'clothforge-pilot-v1': {'root': str(source)}, 'studio-cloth-runs': {'root': str(runs)}}}))
    registry = AssetRegistry(tmp_path / 'registry', sources)
    model, _ = registry.publish(AssetDraft(asset_id='MDL-clothforge-' + garment_id, kind='model', name=garment_id, tags=['clothforge'], engines=['newton_vbd'], data={'category': category}, change_note='fixture', artifacts=[AssetArtifact(source_id='clothforge-pilot-v1', path=str(p.relative_to(source)), role=role) for p, role in [(folder / 'manifest.json', 'provenance'), (folder / 'mesh.npz', 'simulation_mesh'), (folder / 'preview.html', 'interactive_preview')]]))
    for key in ['light', 'medium', 'heavy']:
        material = {'id': key, 'name': key, 'mass_per_area': .22, 'mass_per_area_unit': 'kg/m2', 'tri_ke': 3000, 'tri_ka': 3000, 'tri_kd': .2, 'edge_ke': .005, 'edge_kd': .001, 'friction': .5, 'calibration_status': 'synthetic_unmeasured'}
        registry.publish(AssetDraft(asset_id='MAT-clothforge-' + key, kind='material', name=key, data={'parameters': material}, change_note='fixture'))
        config = {'material': material, 'mesh_sha256': file_digest(folder / 'mesh.npz'), 'gates': {'maximum_principal_stretch': 1.15}, 'simulation': {'duration_s': 2, 'fps': 30, 'substeps': 8, 'iterations': 10}}
        config_file = folder / f'config-{key}.json'; config_file.write_text(json.dumps(config))
        registry.publish(AssetDraft(asset_id='CFG-clothforge-' + garment_id + '-' + key, kind='config', name=key, tags=['clothforge'], engines=['newton_vbd'], data={'parameters': config}, change_note='fixture', references=[AssetReference(asset_id=model.asset_id, version=1, role='geometry')], artifacts=[AssetArtifact(source_id='clothforge-pilot-v1', path=str(config_file.relative_to(source)), role='configuration')]))
    runner = tmp_path / 'runner'; (runner / 'src/clothforge').mkdir(parents=True); (runner / 'src/clothforge/newton_worker.py').write_text('# fixture')
    manager = NewtonClothRunManager(registry, runs, runner, python=__file__)
    return manager, model, folder


def test_tuning_preserves_original_mesh_gates_and_configuration(garment):
    manager, model, folder = garment
    before = (folder / 'config-medium.json').read_bytes()
    result = manager.prepare(model.asset_id, 1, scenario='drop', material_overrides={'friction': .7}, solver_overrides={'iterations': 30})
    assert result['config']['material']['id'] == 'custom'
    assert result['config']['material']['friction'] == .7
    assert result['config']['gates'] == json.loads(before)['gates']
    assert result['config']['mesh_sha256'] == file_digest(folder / 'mesh.npz')
    assert result['config']['simulation']['substeps'] == 64
    assert result['config']['simulation']['iterations'] == 30
    assert (folder / 'config-medium.json').read_bytes() == before
    assert manager.options(model.asset_id, 1)['default_material'] == 'medium'


@pytest.mark.parametrize('garment', [('tshirt-000', 'tshirt'), ('trousers-007', 'trousers')], indirect=True)
def test_recommendations_follow_material_and_are_exposed_to_browser(garment):
    manager, model, _ = garment
    assert manager._solver('open_coat', 'drop', 'light') == {'substeps': 64, 'iterations': 15}
    assert manager._solver('open_coat', 'drop', 'heavy') == {'substeps': 64, 'iterations': 30}
    assert manager._solver('open_coat', 'drop', 'medium') == {'substeps': 64, 'iterations': 30}
    assert manager._solver('trousers', 'drop', 'light', 'trousers-007') == {'substeps': 64, 'iterations': 30}
    assert manager._solver('trousers', 'drop', 'light', 'trousers-006') == {'substeps': 64, 'iterations': 15}
    options = manager.options(model.asset_id, 1)
    for material in ['light', 'medium', 'heavy']:
        for scenario in ['hanging', 'drop']:
            prepared = manager.prepare(model.asset_id, 1, material_id=material, scenario=scenario)
            assert options['recommended_solvers'][material][scenario] == {key: prepared['config']['simulation'][key] for key in ['substeps', 'iterations']}
            expected_iterations = 30 if model.asset_id.endswith('trousers-007') and material == 'light' and scenario == 'drop' else 15
            assert prepared['config']['simulation']['iterations'] == expected_iterations


@pytest.mark.parametrize('options', [
    {'material_overrides': {'friction': True}}, {'material_overrides': {'friction': float('nan')}},
    {'material_overrides': {'friction': -1}}, {'material_overrides': {'gates': 1}},
    {'solver_overrides': {'substeps': 1.5}}, {'solver_overrides': {'substeps': 100000}},
    {'solver_overrides': {'duration_s': 100}}, {'scenario': '../../tmp'}, {'material_id': '../file'},
])
def test_invalid_or_unbounded_inputs_rejected(garment, options):
    manager, model, _ = garment
    with pytest.raises(ClothRunError): manager.prepare(model.asset_id, 1, **options)
    assert not list(manager.run_root.glob('run-*'))


def test_tampered_model_cannot_launch(garment):
    manager, model, folder = garment
    (folder / 'mesh.npz').write_bytes(b'changed')
    with pytest.raises(AssetIntegrityError): manager.prepare(model.asset_id, 1)


def _start_freezes_parameters_and_uses_isolated_worker(garment, monkeypatch):
    manager, model, folder = garment
    commands = []
    monkeypatch.setattr('robot_data_studio.services.cloth_run_service.subprocess.check_output', lambda *a, **k: '16384')
    def launch(command, **kwargs):
        commands.append((command, kwargs)); return SimpleNamespace(pid=123456)
    monkeypatch.setattr('robot_data_studio.services.cloth_run_service.subprocess.Popen', launch)
    run = manager.start(model.asset_id, 1, scenario='drop', material_overrides={'friction': .7})
    config = manager.registry.get(run['config_asset_id'], run['config_version'])
    assert config.data['parameters']['material']['friction'] == .7
    assert config.data['material_modified'] is True
    assert config.data['parameters']['gates'] == {'maximum_principal_stretch': 1.15}
    assert commands[0][1]['start_new_session'] and commands[0][1]['pass_fds']
    assert '--newton-run' in commands[0][0]
    assert config.data['parameters'] == json.loads((manager.run_root / run['run_id'] / 'input/config-custom.json').read_text())
    return run


def test_completed_native_failure_is_not_promoted_to_physics_success(garment, monkeypatch):
    manager, _, _ = garment
    run = _start_freezes_parameters_and_uses_isolated_worker(garment, monkeypatch)
    actual = manager.registry.get(run['config_asset_id'], 1)
    output = manager.run_root / run['run_id'] / 'output'; output.mkdir()
    (output / 'trajectory.npz').write_bytes(b'actual saved trajectory')
    (output / 'request.json').write_text(json.dumps({'config': actual.data['parameters']}))
    result = {'outcome': 'failed', 'engine_id': 'newton_vbd', 'evaluator_version': 'fixture', 'scope': 'sampled-cloth', 'metrics': {'maximum_principal_stretch': 1.2}, 'failed_gates': ['excessive_stretch'], 'scenario': 'drop', 'material_id': 'custom', 'configuration_sha256': _json_hash(actual.data['parameters']), 'trajectory_sha256': file_digest(output / 'trajectory.npz')}
    (output / 'validation.json').write_text(json.dumps(result)); log = output.parent / 'run.log'; log.write_text('finished')
    validation = manager._publish_newton_validation(run, output, log, 0)
    assert validation.data['outcome'] == 'failed'
    assert validation.references[0].asset_id == run['config_asset_id']
    assert validation_overview(manager.registry)['items'][-1]['status'] == 'needs_repair'


def test_interactive_viewer_is_sandboxed_and_refuses_changed_evidence(garment, monkeypatch):
    manager, model, folder = garment
    monkeypatch.setattr('robot_data_studio.routes.assets.AssetRegistry', lambda: manager.registry)
    from robot_data_studio.routes.assets import router
    app = FastAPI(); app.include_router(router, prefix='/api')
    with TestClient(app) as client:
        url = f'/api/assets/{model.asset_id}/versions/1/artifacts/2/viewer'
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/html')
        assert 'sandbox allow-scripts' in response.headers['content-security-policy']
        assert 'allow-same-origin' not in response.headers['content-security-policy']
        assert client.get(f'/api/assets/{model.asset_id}/versions/1/artifacts/0/viewer').status_code == 422
        (folder / 'preview.html').write_text('changed')
        assert client.get(url).status_code == 422


def test_start_freezes_parameters_and_uses_isolated_worker(garment, monkeypatch):
    _start_freezes_parameters_and_uses_isolated_worker(garment, monkeypatch)


def test_low_free_gpu_memory_does_not_start_a_job(garment, monkeypatch):
    from robot_data_studio.services.asset_service import AssetConflict
    manager, model, _ = garment
    monkeypatch.setattr('robot_data_studio.services.cloth_run_service.subprocess.check_output', lambda *a, **k: '512')
    with pytest.raises(AssetConflict): manager.start(model.asset_id, 1)
    assert not list(manager.run_root.glob('run-*'))

def test_ipc_configuration_is_distinct_and_preserves_physics(garment):
    from robot_data_studio.services.cloth_run_service import GenesisGarmentRunManager
    manager, model, folder = garment
    registry=manager.registry
    ipc=GenesisGarmentRunManager(registry=registry,run_root=manager.run_root,runner_root=manager.runner_root,python=manager.python)
    a=manager.prepare(model.asset_id,1);b=ipc.prepare(model.asset_id,1)
    assert a['config']['material']==b['config']['material']
    assert a['config']['mesh_sha256']==b['config']['mesh_sha256']
    assert a['config']['gates']==b['config']['gates']
    assert b['config']['simulation']['solver']=='genesis_ipc'

@pytest.mark.parametrize('count',[1,2,3,5])
@pytest.mark.parametrize('damage', [None, 'mass', 'times', 'positions', 'hash'])
def test_comparison_refuses_unmatched_or_changed_trajectories(tmp_path,monkeypatch,damage,count):
    if count==1 and damage in {'mass','times','positions'}:pytest.skip('pair mismatch requires two sides')
    import numpy as np
    from robot_data_studio.services import cloth_run_service as service
    manager=service.ClothComparisonManager(registry=SimpleNamespace(get=lambda *a:object(),integrity=lambda _: {'status':'current'}),run_root=tmp_path)
    pair='run-20260918t000000z-aaaaaaaa'
    children=[f'run-20260918t00000{i}z-abcdef0{i}' for i in range(count)]
    manager._write_state({'run_id':pair,'engine_id':'comparison','children':children})
    monkeypatch.setattr(service.newton_cloth_run_manager,'get',lambda rid:{'engine_id':'newton_vbd' if rid==children[0] else 'genesis_ipc','status':'completed','created_at':'2026-09-18','validation_asset_id':'VAL-fixture','validation_version':1})
    for i,rid in enumerate(children):
        out=manager._run_dir(rid)/'output';out.mkdir(parents=True)
        positions=np.zeros((2,3,3));times=np.array([0.,1.])
        if i and damage=='positions':positions[1,0,0]=np.nan
        if i and damage=='times':times[1]=2
        np.savez(out/'trajectory.npz',positions=positions,times=times,faces=np.array([[0,1,2]]),rest_triangles=np.zeros((1,3,2)),pins=np.array([0]))
        (out/'validation.json').write_text(json.dumps({'trajectory_sha256':'wrong' if damage=='hash' else file_digest(out/'trajectory.npz')}))
        (out/'initialization.json').write_text(json.dumps({'unconstrained_total_mass_kg':2 if i and damage=='mass' else 1}))
    if damage:
        with pytest.raises(ValueError):manager.trajectories(pair)
    else:
        result=manager.trajectories(pair)
        assert result['initialization_matched'] and len(result['sides'])==count

@pytest.mark.parametrize('engines',[[],['ppf','ppf'],['unknown'],['newton_vbd']*6])
def test_comparison_invalid_solver_selection_never_creates_job(tmp_path,engines):
    from robot_data_studio.services.cloth_run_service import ClothComparisonManager
    manager=ClothComparisonManager(run_root=tmp_path)
    with pytest.raises(ClothRunError):manager.start_pair('MDL-garment',1,engine_ids=engines)
    assert not list(tmp_path.iterdir())

@pytest.mark.parametrize('engine',['newton_xpbd','physx_surface','ppf'])
def test_new_solver_preserves_frozen_geometry_material_and_acceptance(garment,engine):
    from robot_data_studio.services.cloth_run_service import SOLVER_MANAGERS
    original,model,_=garment
    manager=type(SOLVER_MANAGERS[engine])(registry=original.registry,run_root=original.run_root,runner_root=original.runner_root,python=original.python)
    baseline=original.prepare(model.asset_id,1)['config'];actual=manager.prepare(model.asset_id,1)['config']
    for key in ['mesh_sha256','material','gates']:assert actual[key]==baseline[key]
    assert actual['simulation']['solver']==engine

@pytest.mark.parametrize('damage',[None,'configuration','trajectory','registry'])
def test_saved_result_reuse_requires_parameters_and_intact_evidence(tmp_path,damage):
    from robot_data_studio.services.cloth_run_service import ClothComparisonManager
    rid='run-20260918t000001z-aaaaaaaa';folder=tmp_path/rid;output=folder/'output';output.mkdir(parents=True)
    wanted={'simulation':{'solver':'ppf'},'material':{'density':.22}}
    state={'run_id':rid,'engine_id':'ppf','status':'completed','selected_asset_id':'MDL-garment','selected_version':1,'scenario':'drop','material_id':'medium','validation_asset_id':'VAL-test','validation_version':1}
    (folder/'state.json').write_text(json.dumps(state))
    (output/'trajectory.npz').write_bytes(b'native trajectory')
    (output/'request.json').write_text(json.dumps({'config':{} if damage=='configuration' else wanted}))
    (output/'validation.json').write_text(json.dumps({'configuration_sha256':_json_hash(wanted),'trajectory_sha256':'bad' if damage=='trajectory' else file_digest(output/'trajectory.npz')}))
    registry=SimpleNamespace(get=lambda *a:object(),integrity=lambda _: {'status':'stale' if damage=='registry' else 'current'})
    solver=SimpleNamespace(engine_id='ppf',prepare=lambda *a,**k:{'config':wanted},registry=registry)
    result=ClothComparisonManager(run_root=tmp_path).find_saved(solver,'MDL-garment',1,'drop','medium')
    assert (result is not None)==(damage is None)


@pytest.mark.parametrize('frame,expected',[(24,.4),(60,.99)])
def test_ppf_native_progress_is_visible_before_process_completion(tmp_path,monkeypatch,frame,expected):
    from datetime import datetime,timezone
    from robot_data_studio.services import cloth_run_service as service
    state={'status':'running','engine_id':'ppf','created_at':datetime.now(timezone.utc).isoformat(),
           'log_tail':f'progress:  40%|████      | {frame}/60 [00:05<00:06, 4.00it/s]','progress':0.}
    monkeypatch.setattr(service.ClothRunManager,'get',lambda *a:dict(state))
    manager=service.PPFGarmentRunManager(run_root=tmp_path)
    assert manager.get('run-20260918t000000z-abcdef00')['progress']==expected

@pytest.mark.parametrize('engine', ['newton_xpbd', 'physx_surface'])
def test_contact_repair_keeps_source_material_geometry_and_gates(garment, engine):
    from robot_data_studio.services.cloth_run_service import XPBDGarmentRunManager, PhysXGarmentRunManager
    baseline, model, folder = garment
    cls = XPBDGarmentRunManager if engine == 'newton_xpbd' else PhysXGarmentRunManager
    manager = cls(baseline.registry, baseline.run_root, baseline.runner_root, python=__file__)
    before = (folder/'config-medium.json').read_bytes()
    source = json.loads(before)
    prepared = manager.prepare(model.asset_id, 1, scenario='drop')
    for key in ['material','mesh_sha256','gates']:
        assert prepared['config'][key] == source[key]
    assert (folder/'config-medium.json').read_bytes() == before
    new = prepared['config']['simulation']
    old = deepcopy(prepared['config'])
    if engine == 'newton_xpbd':
        assert new['xpbd_surface_contact']['maximum_stretch'] < source['gates']['maximum_principal_stretch']
        old['simulation'].pop('xpbd_surface_contact')
    else:
        p = new['physx_parameters']
        assert p['contact_offset_m'] > p['rest_offset_m'] >= 0
        assert p['self_collision_filter_distance_m'] >= 2*p['rest_offset_m']
        old['simulation']['physx_parameters'] = {'rest_offset_m':.0003,'contact_offset_m':.002,'self_collision_filter_distance_m':.0006}
    assert _json_hash(old) != _json_hash(prepared['config'])
