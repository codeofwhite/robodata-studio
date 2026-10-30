"""Public-core boundaries, using isolated storage and no simulator processes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from robot_data_studio.config import PROJECT_ROOT, settings
from robot_data_studio.models import ExportCreate, SessionCreate


def run_python(code: str, tmp_path: Path, **overrides: str) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if not key.startswith("ROBOT_DATA_STUDIO_")}
    env.update({
        "PYTHONPATH": os.pathsep.join([
            str(PROJECT_ROOT / "backend/src"),
            str(PROJECT_ROOT / "packages/robot-data-contracts/src"),
        ]),
        "PYTHONDONTWRITEBYTECODE": "1",
        "ROBOT_DATA_STUDIO_DB": str(tmp_path / "studio.db"),
        "ROBOT_DATA_STUDIO_DATA_ROOT": str(tmp_path / "data"),
        "ROBOT_DATA_STUDIO_WORKSPACE_ROOT": str(tmp_path / "workspace"),
        **overrides,
    })
    return subprocess.run([sys.executable, "-B", "-c", code], env=env,
                          cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=20)


def test_default_api_import_needs_no_external_runtime_or_optional_routes(tmp_path):
    result = run_python('''
import sys
class ForbidRuntime:
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'genesis','franka_only','clothforge','isaaclab','openpi','jax','torch','robot_data_generation'}:
            raise AssertionError('Unexpected runtime import: ' + fullname)
sys.meta_path.insert(0, ForbidRuntime())
from robot_data_studio.main import app
from robot_data_studio.adapters import engine_descriptors
from fastapi.testclient import TestClient
with TestClient(app) as client:
    schema = client.get('/openapi.json').json()
paths = set(schema['paths'])
assert '/api/sessions' in paths and '/api/exports' in paths
assert '/api/episodes/{episode_id}/qa' in paths
assert not any(any(word in path for word in ('/cloth', '/generation', '/assets', '/pbr-', '/consumer-smokes', '/isaac-render')) for path in paths)
engines = engine_descriptors()
assert [engine['id'] for engine in engines] == ['isaac_sim']
assert set(engines[0]['scenes']) == {'rigid_cube_lift'}
assert engines[0]['control_modes'] == ['keyboard','gello']
assert [entry['id'] for entry in engines[0]['physics_backends']] == ['physx']
assert 'robot_data_studio.adapters.clothtwin' not in sys.modules
assert 'robot_data_studio.adapters.roboverse' not in sys.modules
assert 'robot_data_studio.routes.generation' not in sys.modules
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "studio.db").is_file()
    assert not (tmp_path / "workspace").exists()


@pytest.mark.parametrize("variable,value,message", [
    ("ROBOT_DATA_STUDIO_ENABLED_EXTENSIONS", "typo", "Unknown ROBOT_DATA_STUDIO_ENABLED_EXTENSIONS"),
    ("ROBOT_DATA_STUDIO_ENABLED_ENGINES", "typo", "must list known engine IDs"),
    ("ROBOT_DATA_STUDIO_ENABLED_ENGINES", "genesis", "Extension 'genesis' is disabled"),
    ("ROBOT_DATA_STUDIO_ENABLED_ENGINES", "isaac_sim,", "must list known engine IDs"),
    ("ROBOT_DATA_STUDIO_WORKSPACE_ROOT", " ", "must not be empty"),
    ("ROBOT_DATA_STUDIO_OPENPI_GPU_ID", "-1", "must be a non-negative physical GPU ID"),
    ("ROBOT_DATA_STUDIO_ENABLED_EXTENSIONS", "offline_render", "render runtime"),
])
def test_invalid_configuration_fails_explicitly(tmp_path, variable, value, message):
    result = run_python("from robot_data_studio.main import app", tmp_path, **{variable: value})
    assert result.returncode != 0
    assert message in result.stderr
    assert not (tmp_path / "studio.db").exists()


def test_workspace_defaults_and_explicit_overrides(tmp_path):
    result = run_python('''
import json
from robot_data_studio.config import settings
print(json.dumps({'gello':str(settings.gello_remote_root), 'isaac':str(settings.isaaclab_launcher),
 'public_ip':settings.public_ip, 'checkpoint':settings.openpi_checkpoint,
 'gpu':settings.openpi_gpu_id,'cloth_gpu':settings.clothforge_gpu_id,
 'genesis_gpu':settings.cloth_genesis_gpu_id}))
''', tmp_path, ROBOT_DATA_STUDIO_GELLO_REMOTE_ROOT=str(tmp_path / "custom-gello"))
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value == {
        "gello": str(tmp_path / "custom-gello"),
        "isaac": str(tmp_path / "workspace/IsaacLab/isaaclab.sh"),
        "public_ip": "127.0.0.1", "checkpoint": None,
        "gpu": None, "cloth_gpu": None, "genesis_gpu": None,
    }


def test_adapter_class_import_remains_compatible(tmp_path):
    result = run_python('''
from robot_data_studio.adapters import IsaacSimAdapter
assert IsaacSimAdapter().adapter_id == 'isaac_sim'
''', tmp_path)
    assert result.returncode == 0, result.stderr


def test_assets_extension_registers_only_when_selected(tmp_path):
    code = '''
from robot_data_studio.main import app
from fastapi.testclient import TestClient
with TestClient(app) as client:
    paths = client.get('/openapi.json').json()['paths']
assert '/api/assets' in paths
assert not any('/cloth' in path or '/generation' in path for path in paths)
assert '/api/assets/runs' not in paths
'''
    result = run_python(code, tmp_path, ROBOT_DATA_STUDIO_ENABLED_EXTENSIONS="assets")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("scene", ["genesis_ipc_rigid_single", "genesis_ipc_clothforge_single", "bimanual_tabletop_v17_clothforge", "l_table_basket"])
def test_disabled_scene_rejected_before_session_writes(scene, isolated_settings):
    from robot_data_studio.services.session_service import create_session
    with pytest.raises(ValueError, match="unsupported or disabled"):
        create_session(SessionCreate(dataset_name="blocked", scene_id=scene, control_mode="keyboard"))
    assert not (isolated_settings.data_root / "datasets").exists()


@pytest.mark.parametrize("field", ["generation_plan_id", "cloth_generation_plan_id"])
def test_generation_request_rejected_at_request_boundary(field):
    with pytest.raises(ValidationError, match="Extension 'generation' is disabled"):
        SessionCreate(dataset_name="blocked", scene_id="rigid_cube_lift", control_mode="scripted", **{field: "a" * 32})


def test_core_session_and_missing_worker_report_without_process_launch(isolated_settings, monkeypatch):
    from robot_data_studio.main import app
    monkeypatch.setitem(settings.__dict__, "gello_remote_root", isolated_settings.data_root / "missing-gello")
    monkeypatch.setattr("robot_data_studio.services.worker_manager.subprocess.Popen",
                        lambda *a, **k: pytest.fail("A missing runtime must not spawn a worker"))
    with TestClient(app) as client:
        result = client.post("/api/sessions", json={
            "dataset_name": "public-core", "scene_id": "rigid_cube_lift", "control_mode": "keyboard",
        })
        assert result.status_code == 201, result.text
        session = result.json()
        assert session["engine_id"] == "isaac_sim"
        assert Path(session["config"]["episode_root"]).is_relative_to(isolated_settings.data_root)
        assert client.get("/api/datasets").status_code == 200
        assert client.get("/api/episodes").json() == []
        response = client.post(f"/api/sessions/{session['id']}/workers/start")
        assert response.status_code == 409
        assert "ROBOT_DATA_STUDIO_GELLO_REMOTE_ROOT" in response.json()["detail"]
        assert client.get("/api/episodes/1/isaac-render").status_code == 404


def test_launch_preflight_reports_each_missing_component(tmp_path, monkeypatch):
    from robot_data_studio.adapters import get_engine
    adapter = get_engine("isaac_sim")
    config = SessionCreate(dataset_name="test", scene_id="rigid_cube_lift", control_mode="keyboard").model_dump()
    gello = tmp_path / "gello"
    (gello / "src/gello_remote").mkdir(parents=True)
    monkeypatch.setitem(settings.__dict__, "gello_remote_root", gello)
    monkeypatch.setitem(settings.__dict__, "isaaclab_launcher", tmp_path / "isaaclab.sh")
    with pytest.raises(ValueError, match="ROBOT_DATA_STUDIO_GELLO_REMOTE_ROOT"):
        adapter.build_worker_launch(config, tmp_path / "output")
    (gello / "src/gello_remote/isaaclab_gello.py").write_text("# preflight fixture only\n")
    with pytest.raises(ValueError, match="ROBOT_DATA_STUDIO_ISAACLAB_LAUNCHER"):
        adapter.build_worker_launch(config, tmp_path / "output")
    launcher = tmp_path / "isaaclab.sh"
    launcher.write_text("#!/bin/sh\nexit 1\n")
    launcher.chmod(0o700)
    monkeypatch.setitem(settings.__dict__, "isaaclab_conda_prefix", tmp_path / "missing-env")
    with pytest.raises(ValueError, match="ROBOT_DATA_STUDIO_ISAACLAB_CONDA_PREFIX"):
        adapter.build_worker_launch(config, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_missing_export_interpreter_is_actionable(tmp_path, monkeypatch):
    from robot_data_studio.services.export_service import _build_export_launch
    monkeypatch.setitem(settings.__dict__, "lerobot_python", str(tmp_path / "missing-python"))
    payload = ExportCreate(dataset_id=1, episode_ids=[1], format="lerobot", output_name="test", repo_id="local/test")
    with pytest.raises(ValueError, match="ROBOT_DATA_STUDIO_LEROBOT_PYTHON"):
        _build_export_launch(payload, tmp_path / "input", tmp_path / "output")


@pytest.mark.parametrize("return_code,expected", [(0, "completed"), (2, "failed")])
def test_export_completion_never_starts_a_model_check(monkeypatch, return_code, expected):
    from robot_data_studio.services import export_service, consumer_smoke_service
    updates = []
    monkeypatch.setattr(export_service, "_update", lambda *args, **kwargs: updates.append((args, kwargs)))
    monkeypatch.setattr(consumer_smoke_service, "start_automatic_smoke",
                        lambda *args: pytest.fail("Export must not launch a consumer/model process"))
    class FinishedProcess:
        def wait(self):
            return return_code
    export_service._wait_for_export("export-test", FinishedProcess())
    assert updates[0][0][:2] == ("export-test", expected)
    if return_code:
        assert updates[0][0][2] == "export process exited 2"


def test_core_does_not_read_garment_registry(monkeypatch):
    from robot_data_studio.adapters import engine_descriptors
    from robot_data_studio.services.asset_service import AssetRegistry
    monkeypatch.setattr(AssetRegistry, "all", lambda *a: pytest.fail("Core must not read garment registry"))
    assert set(engine_descriptors()[0]["scenes"]) == {"rigid_cube_lift"}


def test_asset_source_template_contains_no_machine_paths():
    assert json.loads((PROJECT_ROOT / "config/asset_sources.json").read_text()) == {"schema_version": 1, "sources": {}}
