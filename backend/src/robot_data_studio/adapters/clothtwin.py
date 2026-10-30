from __future__ import annotations

import json
import math
import os
import subprocess
from functools import cached_property
from pathlib import Path
from typing import Any

from ..config import CONTRACTS_SRC, PROJECT_ROOT, settings
from ..camera_profiles import validate_session_camera_profile
from .base import CollectionAdapter, WorkerLaunch, WorkerReadiness


class ClothTwinAdapter(CollectionAdapter):
    adapter_id = "genesis"
    label = "Genesis / Cloth Scenes"
    scenes: dict[str, dict[str, Any]] = {}
    control_modes = ("keyboard", "gello")
    camera_profile_ids = ("lab_d435i_dual_v1",)
    capabilities = {
        "webrtc": False,
        "recording": True,
        "automatic_outcome": True,
        "scene_reconfigure": True,
    }
    allowed_modules = {
        "keyboard": "gello_remote.genesis_worker",
        "gello": "gello_remote.genesis_worker",
    }
    worker_entrypoint = "gello_remote.genesis_worker"

    def __init__(self) -> None:
        # Adapter registration freezes the configured plugin location. Tests may
        # redirect data roots, but that must not silently redirect plugin code.
        self.plugin_root = Path(settings.clothtwin_root)

    def _plugin_env(self) -> dict[str, str]:
        """Environment for the plugin subprocess.

        The plugin runs out-of-process: the adapter passes a location, never an
        imported module. Both `describe` and `validate` must see the same
        PYTHONPATH, so it is built in one place.
        """
        env = dict(os.environ)
        python_paths = [
            str(CONTRACTS_SRC),
            str(settings.gello_remote_root / "src"),
        ]
        if env.get("PYTHONPATH"):
            python_paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(python_paths)
        return env

    @cached_property
    def plugin_descriptor(self) -> dict[str, Any]:
        result = subprocess.run(
            [settings.collector_python, "-m", "franka_only.scene_plugin", "describe"],
            cwd=self.plugin_root,
            env=self._plugin_env(),
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        descriptor = json.loads(result.stdout)
        if descriptor.get("contract") != "robot_data_scene_plugin" or descriptor.get("contract_version") != 1:
            raise ValueError("unsupported Cloth scene-plugin descriptor")
        return descriptor

    def validate_scene_parameters(
        self, scene: str, scene_params: dict[str, Any]
    ) -> dict[str, float | int | str]:
        """Resolve scene parameters through the plugin, as the worker will.

        The worker validates the same values again inside its own `parse_args`, so
        a rejection there used to surface only as `worker exited with return code 2`
        in the collector log. Asking the plugin here instead reports the reason
        when the session is created.
        """
        command = [
            settings.collector_python, "-m", "franka_only.scene_plugin", "validate",
            "--scene", scene,
        ]
        for key, value in sorted(scene_params.items()):
            command += ["--param", f"{key}={value}"]
        result = subprocess.run(
            command,
            cwd=self.plugin_root,
            env=self._plugin_env(),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise ValueError(result.stderr.strip() or "scene parameters were rejected")
        return json.loads(result.stdout)

    def scene_descriptors(self) -> dict[str, dict[str, Any]]:
        return {
            scene["id"]: {
                "label": scene["label"],
                "description": scene["description"],
                "family": scene["family"],
                "parameters": scene["parameters"],
            }
            for scene in self.plugin_descriptor["scenes"]
        }

    def validate_config(self, config: dict[str, Any]) -> None:
        if config.get('isaac_episode_source_id'):
            from ..services.episode_render_service import validate_job
            validate_job(config)
            return
        mode = config["control_mode"]
        scene = config["scene_id"]
        scenes = self.scene_descriptors()
        if mode not in self.allowed_modules or scene not in scenes:
            raise ValueError("unsupported Cloth scene collection mode or scene")
        scene_params = config.get("scene_params", {})
        allowed_params = {item["key"] for item in scenes[scene]["parameters"]}
        for key in scene_params:
            if key not in allowed_params:
                raise ValueError(f"scene parameter is not allowlisted: {key}")
        if scene_params:
            self.validate_scene_parameters(scene, scene_params)
        profile_id = str(config.get("camera_profile_id", "lab_d435i_dual_v1"))
        if profile_id not in self.camera_profile_ids:
            raise ValueError(f"unsupported Genesis camera profile: {profile_id}")
        validate_session_camera_profile(profile_id, width=int(config["width"]), height=int(config["height"]))
        control_dt = 1.0 / float(config["control_fps"])
        sim_dt = float(config.get("sim_dt", 0.01))
        simulated_dt = sim_dt * int(config["physics_steps_per_control"])
        if not math.isclose(control_dt, simulated_dt, rel_tol=1e-6, abs_tol=1e-9):
            raise ValueError(
                "inconsistent Genesis timing: "
                f"1/control_fps={control_dt:.9g}s but "
                f"sim_dt*physics_steps_per_control={simulated_dt:.9g}s"
            )

    def build_collect_command(self, config: dict[str, Any], output_dir: Path) -> list[str]:
        self.validate_config(config)
        mode = config["control_mode"]
        scene = config["scene_id"]
        command = [
            settings.collector_python, "-m", self.allowed_modules[mode],
            "--control-source", mode,
            "--scene", scene,
            "--host", "0.0.0.0",
            "--port", str(config["port"]),
            "--data-dir", str(output_dir),
            "--control-fps", str(config["control_fps"]),
            "--sim-dt", str(config.get("sim_dt", 0.01)),
            "--physics-steps-per-control", str(config["physics_steps_per_control"]),
            "--width", str(config["width"]),
            "--height", str(config["height"]),
            "--camera-profile-file",
            str(validate_session_camera_profile(
                str(config.get("camera_profile_id", "lab_d435i_dual_v1")),
                width=int(config["width"]),
                height=int(config["height"]),
            )),
        ]
        for key, value in sorted(config.get("scene_params", {}).items()):
            command += ["--scene-param", f"{key}={value}"]
        return command

    def build_worker_launch(self, config: dict[str, Any], output_dir: Path) -> WorkerLaunch:
        if config.get('isaac_episode_source_id'):
            from ..services.episode_render_service import validate_job
            item = validate_job(config)
            result = output_dir / 'render-result.json'
            if result.is_file() and json.loads(result.read_text()).get('status') == 'completed':
                raise ValueError('渲染任务已完成，请从源 Episode 新建任务')
            return WorkerLaunch(
                command=[settings.cloth_render_python, str(PROJECT_ROOT / 'expert_demos/curobo_cloth_v1/render_episode.py'),
                         '--source', item['path'], '--output', str(output_dir.resolve()), '--gpu', str(config['gpu'])],
                cwd=PROJECT_ROOT,
                env_updates={'CUDA_VISIBLE_DEVICES':str(config['gpu']), 'PYTHONDONTWRITEBYTECODE':'1',
                             'PYTHONPATH':str(CONTRACTS_SRC)},
                readiness=WorkerReadiness(kind='process', timeout_s=600),
                resources=(f"gpu:{int(config['gpu'])}", f"output:{output_dir.resolve()}"))
        python_paths = [
            str(CONTRACTS_SRC),
            str(settings.gello_remote_root / "src"),
            str(self.plugin_root),
        ]
        if os.environ.get("PYTHONPATH"):
            python_paths.append(os.environ["PYTHONPATH"])
        return WorkerLaunch(
            command=self.build_collect_command(config, output_dir),
            cwd=settings.gello_remote_root,
            env_updates={
                "CUDA_VISIBLE_DEVICES": str(config["gpu"]),
                "EGL_DEVICE_ID": str(config["gpu"]),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": os.pathsep.join(python_paths),
            },
            readiness=WorkerReadiness(
                kind="tcp", timeout_s=120.0, host="127.0.0.1", port=int(config["port"])
            ),
            resources=(
                "simulator:global",
                f"gpu:{int(config['gpu'])}",
                f"tcp:{int(config['port'])}",
                f"output:{output_dir.resolve()}",
            ),
        )
