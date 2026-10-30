from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import signal
from threading import Lock, Thread
from uuid import uuid4

from robot_data_contracts.asset import AssetArtifact, AssetDraft, AssetReference

from ..config import settings, BACKEND_ROOT, CONTRACTS_SRC, PROJECT_ROOT
from .asset_service import AssetIntegrityError, AssetRegistry


class ClothRunError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClothRunManager:
    """Run the frozen cloth-batch adapter without importing Genesis into the API."""

    def __init__(self, registry: AssetRegistry | None = None, run_root: Path | None = None,
                 runner_root: Path | None = None, python: str | None = None):
        self.registry = registry or AssetRegistry()
        self.run_root = Path(run_root or settings.cloth_run_root).resolve()
        self.runner_root = Path(runner_root or settings.cloth_batch_root).resolve()
        self.python = python or settings.cloth_genesis_python
        self._lock = Lock()

    def _run_dir(self, run_id: str) -> Path:
        if not re.fullmatch(r"run-[0-9]{8}t[0-9]{6}z-[a-f0-9]{8}", run_id):
            raise ClothRunError("invalid run ID")
        path = (self.run_root / run_id).resolve()
        if path.parent != self.run_root:
            raise ClothRunError("unsafe run path")
        return path

    def _state_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "state.json"

    def _write_state(self, state: dict) -> None:
        path = self._state_path(state["run_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(".state-" + uuid4().hex)
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def get(self, run_id: str) -> dict:
        path = self._state_path(run_id)
        if not path.is_file():
            raise ClothRunError("run does not exist")
        state = json.loads(path.read_text(encoding="utf-8"))
        log = self._run_dir(run_id) / "run.log"
        if log.is_file():
            state["log_tail"] = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-80:])
        return state

    def start(self, asset_id: str, version: int) -> dict:
        config = self.registry.get(asset_id, version)
        if config.kind != "config":
            raise ClothRunError("only config assets can be run")
        if self.registry.integrity(config)["status"] != "current":
            raise AssetIntegrityError("config evidence is stale; refusing to run")
        parameters = config.data.get("parameters")
        if not isinstance(parameters, dict) or parameters.get("id") != "textile_feeding" or parameters.get("task") != "feed":
            raise ClothRunError("the first runnable task only supports textile_feeding / feed")
        if "genesis" not in config.engines:
            raise ClothRunError("config does not declare Genesis support")
        if not (self.runner_root / "genesis_runner.py").is_file():
            raise ClothRunError("Genesis cloth runner is unavailable")

        run_id = datetime.now(timezone.utc).strftime("run-%Y%m%dt%H%M%Sz-") + uuid4().hex[:8]
        directory = self._run_dir(run_id)
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "request_config.json").write_text(
            json.dumps(parameters, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        state = {
            "run_id": run_id, "status": "queued", "engine_id": "genesis", "progress": 0.0,
            "config_asset_id": asset_id, "config_version": version, "created_at": _now(),
            "started_at": None, "finished_at": None, "validation_asset_id": None,
            "validation_version": None, "outcome": None, "error": None, "log_tail": "",
        }
        self._write_state(state)
        Thread(target=self._execute, args=(run_id,), name=f"cloth-{run_id}", daemon=True).start()
        return state

    def _update(self, run_id: str, **updates) -> dict:
        with self._lock:
            state = self.get(run_id)
            state.pop("log_tail", None)
            state.update(updates)
            self._write_state(state)
            return state

    def _execute(self, run_id: str) -> None:
        directory = self._run_dir(run_id)
        output = directory / "output"
        log_path = directory / "run.log"
        state = self._update(run_id, status="running", started_at=_now())
        duration = float(json.loads((directory / "request_config.json").read_text())["duration_s"])
        cache = self.run_root / ".cache"
        for child in ("tmp", "genesis", "numba", "matplotlib"):
            (cache / child).mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update({
            "CUDA_VISIBLE_DEVICES": str(settings.cloth_genesis_gpu_id), "EGL_DEVICE_ID": "0",
            "PYOPENGL_PLATFORM": "egl", "TMPDIR": str(cache / "tmp"),
            "GS_CACHE_FILE_PATH": str(cache / "genesis"), "NUMBA_CACHE_DIR": str(cache / "numba"),
            "MPLCONFIGDIR": str(cache / "matplotlib"),
        })
        command = [self.python, "-B", str(self.runner_root / "genesis_runner.py"),
                   "--config", str(directory / "request_config.json"), "--out", str(output), "--video"]
        returncode = -1
        try:
            with log_path.open("w", encoding="utf-8") as log:
                log.write("COMMAND " + " ".join(command) + "\n")
                process = subprocess.Popen(command, cwd=self.runner_root, env=env, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True, bufsize=1)
                assert process.stdout is not None
                for line in process.stdout:
                    log.write(line); log.flush()
                    match = re.match(r"PROGRESS\s+([0-9.]+)", line)
                    if match:
                        self._update(run_id, progress=min(0.99, float(match.group(1)) / duration))
                returncode = process.wait()
            validation = self._publish_validation(state, output, log_path, returncode)
            self._update(run_id, status="completed" if returncode == 0 else "failed", progress=1.0,
                         finished_at=_now(), validation_asset_id=validation.asset_id,
                         validation_version=validation.version, outcome=validation.data["outcome"],
                         error=None if returncode == 0 else "Genesis process exited non-zero")
        except BaseException as error:
            try:
                validation = self._publish_validation(state, output, log_path, returncode, str(error))
                validation_id, validation_version = validation.asset_id, validation.version
            except BaseException:
                validation_id, validation_version = None, None
            self._update(run_id, status="failed", finished_at=_now(), validation_asset_id=validation_id,
                         validation_version=validation_version, outcome="unavailable", error=str(error))

    def _publish_validation(self, state: dict, output: Path, log_path: Path, returncode: int,
                            internal_error: str | None = None):
        evaluation_path = output / "evaluation.json"
        evaluation = json.loads(evaluation_path.read_text()) if evaluation_path.is_file() else None
        if returncode == 0 and evaluation is not None:
            outcome = "passed" if evaluation.get("status") == "PASS" else "failed"
            gates = evaluation.get("gates", {})
            failed_gates = sorted(key for key, passed in gates.items() if not passed)
            metrics = evaluation.get("metrics", {})
        else:
            outcome, gates, metrics, failed_gates = "unavailable", {}, {}, ["execution_error"]
        candidates = [
            (output / "config.json", "configuration"), (output / "trajectory.npz", "trajectory"),
            (evaluation_path, "evaluation"), (output / "replay.mp4", "video"),
            (output / "replay_provenance.json", "provenance"), (output / "final.png", "preview"),
            (output / "failure.json", "failure"), (log_path, "log"),
        ]
        artifacts = []
        for path, role in candidates:
            if path.is_file():
                relative = path.resolve().relative_to(self.run_root).as_posix()
                artifacts.append(AssetArtifact(source_id="studio-cloth-runs", path=relative, role=role))
        if not artifacts:
            raise ClothRunError("run produced no evidence artifact")
        validation_id = "VAL-studio_" + state["run_id"].replace("run-", "")
        draft = AssetDraft(
            asset_id=validation_id, kind="validation",
            name=f"送料工位 Genesis 运行 · {state['run_id']}",
            description="Studio 发起的笛卡尔双夹爪布料筛查；不是 Franka 机械臂可达性或闭环训练验证。",
            tags=["studio-run", "cloth", "textile-feeding", "cartesian-jaw"], engines=["genesis"],
            data={"outcome": outcome, "engine_id": "genesis",
                  "evaluator_version": "cloth-batch-v1/evaluate.assess-v1",
                  "scope": "cartesian_jaw_task_screening", "metrics": metrics, "gates": gates,
                  "failed_gates": failed_gates, "source_trial": state["run_id"],
                  "run_id": state["run_id"], "returncode": returncode,
                  "limitation": evaluation.get("limitation") if evaluation else "Simulation did not complete.",
                  "internal_error": internal_error},
            references=[AssetReference(asset_id=state["config_asset_id"], version=state["config_version"], role="tested_config")],
            artifacts=artifacts, change_note="Automatically registered after a Studio-triggered Genesis run.",
        )
        return self.registry.publish(draft, expected_version=0)[0]


cloth_run_manager = ClothRunManager()

# Newton jobs use the same asset/run API, with an independent environment.
# They are cloth experiments, not robot Episodes.
import argparse
from copy import deepcopy
import fcntl
import hashlib
import math
import shutil
import sys
import time

from .asset_service import AssetConflict, AssetNotFound, file_digest
from .worker_runtime import identity_matches, process_identity

MATERIAL_FIELDS = {
    "mass_per_area": {"label": "面密度", "unit": "kg/m²", "min": .02, "max": 2, "step": .01},
    "tri_ke": {"label": "拉伸系数", "unit": "求解器参数", "min": 100, "max": 30000, "step": 100},
    "tri_ka": {"label": "面积约束系数", "unit": "求解器参数", "min": 100, "max": 30000, "step": 100},
    "edge_ke": {"label": "弯曲系数", "unit": "求解器参数", "min": .00001, "max": 1, "step": .001},
    "tri_kd": {"label": "拉伸阻尼", "unit": "求解器参数", "min": 0, "max": 5, "step": .01},
    "edge_kd": {"label": "弯曲阻尼", "unit": "求解器参数", "min": 0, "max": 1, "step": .001},
    "friction": {"label": "摩擦系数", "unit": "无量纲", "min": .01, "max": 2, "step": .05},
}
SOLVER_FIELDS = {
    "substeps": {"label": "每帧子步数", "choices": [16, 32, 64]},
    "iterations": {"label": "每子步迭代数", "choices": [10, 15, 30, 60]},
}
SOLVER_DEFAULTS = {"topological_contact_filter_threshold": 1, "collision_detection_interval": 1,
                   "soft_contact_ke": 1e4, "soft_contact_kd": 10.,
                   "vertex_contact_buffer_size": 64, "edge_contact_buffer_size": 128}


def _json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _checked_overrides(values, fields):
    if not isinstance(values, dict) or set(values) - set(fields):
        raise ClothRunError("unsupported tuning parameter")
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ClothRunError("finite numeric value required: " + key)
        field = fields[key]
        if "choices" in field:
            if not isinstance(value, int) or value not in field["choices"]:
                raise ClothRunError("unsupported solver value: " + key)
        elif not field["min"] <= value <= field["max"]:
            raise ClothRunError("tuning value outside supported range: " + key)
    return values


class NewtonClothRunManager(ClothRunManager):
    engine_id = "newton_vbd"
    @property
    def timeout_s(self):
        return settings.clothforge_timeout_s * (2 if self.engine_id == "genesis_ipc" else 1)
    def __init__(self, registry=None, run_root=None, runner_root=None, python=None):
        super().__init__(registry, run_root, runner_root or settings.clothforge_root,
                         python or settings.clothforge_python)

    def _selection(self, asset_id, version):
        record = self.registry.get(asset_id, version)
        if record.kind not in {"model", "config"} or "clothforge" not in record.tags or not {"newton_vbd", "genesis_ipc", "newton_xpbd", "physx_surface", "ppf"}.intersection(record.engines):
            raise ClothRunError("select a ClothForge garment or configuration")
        if self.registry.integrity(record)["status"] != "current":
            raise AssetIntegrityError("selected asset evidence is stale")
        if record.kind == "model":
            model = record
        else:
            ref = next((r for r in record.references if r.role == "geometry"), None)
            if ref is None:
                raise ClothRunError("configuration has no garment reference")
            model = self.registry.get(ref.asset_id, ref.version)
        artifact = next((a for a in model.artifacts if a.role == "provenance" and a.source_id in {"clothforge-pilot-v1", "clothforge-library-v1", "clothforge-trouser-styles-v1", "clothforge-tshirt-styles-v1", "clothforge-skirt-styles-v1", "garmentcodedata-v2-phase2"}), None)
        if artifact is None:
            raise ClothRunError("unsupported garment provenance")
        path = self.registry.artifact_path(self.registry.inspect_artifact(artifact))
        manifest = json.loads(path.read_text())
        if manifest["category"] not in {"tshirt", "trousers", "open_coat", "towel", "napkin", "long_sleeve", "shorts", "skirt"}:
            raise ClothRunError("unsupported garment category")
        mesh = next(a for a in model.artifacts if a.role == "simulation_mesh")
        mesh_path = self.registry.artifact_path(self.registry.inspect_artifact(mesh))
        if mesh_path != path.parent / "mesh.npz" or file_digest(mesh_path) != manifest["mesh_sha256"]:
            raise AssetIntegrityError("garment mesh does not match manifest")
        return record, model, manifest, path.parent

    def options(self, asset_id, version):
        record, model, manifest, _ = self._selection(asset_id, version)
        presets = []
        for material_id in ["light", "medium", "heavy"]:
            material = self.registry.get("MAT-clothforge-" + material_id, 1)
            presets.append({"id": material_id, "name": material.name, "parameters": material.data["parameters"]})
        original = record.data.get("parameters", {}) if record.kind == "config" else {}
        selected = record.data.get("preset_material_id", original.get("material", {}).get("id", "medium"))
        scenario = record.data.get("scenario", "hanging")
        default_solver = self._solver(manifest["category"], scenario, selected, manifest["id"])
        if record.data.get("runner") == "clothforge":
            default_solver.update({k: original["simulation"][k] for k in SOLVER_FIELDS})
        return {"model_asset_id": model.asset_id, "model_version": model.version, "garment_id": manifest["id"],
                "category": manifest["category"], "presets": presets, "default_material": selected,
                "default_scenario": scenario, "initial_material": original.get("material"),
                "initial_solver": default_solver,
                "recommended_solvers": {p["id"]: {s: self._solver(manifest["category"], s, p["id"], manifest["id"]) for s in ["hanging", "drop"]} for p in presets},
                "material_fields": MATERIAL_FIELDS, "solver_fields": SOLVER_FIELDS,
                "scenarios": [{"id": "hanging", "label": "双点悬挂"}, {"id": "drop", "label": "自由落地"}],
                "duration_s": 2, "gpu": settings.clothforge_gpu_id}

    @staticmethod
    def _solver(category, scenario, material_id="medium", garment_id=None):
        # Coat impacts need the finer time step. Medium/heavy also need 30
        # iterations: 64 x 15 failed stretch/contact gates on coats 000/008.
        iterations = 30 if category == "open_coat" and scenario == "drop" and material_id in {"medium", "heavy"} else 15
        # Geometry-specific numerical repair: light trousers 007 had 20.21%
        # impact stretch at 64 x 15; 64 x 30 passed at 9.46%. Other trousers
        # retain their independently validated defaults.
        if (garment_id, material_id, scenario) == ("trousers-007", "light", "drop"):
            iterations = 30
        return {"substeps": 64, "iterations": iterations}

    def prepare(self, asset_id, version, scenario="hanging", material_id="medium", material_overrides=None, solver_overrides=None):
        record, model, manifest, garment = self._selection(asset_id, version)
        if scenario not in {"hanging", "drop"} or material_id not in {"light", "medium", "heavy"}:
            raise ClothRunError("unsupported scenario or material preset")
        material_overrides = _checked_overrides(material_overrides or {}, MATERIAL_FIELDS)
        solver_overrides = _checked_overrides(solver_overrides or {}, SOLVER_FIELDS)
        baseline = self.registry.get(f"CFG-clothforge-{manifest['id']}-{material_id}", 1)
        if self.registry.integrity(baseline)["status"] != "current":
            raise AssetIntegrityError("source configuration is stale")
        source = json.loads((garment / f"config-{material_id}.json").read_text())
        if source != baseline.data["parameters"] or source["mesh_sha256"] != manifest["mesh_sha256"]:
            raise AssetIntegrityError("source config differs from registered revision")
        config = deepcopy(source)
        config["material"].update(material_overrides)
        modified = config["material"] != source["material"]
        if modified:
            config["material"].update(id="custom", name="自定义合成材料")
        numerical = {**self._solver(manifest["category"], scenario, material_id, manifest["id"]), **solver_overrides}
        config["simulation"].update(SOLVER_DEFAULTS)
        config["simulation"].update(numerical)
        if config["simulation"]["duration_s"] != 2:
            raise ClothRunError("this runner requires the frozen 2-second horizon")
        profile = {"id": "studio-custom" if modified or solver_overrides else "studio-recommended",
                   "overrides": {**numerical, "topological_contact_filter_threshold": 1, "collision_detection_interval": 1}}
        config["simulation"]["solver"] = self.engine_id
        return {"config": config, "profile": profile, "model": model, "record": record, "manifest": manifest,
                "garment": garment, "scenario": scenario, "preset_material_id": material_id,
                "material_id": "custom" if modified else material_id, "material_modified": modified}

    def start(self, asset_id, version, **options):
        prepared = self.prepare(asset_id, version, **options)
        worker_file = {"genesis_ipc":"genesis_worker.py","physx_surface":"physx_worker.py","ppf":"ppf_worker.py"}.get(self.engine_id,"newton_worker.py")
        if not Path(self.python).is_file() or not (self.runner_root / "src/clothforge" / worker_file).is_file():
            raise ClothRunError("cloth solver environment is unavailable")
        self.run_root.mkdir(parents=True, exist_ok=True)
        lock = (self.run_root / f".newton-gpu-{settings.clothforge_gpu_id}.lock").open("a")
        try:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise AssetConflict("布料求解器正在运行，请等待当前任务完成") from error
            try:
                memory = subprocess.check_output(["nvidia-smi", "-i", str(settings.clothforge_gpu_id),
                                                  "--query-gpu=memory.free", "--format=csv,noheader,nounits"], text=True, timeout=10).strip()
            except (subprocess.SubprocessError, OSError) as error:
                raise ClothRunError("无法读取布料求解器 GPU 状态：" + str(error)) from error
            if int(memory) < settings.clothforge_min_free_mb:
                raise AssetConflict("GPU 剩余显存不足，请稍后再运行")
            run_id = datetime.now(timezone.utc).strftime("run-%Y%m%dt%H%M%Sz-") + uuid4().hex[:8]
            directory = self._run_dir(run_id)
            inputs = directory / "input"
            inputs.mkdir(parents=True, exist_ok=False)
            for name in ["mesh.npz", "manifest.json"]:
                shutil.copy2(prepared["garment"] / name, inputs / name)
            material_id = prepared["material_id"]
            configuration = inputs / f"config-{material_id}.json"
            configuration.write_text(json.dumps(prepared["config"], ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            (directory / "profile.json").write_text(json.dumps(prepared["profile"], indent=2) + "\n")
            model = prepared["model"]
            config_id = "CFG-studio_cf-" + run_id.removeprefix("run-")
            artifact = AssetArtifact(source_id="studio-cloth-runs", path=configuration.relative_to(self.run_root).as_posix(), role="configuration")
            actual, _ = self.registry.publish(AssetDraft(
                asset_id=config_id, kind="config", name=model.name + " · " + ("悬挂" if prepared["scenario"] == "hanging" else "落地") + " · 本次配置",
                tags=["clothforge", "studio-run", prepared["scenario"]], engines=[self.engine_id],
                data={"runner": "clothforge", "parameters": prepared["config"], "profile": prepared["profile"],
                      "scenario": prepared["scenario"], "preset_material_id": prepared["preset_material_id"],
                      "material_modified": prepared["material_modified"]},
                references=[AssetReference(asset_id=model.asset_id, version=model.version, role="geometry"),
                            AssetReference(asset_id="MAT-clothforge-" + prepared["preset_material_id"], version=1, role="material_preset"),
                            AssetReference(asset_id=asset_id, version=version, role="selected_asset")],
                artifacts=[artifact], change_note="Immutable snapshot of parameters selected in Studio; requires a new physical evaluation."))
            state = {"run_id": run_id, "status": "queued", "engine_id": self.engine_id, "progress": 0.,
                     "config_asset_id": actual.asset_id, "config_version": actual.version,
                     "selected_asset_id": asset_id, "selected_version": version, "scenario": prepared["scenario"],
                     "material_id": material_id, "created_at": _now(), "started_at": None, "finished_at": None,
                     "validation_asset_id": None, "validation_version": None, "outcome": None, "error": None,
                     "log_tail": "", "worker_pid": None, "gpu": settings.clothforge_gpu_id,
                     "gpu_free_mb_before": int(memory), "timeout_s": self.timeout_s}
            self._write_state(state)
            env = os.environ.copy()
            env.update({"PYTHONDONTWRITEBYTECODE": "1", "ROBOT_DATA_STUDIO_ASSET_ROOT": str(self.registry.root),
                        "PYTHONPATH": os.pathsep.join([str(BACKEND_ROOT / "src"), str(CONTRACTS_SRC), env.get("PYTHONPATH", "")]),
                        "ROBOT_DATA_STUDIO_ASSET_SOURCES": str(self.registry.sources_file.resolve()),
                        "ROBOT_DATA_STUDIO_CLOTH_RUN_ROOT": str(self.run_root),
                        "ROBOT_DATA_STUDIO_CLOTHFORGE_ROOT": str(self.runner_root),
                        "ROBOT_DATA_STUDIO_CLOTHFORGE_PYTHON": settings.clothforge_python})
            try:
                with (directory / "supervisor.log").open("x") as log:
                    child = subprocess.Popen([sys.executable, "-B", "-m", "robot_data_studio.services.cloth_run_service",
                                              "--newton-run", run_id, "--lock-fd", str(lock.fileno())],
                                             cwd=PROJECT_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                             pass_fds=(lock.fileno(),), start_new_session=True)
            except OSError as error:
                state.update(status="failed", outcome="unavailable", error=str(error), finished_at=_now())
                self._write_state(state)
                raise ClothRunError("无法启动布料求解器进程") from error
            # Child owns the inherited lock and writes its own process identity.
            return {**state, "worker_pid": child.pid}
        finally:
            lock.close()

    def get(self, run_id):
        state = super().get(run_id)
        if state.get("engine_id") not in {"newton_vbd", "genesis_ipc", "newton_xpbd", "physx_surface", "ppf"}:
            return state
        if state["status"] in {"queued", "running"}:
            pid = state.get("worker_pid")
            dead = pid and not identity_matches(pid, state.get("worker_boot_id"), state.get("worker_start_ticks"))
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(state["created_at"])).total_seconds()
            if dead or (not pid and age > 15):
                state.update(status="failed", outcome="unavailable", error="布料求解器进程已退出，请查看日志", finished_at=_now())
                self._write_state({k: v for k, v in state.items() if k != "log_tail"})
            frames = re.findall(r"FRAME\s+(\d+)\s*/\s*(\d+)", state.get("log_tail", ""))
            if not frames and state.get("engine_id") == "ppf":
                frames = re.findall(r"progress:\s*\d+%\|[^\n\r]*?\|\s*(\d+)/(\d+)", state.get("log_tail", ""))
            if frames and state["status"] == "running":
                state["progress"] = min(.99, int(frames[-1][0]) / int(frames[-1][1]))
        return state

    def _execute_newton(self, run_id, lock_fd):
        # A detached API-environment supervisor survives page reloads/API reloads.
        # Only the child process imports Newton. The inherited flock serializes GPU jobs.
        state = super().get(run_id)
        directory = self._run_dir(run_id)
        boot, ticks = process_identity(os.getpid())
        state.update(status="running", started_at=_now(), worker_pid=os.getpid(), worker_boot_id=boot, worker_start_ticks=ticks)
        self._write_state(state)
        output, log_path = directory / "output", directory / "run.log"
        cache = self.run_root / ".newton-cache"
        for name in ["tmp", "matplotlib"]:
            (cache / name).mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update({"CUDA_VISIBLE_DEVICES": str(state["gpu"]), "PYTHONPATH": str(self.runner_root / "src"),
                    "CLOTHFORGE_CACHE_ROOT": str(cache), "MPLCONFIGDIR": str(cache / "matplotlib"), "TMPDIR": str(cache / "tmp")})
        command = [self.python, "-u", "-B", "-m", "clothforge", "simulate", "--garment", str(directory / "input"),
                   "--material", state["material_id"], "--scenario", state["scenario"], "--output", str(output),
                   "--run-config", str(directory / "profile.json"), "--engine", state["engine_id"]]
        if state["engine_id"] == "genesis_ipc":
            env.update(GS_CACHE_FILE_PATH=str(cache / "genesis"), NUMBA_CACHE_DIR=str(cache / "numba"), XDG_CACHE_HOME=str(cache), OMP_NUM_THREADS="4", PYOPENGL_PLATFORM="egl")
        stamp = time.monotonic()
        returncode, error = -1, None
        try:
            with log_path.open("x") as log:
                log.write("COMMAND " + json.dumps(command) + "\n"); log.flush()
                try:
                    process = subprocess.Popen(command, env=env, cwd=self.runner_root, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                    returncode = process.wait(timeout=state.get("timeout_s", self.timeout_s))
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    error = "布料求解器运行超时，进程组已停止"
            validation = self._publish_newton_validation(state, output, log_path, returncode, error)
            state.update(status="completed" if returncode == 0 else "failed", progress=1.,
                         validation_asset_id=validation.asset_id, validation_version=validation.version,
                         outcome=validation.data["outcome"], error=error or (None if returncode == 0 else "布料求解器执行失败"))
        except Exception as caught:
            state.update(status="failed", outcome="unavailable", error=str(caught))
        finally:
            if state["engine_id"] == "ppf":
                try:
                    subprocess.run(["docker", "rm", "-f", "clothforge-"+run_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
                except (OSError, subprocess.TimeoutExpired) as cleanup_error:
                    state.update(status="failed",outcome="unavailable",error="PPF container cleanup failed: "+str(cleanup_error))
            state.update(finished_at=_now(), worker_wall_seconds=time.monotonic() - stamp, returncode=returncode)
            self._write_state(state)
            os.close(lock_fd)

    def _publish_newton_validation(self, state, output, log_path, returncode, error=None):
        actual = self.registry.get(state["config_asset_id"], state["config_version"])
        result_path = output / "validation.json"
        if returncode == 0 and result_path.is_file():
            result = json.loads(result_path.read_text())
            request = json.loads((output / "request.json").read_text())
            if request["config"] != actual.data["parameters"] or result["configuration_sha256"] != _json_hash(request["config"]):
                raise AssetIntegrityError("executed parameters differ from the registered snapshot")
            if result["trajectory_sha256"] != file_digest(output / "trajectory.npz"):
                raise AssetIntegrityError("trajectory hash mismatch")
            if result["engine_id"] != state["engine_id"] or result["scenario"] != state["scenario"] or result["material_id"] != state["material_id"]:
                raise AssetIntegrityError("run result identity mismatch")
        else:
            result = {"outcome": "unavailable", "engine_id": self.engine_id, "evaluator_version": "clothforge_sampled_surface_v1",
                      "scope": "synthetic_garment_hanging_drop_2s_saved_frame_checks", "metrics": {},
                      "failed_gates": ["execution_error"], "error": error or "Native worker did not complete"}
        roles = {"validation.json": "metrics", "trajectory.npz": "trajectory", "replay.html": "interactive_replay",
                 "preview.png": "preview", "final.glb": "final_mesh", "request.json": "configuration",
                 "initialization.json": "initialization", "diagnostics.json": "diagnostics"}
        artifacts = [AssetArtifact(source_id="studio-cloth-runs", path=p.relative_to(self.run_root).as_posix(), role=role)
                     for name, role in roles.items() if (p := output / name).is_file()]
        artifacts.append(AssetArtifact(source_id="studio-cloth-runs", path=log_path.relative_to(self.run_root).as_posix(), role="log"))
        return self.registry.publish(AssetDraft(
            asset_id="VAL-studio_cf-" + state["run_id"].removeprefix("run-"), kind="validation",
            name=actual.name + " · " + {"passed": "通过", "failed": "失败", "unavailable": "未完成"}[result["outcome"]],
            description="Studio 发起的两秒布料试验；结果只适用于这次保存的参数与场景。",
            tags=["clothforge", "studio-run", state["scenario"]], engines=[self.engine_id],
            data={**result, "run_id": state["run_id"], "source_trial": state["run_id"], "returncode": returncode,
                  "material_modified": actual.data["material_modified"]},
            references=[AssetReference(asset_id=actual.asset_id, version=actual.version, role="tested_config")],
            artifacts=artifacts, change_note="Recorded actual native solver output and physical verdict; process completion is separate from physics success."
        ), expected_version=0)[0]


class PPFGarmentRunManager(NewtonClothRunManager):
    engine_id = "ppf"
    def prepare(self, *args, **kwargs):
        prepared=super().prepare(*args, **kwargs)
        prepared["config"]["simulation"].update(substeps=8,iterations=2048)
        prepared["profile"]["overrides"].update(substeps=8,iterations=2048)
        prepared['config']['simulation']['ppf_parameters']={'image_id':'sha256:2a1fdc6da8775c05d5f57e3441e59dde0b7a0f99dfe03676abaf024c80e2e8ae','contact_gap_m':.0005,'strain_limit':.1,'ground_friction':prepared['config']['material']['friction']}
        return prepared


class PhysXGarmentRunManager(NewtonClothRunManager):
    engine_id = "physx_surface"
    def prepare(self, *args, **kwargs):
        prepared=super().prepare(*args, **kwargs)
        prepared['config']['simulation']['physx_parameters']={'rest_offset_m':.0003,'contact_offset_m':.002,'self_collision_filter_distance_m':.0006,'pair_updates':4,'collision_iterations':4,'contact_revision':'contact-v14-motion-audit','disable_sleep':True,'explicit_zero_material_damping':True,'motion_tolerance_m':.005}
        prepared['config']['simulation'].update(substeps=8,iterations=32)
        prepared['profile']['overrides'].update(substeps=8,iterations=32)
        return prepared


class XPBDGarmentRunManager(NewtonClothRunManager):
    engine_id = "newton_xpbd"
    def prepare(self, *args, **kwargs):
        prepared=super().prepare(*args, **kwargs)
        # Jacobi spring corrections on fine, light meshes require a smaller dt.
        prepared["config"]["simulation"].update(substeps=512,iterations=4)
        prepared["profile"]["overrides"].update(substeps=512,iterations=4)
        prepared["config"]["simulation"]["xpbd_surface_contact"]={"revision":"surface-v9-conservative-contact","gap_m":.001,"margin_m":.004,"iterations":12,"maximum_stretch":1.10,"spring_damping_from_material":True,"area_stiffness_from_material":True,"symmetric_projection":True,"topological_exclusion_hops":0}
        return prepared


class GenesisGarmentRunManager(NewtonClothRunManager):
    engine_id = "genesis_ipc"
    def __init__(self, **kwargs):
        kwargs.setdefault("python", settings.cloth_genesis_python)
        super().__init__(**kwargs)
    def prepare(self, *args, **kwargs):
        prepared=super().prepare(*args, **kwargs)
        prepared['config']['simulation'].update(substeps=8,iterations=128)
        prepared['profile']['overrides'].update(substeps=8,iterations=128)
        prepared['config']['simulation']['ipc_parameters']={'newton_tolerance':1e-5,'contact_d_hat':.0005,'contact_resistance':1e7}
        return prepared

newton_cloth_run_manager = NewtonClothRunManager()
genesis_garment_run_manager = GenesisGarmentRunManager()
xpbd_garment_run_manager = XPBDGarmentRunManager()
physx_garment_run_manager = PhysXGarmentRunManager()
ppf_garment_run_manager = PPFGarmentRunManager()
SOLVER_MANAGERS = {m.engine_id: m for m in [newton_cloth_run_manager, genesis_garment_run_manager, xpbd_garment_run_manager, physx_garment_run_manager, ppf_garment_run_manager]}

class ClothComparisonManager(ClothRunManager):
    def start_pair(self, asset_id, version, scenario="hanging", material_id="medium", engine_ids=None, reuse=True):
        engine_ids = engine_ids if engine_ids is not None else ["newton_vbd", "genesis_ipc"]
        if not engine_ids or len(engine_ids)>5 or len(set(engine_ids))!=len(engine_ids) or any(e not in SOLVER_MANAGERS for e in engine_ids):
            raise ClothRunError("select one to five distinct supported solvers")
        # Validate every requested backend before creating a GPU job.
        for manager in [SOLVER_MANAGERS[e] for e in engine_ids]:
            manager.prepare(asset_id, version, scenario=scenario, material_id=material_id)
        if material_id != 'medium':raise ValueError('comparison currently validates the medium material only')
        self.run_root.mkdir(parents=True,exist_ok=True)
        lock=(self.run_root/'.comparison.lock').open('a')
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close();raise AssetConflict('已有对比任务正在运行')
        try:
            run_id=datetime.now(timezone.utc).strftime("run-%Y%m%dt%H%M%Sz-")+uuid4().hex[:8]
            directory=self._run_dir(run_id);directory.mkdir(parents=True)
            state={"run_id":run_id,"engine_id":"comparison","status":"queued","created_at":_now(),"children":[],
                   "asset_id":asset_id,"version":version,"scenario":scenario,"material_id":material_id,"error":None,"engine_ids":engine_ids,"reuse":reuse,"reused_children":[]}
            self._write_state(state)
            env=os.environ.copy();env['PYTHONPATH']=os.pathsep.join([str(BACKEND_ROOT/'src'),str(CONTRACTS_SRC)])
            with (directory/'supervisor.log').open('x') as log:
                child=subprocess.Popen([sys.executable,'-B','-m','robot_data_studio.services.cloth_run_service','--comparison-run',run_id,'--lock-fd',str(lock.fileno())],cwd=PROJECT_ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,pass_fds=(lock.fileno(),))
        finally:
            lock.close()
        return state

    def execute_pair(self, run_id):
        state=super().get(run_id);boot,ticks=process_identity(os.getpid());state.update(status='running',started_at=_now(),worker_pid=os.getpid(),worker_boot_id=boot,worker_start_ticks=ticks);self._write_state(state)
        try:
            failures=[]
            for engine in state.get('engine_ids',['newton_vbd','genesis_ipc']):
                manager=SOLVER_MANAGERS[engine]
                child=self.find_saved(manager,state['asset_id'],state['version'],state['scenario'],state['material_id']) if state.get('reuse',False) else None
                if child:state.setdefault('reused_children',[]).append(child['run_id'])
                else:child=manager.start(state['asset_id'],state['version'],scenario=state['scenario'],material_id=state['material_id'])
                state['children'].append(child['run_id']);self._write_state(state)
                deadline=time.monotonic()+manager.timeout_s+30
                while child['status'] in {'queued','running'}:
                    if time.monotonic()>deadline:raise TimeoutError('native worker supervision timeout')
                    time.sleep(1);child=manager.get(child['run_id'])
                if child['outcome']=='unavailable':failures.append(engine+': '+(child.get('error') or 'native run incomplete'))
            self.trajectories(run_id) # validate real initial conditions, including failed physical verdicts
            state.update(status='failed' if failures else 'completed',error='; '.join(failures) or None)
        except Exception as e:state.update(status='failed',error=str(e))
        finally:state['finished_at']=_now();self._write_state(state)

    def get_pair(self,run_id):
        state=super().get(run_id)
        if state.get('engine_id')!='comparison':raise ValueError('not a comparison run')
        if state['status'] in {'queued','running'}:
            pid=state.get('worker_pid');age=(datetime.now(timezone.utc)-datetime.fromisoformat(state['created_at'])).total_seconds()
            if (pid and not identity_matches(pid,state.get('worker_boot_id'),state.get('worker_start_ticks'))) or (not pid and age>15):
                state.update(status='failed',error='对比监督进程已退出');self._write_state(state)
        state['runs']=[newton_cloth_run_manager.get(x) for x in state['children']]
        return state

    def trajectories(self,run_id):
        state=super().get(run_id)
        if state.get('engine_id')!='comparison':raise ValueError('not a comparison run')
        return self._trajectories(state['children'])

    def find_saved(self,manager,asset_id,version,scenario,material_id):
        wanted=manager.prepare(asset_id,version,scenario=scenario,material_id=material_id)['config']
        for path in sorted(self.run_root.glob('run-*/state.json'),reverse=True):
            run=json.loads(path.read_text())
            if (run.get('engine_id'),run.get('status'),run.get('selected_asset_id'),run.get('selected_version'),run.get('scenario'),run.get('material_id'))!=(manager.engine_id,'completed',asset_id,version,scenario,material_id):continue
            output=path.parent/'output'
            try:
                request=json.loads((output/'request.json').read_text());result=json.loads((output/'validation.json').read_text())
                if request['config']!=wanted or result['configuration_sha256']!=_json_hash(wanted):continue
                record=manager.registry.get(run['validation_asset_id'],run['validation_version'])
                if manager.registry.integrity(record)['status']!='current':continue
                if result['trajectory_sha256']!=file_digest(output/'trajectory.npz'):continue
            except (OSError,KeyError,ValueError):continue
            return run
        return None

    def saved_trajectories(self,asset_id,version=1,scenario='hanging',material_id='medium'):
        children=[]
        for manager in SOLVER_MANAGERS.values():
            child=self.find_saved(manager,asset_id,version,scenario,material_id)
            if child:children.append(child['run_id'])
        if not children:return {'times':[],'faces':[],'sides':[],'initialization_matched':False,'scope':'no saved native results'}
        return self._trajectories(children)

    def _trajectories(self,children):
        import numpy as np
        arrays=[];sides=[]
        for child in children:
            run=newton_cloth_run_manager.get(child)
            if run.get('outcome')=='unavailable' or run.get('status')!='completed':continue
            evidence=self.registry.get(run['validation_asset_id'],run['validation_version'])
            if self.registry.integrity(evidence)['status']!='current':raise AssetIntegrityError('comparison evidence changed')
            output=self._run_dir(child)/'output'
            result=json.loads((output/'validation.json').read_text())
            if file_digest(output/'trajectory.npz')!=result['trajectory_sha256']:raise AssetIntegrityError('comparison trajectory changed')
            with np.load(output/'trajectory.npz',allow_pickle=False) as data: arrays.append({k:data[k].copy() for k in ['positions','faces','rest_triangles','pins','times']})
            init=json.loads((output/'initialization.json').read_text())
            sides.append({'engine_id':run['engine_id'],'run_id':child,'created_at':run['created_at'],'result':result,'initialization':init})
        if not arrays:raise ValueError("no completed native trajectory available")
        a=arrays[0]
        for data in arrays:
            if data['positions'].ndim!=3 or data['positions'].shape[-1]!=3 or len(data['positions'])!=len(data['times']) or not np.isfinite(data['positions']).all():raise ValueError('invalid comparison positions')
        for i,b in enumerate(arrays[1:],1):
            if a['positions'].shape!=b['positions'].shape:raise ValueError('comparison position dimensions differ')
            for key in ['faces','pins','rest_triangles','times']:
                if a[key].shape!=b[key].shape or not np.allclose(a[key],b[key],atol=1e-8):raise ValueError('comparison mismatch: '+key)
            if not np.allclose(a['positions'][0],b['positions'][0],atol=1e-6):raise ValueError('initial positions differ')
            if not np.isclose(sides[0]['initialization']['unconstrained_total_mass_kg'],sides[i]['initialization']['unconstrained_total_mass_kg']):raise ValueError('total mass differs')
        for side,data in zip(sides,arrays):side['positions']=data['positions'].round(6).tolist()
        return {'times':a['times'].tolist(),'faces':a['faces'].tolist(),'sides':sides,'initialization_matched':True,
                'scope':'same geometry, mass, pins and initial pose; different uncalibrated constitutive and contact models'}

cloth_comparison_manager=ClothComparisonManager()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--newton-run")
    parser.add_argument("--comparison-run")
    parser.add_argument("--lock-fd", type=int)
    arguments = parser.parse_args()
    if arguments.comparison_run:
        cloth_comparison_manager.execute_pair(arguments.comparison_run)
    elif arguments.newton_run and arguments.lock_fd is not None:
        state=newton_cloth_run_manager.get(arguments.newton_run)
        manager=SOLVER_MANAGERS[state['engine_id']]
        manager._execute_newton(arguments.newton_run,arguments.lock_fd)
    else:parser.error('a run and inherited lock, or comparison run is required')
