from __future__ import annotations

import shutil
import subprocess

from fastapi import APIRouter

from ..adapters import engine_descriptors
from ..config import settings


router = APIRouter(tags=["health"])


def _engine_available(engine_id: str) -> bool:
    if engine_id == "genesis":
        return settings.clothtwin_root.is_dir()
    if engine_id == "isaac_sim":
        return settings.gello_remote_root.is_dir() and settings.isaaclab_launcher.is_file()
    if engine_id == "roboverse":
        return settings.roboverse_root.is_dir() and settings.roboverse_python.is_file()
    return False


@router.get("/health")
def health():
    settings.data_root.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(settings.data_root)
    gpu = {"available": False, "devices": [], "detail": "nvidia-smi unavailable"}
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, check=True,
        )
        devices = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        gpu = {"available": bool(devices), "devices": devices, "detail": None}
    except (OSError, subprocess.SubprocessError) as error:
        gpu["detail"] = str(error)
    return {
        "status": "ok",
        "enabled_extensions": sorted(settings.enabled_extensions),
        "engines": [
            {
                **descriptor,
                "available": _engine_available(descriptor["id"]),
            }
            for descriptor in engine_descriptors()
        ],
        "disk": {"root": str(settings.data_root), "free_bytes": disk.free, "total_bytes": disk.total},
        "gpu": gpu,
    }
