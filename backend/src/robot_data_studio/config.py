from __future__ import annotations

import os
import shutil
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent
CONTRACTS_SRC = PROJECT_ROOT / "packages" / "robot-data-contracts" / "src"

# An editable/source import keeps repository resources; a wheel import uses the
# data files installed into this interpreter's environment, never a guessed repo.
SOURCE_LAYOUT = (BACKEND_ROOT / "src" / "robot_data_studio").resolve() == Path(__file__).resolve().parent
INSTALLED_RESOURCE_ROOT = Path(sysconfig.get_path("data")) / "share" / "robot-data-studio"
DEFAULT_PROFILE_ROOT = PROJECT_ROOT / "config" if SOURCE_LAYOUT else INSTALLED_RESOURCE_ROOT
DEFAULT_MIGRATIONS_ROOT = BACKEND_ROOT / "migrations" if SOURCE_LAYOUT else INSTALLED_RESOURCE_ROOT / "migrations"

WORKSPACE_ROOT = Path(os.environ.get("ROBOT_DATA_STUDIO_WORKSPACE_ROOT", PROJECT_ROOT.parent)).expanduser()
if not str(os.environ.get("ROBOT_DATA_STUDIO_WORKSPACE_ROOT", WORKSPACE_ROOT)).strip():
    raise ValueError("ROBOT_DATA_STUDIO_WORKSPACE_ROOT must not be empty")

KNOWN_EXTENSIONS = frozenset({"genesis", "roboverse", "cloth", "generation", "assets", "consumer_smokes", "offline_render"})


def _extensions() -> frozenset[str]:
    raw = os.environ.get("ROBOT_DATA_STUDIO_ENABLED_EXTENSIONS", "")
    if not raw.strip():
        return frozenset()
    values = [item.strip() for item in raw.split(",")]
    unknown = set(values) - KNOWN_EXTENSIONS
    if unknown:
        raise ValueError("Unknown ROBOT_DATA_STUDIO_ENABLED_EXTENSIONS: " + ", ".join(sorted(unknown)))
    return frozenset(values)


def _optional_gpu(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    value = int(raw)
    if value < 0:
        raise ValueError(name + " must be a non-negative physical GPU ID")
    return value


def require_file(path: Path, variable: str, *, executable: bool = False) -> None:
    if not path.is_file() or (executable and not os.access(path, os.X_OK)):
        raise ValueError(f"Configure {variable}: required {'executable' if executable else 'file'} is unavailable: {path}")


def require_directory(path: Path, variable: str) -> None:
    if not path.is_dir():
        raise ValueError(f"Configure {variable}: required directory is unavailable: {path}")


def require_interpreter(value: str, variable: str) -> None:
    if not value.strip() or shutil.which(value) is None:
        raise ValueError(f"Configure {variable}: interpreter is unavailable: {value!r}")



@dataclass(frozen=True)
class Settings:
    migrations_root: Path = Path(os.getenv("ROBOT_DATA_STUDIO_MIGRATIONS_ROOT", DEFAULT_MIGRATIONS_ROOT))
    enabled_extensions: frozenset[str] = _extensions()
    cloth_expert_root: Path = Path(os.getenv("ROBOT_DATA_STUDIO_CLOTH_EXPERT_ROOT", PROJECT_ROOT / "data/expert_demos/curobo-cloth-v1"))
    cloth_render_python: str = os.getenv("ROBOT_DATA_STUDIO_CLOTH_RENDER_PYTHON", str(WORKSPACE_ROOT / "isaacsim" / "python.sh"))
    generation_root: Path = Path(os.getenv("ROBOT_DATA_STUDIO_GENERATION_ROOT", WORKSPACE_ROOT / "robot-data-generation"))
    asset_root: Path = Path(os.getenv("ROBOT_DATA_STUDIO_ASSET_ROOT", PROJECT_ROOT / "assets" / "registry"))
    asset_sources_file: Path = Path(os.getenv("ROBOT_DATA_STUDIO_ASSET_SOURCES", PROJECT_ROOT / "config" / "asset_sources.json"))
    cloth_run_root: Path = Path(os.getenv("ROBOT_DATA_STUDIO_CLOTH_RUN_ROOT", PROJECT_ROOT / "data" / "cloth_runs"))
    clothforge_root: Path = Path(os.getenv("ROBOT_DATA_STUDIO_CLOTHFORGE_ROOT", WORKSPACE_ROOT / "ClothForge"))
    clothforge_python: str = os.getenv("ROBOT_DATA_STUDIO_CLOTHFORGE_PYTHON", str(WORKSPACE_ROOT / ".venvs" / "newton-cloth" / "bin" / "python"))
    clothforge_gpu_id: int | None = _optional_gpu("ROBOT_DATA_STUDIO_CLOTHFORGE_GPU_ID")
    clothforge_timeout_s: int = int(os.getenv("ROBOT_DATA_STUDIO_CLOTHFORGE_TIMEOUT_S", "300"))
    clothforge_min_free_mb: int = int(os.getenv("ROBOT_DATA_STUDIO_CLOTHFORGE_MIN_FREE_MB", "8192"))
    cloth_batch_root: Path = Path(
        os.getenv("ROBOT_DATA_STUDIO_CLOTH_BATCH_ROOT", WORKSPACE_ROOT / "simulation-demos" / "cloth-batch-v1")
    )
    cloth_genesis_python: str = os.getenv(
        "ROBOT_DATA_STUDIO_CLOTH_GENESIS_PYTHON", str(WORKSPACE_ROOT / ".venvs" / "genesis" / "bin" / "python")
    )
    cloth_genesis_gpu_id: int | None = _optional_gpu("ROBOT_DATA_STUDIO_CLOTH_GENESIS_GPU_ID")
    db_path: Path = Path(os.getenv("ROBOT_DATA_STUDIO_DB", PROJECT_ROOT / "data" / "studio.db"))
    data_root: Path = Path(os.getenv("ROBOT_DATA_STUDIO_DATA_ROOT", PROJECT_ROOT / "data"))
    camera_profile_root: Path = Path(
        os.getenv("ROBOT_DATA_STUDIO_CAMERA_PROFILE_ROOT", DEFAULT_PROFILE_ROOT / "camera_profiles")
    )
    renderer_profile_root: Path = Path(
        os.getenv("ROBOT_DATA_STUDIO_RENDERER_PROFILE_ROOT", DEFAULT_PROFILE_ROOT / "renderer_profiles")
    )
    clothtwin_root: Path = Path(os.getenv("ROBOT_DATA_STUDIO_CLOTHTWIN_ROOT", WORKSPACE_ROOT / "ClothTwin"))
    collector_python: str = os.getenv(
        "ROBOT_DATA_STUDIO_COLLECTOR_PYTHON", str(WORKSPACE_ROOT / ".venvs" / "genesis" / "bin" / "python")
    )
    gello_remote_root: Path = Path(
        os.getenv("ROBOT_DATA_STUDIO_GELLO_REMOTE_ROOT", PROJECT_ROOT / "teleop")
    )
    roboverse_root: Path = Path(
        os.getenv("ROBOT_DATA_STUDIO_ROBOVERSE_ROOT", WORKSPACE_ROOT / "RoboVerse")
    )
    roboverse_python: Path = Path(
        os.getenv(
            "ROBOT_DATA_STUDIO_ROBOVERSE_PYTHON",
            WORKSPACE_ROOT / ".venvs" / "roboverse-maniskill" / "bin" / "python",
        )
    )
    roboverse_demo_root: Path = Path(
        os.getenv(
            "ROBOT_DATA_STUDIO_ROBOVERSE_DEMO_ROOT",
            PROJECT_ROOT / "data/cache/maniskill",
        )
    )
    isaaclab_launcher: Path = Path(
        os.getenv("ROBOT_DATA_STUDIO_ISAACLAB_LAUNCHER", WORKSPACE_ROOT / "IsaacLab" / "isaaclab.sh")
    )
    isaaclab_conda_prefix: Path = Path(
        os.getenv(
            "ROBOT_DATA_STUDIO_ISAACLAB_CONDA_PREFIX",
            WORKSPACE_ROOT / ".venvs" / "isaaclab",
        )
    )
    isaac_local_display: bool = os.getenv("ROBOT_DATA_STUDIO_ISAAC_LOCAL_DISPLAY", "0") == "1"
    isaac_robot_model: str = os.getenv("ROBOT_DATA_STUDIO_ISAAC_ROBOT_MODEL", "panda")
    isaac_fr3_usd: str = os.getenv("ROBOT_DATA_STUDIO_ISAAC_FR3_USD", "")
    public_ip: str = os.getenv("ROBOT_DATA_STUDIO_PUBLIC_IP", "127.0.0.1")
    isaac_signaling_port: int = int(os.getenv("ROBOT_DATA_STUDIO_ISAAC_SIGNALING_PORT", "49100"))
    isaac_media_port: int = int(os.getenv("ROBOT_DATA_STUDIO_ISAAC_MEDIA_PORT", "47998"))
    isaac_physics_backend: str = os.getenv("ROBOT_DATA_STUDIO_ISAAC_PHYSICS_BACKEND", "physx")
    isaac_franka_usd: str = os.getenv(
        "ROBOT_DATA_STUDIO_ISAAC_FRANKA_USD",
        "https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/5.1/Isaac/IsaacLab/Robots/FrankaEmika/panda_instanceable.usd",
    )
    isaac_l_table_basket_scene_usd: Path = Path(
        os.getenv(
            "ROBOT_DATA_STUDIO_ISAAC_L_TABLE_BASKET_SCENE_USD",
            PROJECT_ROOT
            / "assets"
            / "sources"
            / "robot-cloth-scenes-v1"
            / "scenes"
            / "fixtures_v4"
            / "place_in_basket"
            / "v001"
            / "scene.usda",
        )
    )
    lerobot_python: str = os.getenv("ROBOT_DATA_STUDIO_LEROBOT_PYTHON", sys.executable)
    openpi_root: Path = Path(os.getenv("ROBOT_DATA_STUDIO_OPENPI_ROOT", WORKSPACE_ROOT / "openpi"))
    openpi_python: str = os.getenv(
        "ROBOT_DATA_STUDIO_OPENPI_PYTHON", str(WORKSPACE_ROOT / "openpi" / ".venv" / "bin" / "python")
    )
    openpi_checkpoint: Path | None = (
        Path(os.environ["ROBOT_DATA_STUDIO_OPENPI_CHECKPOINT"]).expanduser()
        if os.environ.get("ROBOT_DATA_STUDIO_OPENPI_CHECKPOINT", "").strip() else None
    )
    openpi_config: str = os.getenv(
        "ROBOT_DATA_STUDIO_OPENPI_CONFIG", "pi05_franka_joint8_lora"
    )
    openpi_gpu_id: int | None = _optional_gpu("ROBOT_DATA_STUDIO_OPENPI_GPU_ID")
    openpi_inference_steps: int = int(
        os.getenv("ROBOT_DATA_STUDIO_OPENPI_INFERENCE_STEPS", "2")
    )
    fastwam_python: str = os.getenv(
        "ROBOT_DATA_STUDIO_FASTWAM_PYTHON",
        str(WORKSPACE_ROOT / ".venvs" / "lerobot-fastwam" / "bin" / "python"),
    )
    rlds_python: str = os.getenv("ROBOT_DATA_STUDIO_RLDS_PYTHON", sys.executable)
    robomimic_python: str = os.getenv(
        "ROBOT_DATA_STUDIO_ROBOMIMIC_PYTHON", str(WORKSPACE_ROOT / ".venvs" / "robomimic" / "bin" / "python")
    )


    def require_extension(self, extension: str) -> None:
        if extension not in self.enabled_extensions:
            raise ValueError(f"Extension '{extension}' is disabled; configure ROBOT_DATA_STUDIO_ENABLED_EXTENSIONS explicitly")


settings = Settings()
