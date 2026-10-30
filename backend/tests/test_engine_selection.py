"""Deployment selection must not probe an uninstalled engine plugin."""
import json
import os
import subprocess
import sys

import pytest


def run_registry(tmp_path, selection, code):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
           "ROBOT_DATA_STUDIO_CLOTHTWIN_ROOT": str(tmp_path / "missing-plugin"),
           "ROBOT_DATA_STUDIO_COLLECTOR_PYTHON": str(tmp_path / "missing-python"),
           "ROBOT_DATA_STUDIO_DB": str(tmp_path / "studio.db"),
           "ROBOT_DATA_STUDIO_DATA_ROOT": str(tmp_path / "data")}
    env.pop("ROBOT_DATA_STUDIO_ENABLED_ENGINES", None)
    if selection is not None:
        env["ROBOT_DATA_STUDIO_ENABLED_ENGINES"] = selection
    return subprocess.run([sys.executable, "-c", code], env=env, text=True,
                          capture_output=True, timeout=30)


def test_default_registry_preserves_all_three_engines(tmp_path):
    result = run_registry(tmp_path, None, "from robot_data_studio.adapters import _ENGINES; import json; print(json.dumps(list(_ENGINES)))")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["genesis", "isaac_sim", "roboverse"]


def test_isaac_only_routes_work_without_clothtwin(tmp_path):
    result = run_registry(tmp_path, "isaac_sim", """
from fastapi.testclient import TestClient
from robot_data_studio.main import app
client = TestClient(app)
for path in ('/api/engines', '/api/adapters'):
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert [item['id'] for item in response.json()] == ['isaac_sim']
health = client.get('/api/health')
assert health.status_code == 200, health.text
assert [item['id'] for item in health.json()['engines']] == ['isaac_sim']
""")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("selection", ["", "isaac_sim,", "unknown", "isaac_sim,unknown"])
def test_invalid_selection_fails_explicitly(tmp_path, selection):
    result = run_registry(tmp_path, selection, "import robot_data_studio.adapters")
    assert result.returncode != 0
    assert "ROBOT_DATA_STUDIO_ENABLED_ENGINES must list known engine IDs" in result.stderr
