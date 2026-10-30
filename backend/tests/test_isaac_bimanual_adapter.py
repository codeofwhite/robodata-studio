from pathlib import Path
import pytest
from robot_data_studio.adapters.isaac_sim import IsaacSimAdapter


def config(**updates):
    return dict(scene_id="bimanual_tabletop_v17", control_mode="keyboard", gpu=2,
                port=18082, control_fps=20, width=960, height=720, scene_params={},
                camera_profile_id="isaac_bimanual_tabletop_visual_v4",
                renderer_profile_id="isaac_balanced_v1", physics_backend="physx", **updates)


def test_live_bimanual_launch_reuses_v17_assets_without_visual_capture():
    command = IsaacSimAdapter().build_collect_command(config(), Path("/tmp/bimanual-test"))
    for flag, suffix in (("--workstation-usd", "bimanual_tabletop_lab_v17.usda"),
                         ("--workstation-manifest-file", "asset_manifest_bimanual_v17.json"),
                         ("--franka-usd", "assets/franka/franka.usd")):
        assert command[command.index(flag) + 1].endswith(suffix)
    assert command[command.index("--scene") + 1] == "bimanual_tabletop_v17"
    assert "--visual-demo-output" not in command
    assert command[command.index("--width") + 1] == "960"


def test_environment_appearance_reaches_worker_without_physics_changes():
    import json
    candidate = config()
    candidate['scene_params']['environment_appearance'] = json.dumps({'tabletop': {'color': '#b87e42', 'roughness': .2}, 'background': None})
    command = IsaacSimAdapter().build_collect_command(candidate, Path('/tmp/surface-test'))
    resolved = json.loads(command[command.index('--environment-appearance') + 1])
    assert resolved['tabletop']['color'] == '#b87e42' and resolved['background'] is None
    assert command[command.index('--physics-backend')+1] == 'physx'


@pytest.mark.parametrize("key,value", [("control_mode", "scripted"), ("physics_backend", "newton"),
                                       ("camera_profile_id", "lab_d435i_dual_v1"), ("width", 640)])
def test_rejects_incompatible_bimanual_launch(key, value):
    candidate = config()
    candidate[key] = value
    with pytest.raises(ValueError):
        IsaacSimAdapter().validate_config(candidate)


@pytest.fixture
def clothforge_registry(tmp_path, monkeypatch):
    import json
    from robot_data_contracts.asset import AssetArtifact, AssetDraft
    from robot_data_studio.services.asset_service import AssetRegistry
    folder = tmp_path / 'garments' / 'tshirt-test'
    folder.mkdir(parents=True)
    (folder / 'mesh.npz').write_bytes(b'mesh fixture')
    (folder / 'manifest.json').write_text(json.dumps({'id': 'tshirt-test'}))
    for preset, density in [('light', .1), ('medium', .22), ('heavy', .4)]:
        (folder / f'config-{preset}.json').write_text(json.dumps({'material': {
            'mass_per_area': density, 'friction': .5, 'tri_ke': 3000, 'tri_ka': 3000, 'edge_ke': .005}}))
    sources = tmp_path / 'sources.json'
    sources.write_text(json.dumps({'schema_version': 1, 'sources': {'fixture': {'root': str(tmp_path / 'garments')}}}))
    registry = AssetRegistry(tmp_path / 'registry', sources)
    registry.publish(AssetDraft(asset_id='MDL-clothforge-tshirt-test', kind='model', name='测试 T 恤', tags=['clothforge'],
        change_note='fixture', artifacts=[AssetArtifact(source_id='fixture', path='tshirt-test/'+name, role=role)
        for name, role in [('manifest.json', 'provenance'), ('mesh.npz', 'simulation_mesh')]]))
    monkeypatch.setattr('robot_data_studio.services.asset_service.AssetRegistry', lambda: registry)
    return registry, folder


def clothforge_config(params=None):
    c = config()
    c['scene_id'] = 'bimanual_tabletop_v17_clothforge'
    c['scene_params'] = {'garment_asset_id': 'MDL-clothforge-tshirt-test', **(params or {})}
    return c


def test_genesis_ipc_single_arm_launch_uses_live_worker_and_one_gpu(clothforge_registry, tmp_path):
    candidate = clothforge_config()
    candidate.update(scene_id='genesis_ipc_clothforge_single', physics_backend='genesis_ipc',
                     camera_profile_id='lab_d435i_dual_v1', width=640, height=480)
    launch = IsaacSimAdapter().build_worker_launch(candidate, tmp_path / 'live')
    assert any(part.endswith('/teleop/live.py') for part in launch.command)
    assert launch.command[launch.command.index('--isaac-python') + 1].endswith('python.sh')
    assert launch.command[launch.command.index('--garment-dir') + 1] == str(clothforge_registry[1])
    assert launch.env_updates['CUDA_VISIBLE_DEVICES'] == str(candidate['gpu'])
    assert launch.readiness.kind == 'tcp'
    assert not any('49100' in resource for resource in launch.resources)
    candidate['scene_id'] = 'franka_empty'
    candidate['scene_params'] = {}
    with pytest.raises(ValueError, match='仅支持单臂'):
        IsaacSimAdapter().validate_config(candidate)


def test_clothforge_selection_and_parameters_are_passed_to_existing_worker(clothforge_registry):
    import json
    registry, folder = clothforge_registry
    source = (folder / 'config-heavy.json').read_bytes()
    a = IsaacSimAdapter()
    command = a.build_collect_command(clothforge_config({'material_preset': 'heavy', 'friction': .8,
                                                       'garment_rotation_deg': 90}), Path('/tmp/clothforge-test'))
    params = json.loads(command[command.index('--clothforge-params') + 1])
    assert params['mass_per_area'] == .4
    assert params['friction'] == .8
    assert params['garment_rotation_deg'] == 90
    assert params['garment_version'] == 1
    assert command[command.index('--clothforge-dir') + 1] == str(folder)
    assert '--workstation-usd' in command and '--scene-usd' not in command
    assert (folder / 'config-heavy.json').read_bytes() == source
    choices = a.scene_descriptors()['bimanual_tabletop_v17_clothforge']['parameters'][0]['choices']
    assert choices == ['MDL-clothforge-tshirt-test']


@pytest.mark.parametrize('params', [{'friction': float('nan')}, {'garment_scale': -1},
                                    {'material_preset': '../medium'}, {'cloth_iterations': 4.5},
                                    {'garment_version': True}, {'unexpected': 1}])
def test_invalid_clothforge_parameters_fail_before_launch(clothforge_registry, params):
    with pytest.raises(ValueError):
        IsaacSimAdapter().build_collect_command(clothforge_config(params), Path('/tmp/clothforge-test'))


def test_newton_clothforge_uses_same_asset_and_parameter_contract(clothforge_registry):
    import json
    candidate = clothforge_config({'friction': .8, 'cloth_iterations': 12})
    candidate['physics_backend'] = 'newton'
    adapter = IsaacSimAdapter()
    adapter.validate_config(candidate)
    command = adapter.build_collect_command(candidate, Path('/tmp/clothforge-newton-test'))
    assert command[command.index('--physics-backend') + 1] == 'newton'
    params = json.loads(command[command.index('--clothforge-params') + 1])
    assert params['friction'] == .8 and params['cloth_iterations'] == 12
    assert '--workstation-usd' in command


def test_saved_garment_appearance_reaches_worker_and_can_be_overridden(clothforge_registry):
    import json
    registry, _ = clothforge_registry
    old = registry.get('MDL-clothforge-tshirt-test', 1)
    from robot_data_contracts.asset import AssetDraft
    draft = AssetDraft(**old.model_dump(include=set(AssetDraft.model_fields)))
    draft.data['appearance'] = {'texture': 'none', 'color': '#ff8844', 'roughness': .25}
    registry.publish(draft, expected_version=1)
    for backend in ('physx', 'newton'):
        candidate = clothforge_config({'garment_version': 2})
        candidate['physics_backend'] = backend
        command = IsaacSimAdapter().build_collect_command(candidate, Path('/tmp/appearance-test'))
        params = json.loads(command[command.index('--clothforge-params') + 1])
        assert params['appearance']['color'] == '#ff8844'
        assert params['appearance']['roughness'] == .25
        assert params['visual_color'] == '#ff8844' and params['visual_roughness'] == .25
        candidate['scene_params']['visual_color'] = '#ffffff'
        command = IsaacSimAdapter().build_collect_command(candidate, Path('/tmp/appearance-test'))
        assert json.loads(command[command.index('--clothforge-params') + 1])['appearance']['color'] == '#ffffff'


def test_v5_camera_lighting_reaches_worker():
    import json
    candidate = config()
    candidate['camera_profile_id'] = 'isaac_bimanual_tabletop_visual_v5'
    candidate['scene_params']['camera_lighting'] = json.dumps({'values': {'exposure_ev': .5, 'fov_offset_deg': 2}})
    adapter = IsaacSimAdapter()
    adapter.validate_config(candidate)
    command = adapter.build_collect_command(candidate, Path('/tmp/camera-lighting-test'))
    resolved = json.loads(command[command.index('--camera-lighting') + 1])
    assert resolved['values']['exposure_ev'] == .5 and resolved['values']['fov_offset_deg'] == 2


def test_genesis_ipc_uses_latest_asset_version_and_session_episode_root(clothforge_registry, tmp_path):
    import json
    from robot_data_contracts.asset import AssetDraft
    registry, _ = clothforge_registry
    latest = registry.get('MDL-clothforge-tshirt-test')
    registry.publish(AssetDraft(**{k:v for k,v in latest.model_dump().items()
                                  if k in AssetDraft.model_fields}), expected_version=1)
    candidate = clothforge_config()
    candidate.update(scene_id='genesis_ipc_clothforge_single', physics_backend='genesis_ipc',
                     camera_profile_id='lab_d435i_dual_v1', width=640, height=480,
                     target_episodes=7)
    launch = IsaacSimAdapter().build_worker_launch(candidate, tmp_path / 'raw')
    params = json.loads(launch.command[launch.command.index('--parameters')+1])
    assert params['garment_version'] == 2
    assert launch.command[launch.command.index('--episode-root')+1] == str(tmp_path / 'raw')
    assert launch.command[launch.command.index('--target-episodes')+1] == '7'


def test_genesis_rigid_scene_uses_same_worker_without_garment(tmp_path):
    candidate = config()
    candidate.update(scene_id='genesis_ipc_rigid_single', physics_backend='genesis_ipc',
                     camera_profile_id='lab_d435i_dual_v1', width=640, height=480)
    launch = IsaacSimAdapter().build_worker_launch(candidate, tmp_path / 'rigid')
    assert '--rigid-only' in launch.command
    assert '--garment-dir' not in launch.command
    assert launch.command[launch.command.index('--episode-root')+1] == str(tmp_path / 'rigid')
    assert launch.env_updates['CUDA_VISIBLE_DEVICES'] == '2'
    assert IsaacSimAdapter().scene_descriptors()['genesis_ipc_rigid_single']['parameters'] == []


def test_dual_gello_local_fr3_launch_selects_explicit_asset(tmp_path, monkeypatch):
    import dataclasses
    from robot_data_studio.adapters import isaac_sim
    asset=tmp_path/"fr3.usd"; asset.write_text("test fixture only")
    monkeypatch.setattr(isaac_sim,"settings",dataclasses.replace(isaac_sim.settings,
        isaac_robot_model="fr3",isaac_fr3_usd=str(asset),isaac_local_display=True))
    candidate=config();candidate["control_mode"]="gello"
    launch=IsaacSimAdapter().build_worker_launch(candidate,tmp_path/"output")
    command=launch.command
    assert command[command.index("--franka-usd")+1] == str(asset)
    assert command[command.index("--robot-model")+1] == "fr3"
    assert command[command.index("--livestream")+1] == "0"
    assert "--local-display" in command and "--headless" not in command
    assert not any("49100" in resource or "47998" in resource for resource in launch.resources)


def test_fr3_wrist_profile_requires_fr3_and_reaches_worker(tmp_path, monkeypatch):
    from dataclasses import replace
    from robot_data_studio.adapters import isaac_sim
    from robot_data_studio.camera_profiles import load_camera_profile
    asset = tmp_path / "fr3.usd"
    asset.write_text("#usda 1.0\n")
    candidate = config()
    candidate["camera_profile_id"] = "isaac_fr3_dual_wrist_v1"
    original = isaac_sim.settings
    monkeypatch.setattr(isaac_sim, "settings", replace(original, isaac_robot_model="panda"))
    assert "isaac_fr3_dual_wrist_v1" not in IsaacSimAdapter().camera_profile_ids
    with pytest.raises(ValueError, match="双腕"):
        IsaacSimAdapter().validate_config(candidate)
    monkeypatch.setattr(isaac_sim, "settings", replace(original, isaac_robot_model="fr3", isaac_fr3_usd=str(asset)))
    assert "isaac_fr3_dual_wrist_v1" in IsaacSimAdapter().camera_profile_ids
    command = IsaacSimAdapter().build_collect_command(candidate, tmp_path / "session")
    assert command[command.index("--camera-profile-file")+1].endswith("isaac_fr3_dual_wrist_v1.json")
    assert command[command.index("--workstation-usd")+1].endswith("bimanual_tabletop_lab_v17.usda")
    profile = load_camera_profile("isaac_fr3_dual_wrist_v1")
    assert profile["engine_overrides"]["isaac_sim"]["recording_camera_map"] == {"main": "base", "left_wrist": "side", "right_wrist": "wrist"}
