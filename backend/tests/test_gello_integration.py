"""Suite packaging boundaries; no simulator, USB or robot access."""
from __future__ import annotations

from html.parser import HTMLParser
from importlib import resources
import os
from pathlib import Path
import subprocess
import sys
import tomllib

from robot_data_contracts import WorkerDescriptorV1
from gello_remote.worker_descriptors import ISAAC_SIM_WORKER
from robot_data_studio.adapters import get_engine
from robot_data_studio.config import PROJECT_ROOT, settings
from robot_data_studio.models import SessionCreate


class ConsoleReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.paths.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.paths.append(attrs["href"])


def test_studio_defaults_to_bundled_worker_and_honors_override(tmp_path):
    assert settings.gello_remote_root == PROJECT_ROOT / "teleop"
    env = {k: v for k, v in os.environ.items() if not k.startswith("ROBOT_DATA_STUDIO_")}
    env.update(PYTHONDONTWRITEBYTECODE="1", ROBOT_DATA_STUDIO_GELLO_REMOTE_ROOT=str(tmp_path / "custom"))
    result = subprocess.run(
        [sys.executable, "-B", "-c", "from robot_data_studio.config import settings; print(settings.gello_remote_root)"],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(tmp_path / "custom")


def test_gello_and_studio_use_the_same_worker_contract():
    descriptor = get_engine("isaac_sim").descriptor()["worker"]
    assert isinstance(ISAAC_SIM_WORKER, WorkerDescriptorV1)
    assert descriptor == ISAAC_SIM_WORKER.model_dump(mode="json")


def test_shared_contract_dependency_is_pinned_once_per_distribution():
    for rel in ("backend/pyproject.toml", "teleop/pyproject.toml"):
        metadata = tomllib.loads((PROJECT_ROOT / rel).read_text())
        assert metadata["project"]["dependencies"].count("robot-data-contracts==0.2.0") == 1
    metadata = tomllib.loads((PROJECT_ROOT / "backend/pyproject.toml").read_text())
    assert "gello-remote==0.1.0" in metadata["project"]["dependencies"]
    assert not (PROJECT_ROOT / "teleop/src/robot_data_contracts").exists()


def test_control_imports_do_not_require_studio_or_a_simulator(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ROBOT_DATA_STUDIO_")}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=os.pathsep.join([
        str(PROJECT_ROOT / "teleop/src"), str(PROJECT_ROOT / "packages/robot-data-contracts/src"),
    ]))
    result = subprocess.run([sys.executable, "-B", "-c", '''
import sys
class Forbidden:
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'robot_data_studio','isaaclab','isaacsim','genesis','franka_only','clothforge','torch','jax'}:
            raise AssertionError('Unexpected dependency: ' + fullname)
sys.meta_path.insert(0, Forbidden())
import gello_remote.control
import gello_remote.protocol
import gello_remote.isaaclab_gello
from gello_remote.worker_descriptors import ISAAC_SIM_WORKER
assert ISAAC_SIM_WORKER.control_modes == ('keyboard','gello')
'''], cwd=tmp_path, env=env, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_worker_launch_points_to_bundled_source_and_selected_device(tmp_path, monkeypatch):
    prefix = tmp_path / "sdk-env"
    prefix.mkdir()
    launcher = tmp_path / "isaaclab.sh"
    launcher.write_text("#!/bin/sh\nexit 1\n")
    launcher.chmod(0o700)
    monkeypatch.setitem(settings.__dict__, "isaaclab_conda_prefix", prefix)
    monkeypatch.setitem(settings.__dict__, "isaaclab_launcher", launcher)
    config = SessionCreate(dataset_name="bundled", scene_id="rigid_cube_lift", control_mode="gello", gpu=3).model_dump()
    launch = get_engine("isaac_sim").build_worker_launch(config, tmp_path / "episodes")
    assert launch.cwd == PROJECT_ROOT / "teleop"
    assert launch.command[launch.command.index("-m") + 1] == "gello_remote.isaaclab_gello"
    assert launch.command[launch.command.index("--gpu-id") + 1] == "3"
    assert launch.env_updates["CUDA_VISIBLE_DEVICES"] == "3"
    assert "gpu:3" in launch.resources
    python_paths = launch.env_updates["PYTHONPATH"].split(os.pathsep)
    assert str(PROJECT_ROOT / "teleop/src") in python_paths
    assert str(PROJECT_ROOT / "packages/robot-data-contracts/src") in python_paths
    assert str(settings.clothforge_root / "src") not in python_paths
    assert not (tmp_path / "episodes").exists()


def test_runtime_console_references_are_complete():
    web = resources.files("gello_remote").joinpath("web")
    index = web.joinpath("console/index.html")
    # The public source snapshot does not ship vendor-containing builds. If the
    # operator built a console locally, check its references before using it.
    if index.is_file():
        parser = ConsoleReferences()
        parser.feed(index.read_text())
        assert any(path.endswith(".js") for path in parser.paths)
        assert any(path.endswith(".css") for path in parser.paths)
        for path in parser.paths:
            assert path.startswith("/assets/")
            assert web.joinpath("console", path.lstrip("/")).is_file(), path
    else:
        from gello_remote.isaaclab_gello import GelloWebServer, TelemetryStore
        from types import SimpleNamespace
        class Protocol:
            def reject(self, status, text):
                return SimpleNamespace(status_code=int(status), body=text.encode(), headers={})
        server = GelloWebServer(object(), TelemetryStore(), host="127.0.0.1", port=18081)
        result = server._process_request(SimpleNamespace(protocol=Protocol()), SimpleNamespace(path="/", headers={}))
        assert result.status_code == 404
        assert b"not built" in result.body
    for relative in ("gello_web_serial.mjs", "cloth_drop.html", "genesis/gello_ui.html", "genesis/keyboard_ui.html"):
        assert web.joinpath(relative).is_file(), relative
