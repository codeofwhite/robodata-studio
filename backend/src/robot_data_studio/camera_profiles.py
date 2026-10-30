from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from robot_data_contracts.camera import load_camera_profile as load_contract_camera_profile

from .config import settings


SAFE_PROFILE_ID = re.compile(r"^[a-z][a-z0-9_]*$")
def camera_profile_path(profile_id: str) -> Path:
    if not SAFE_PROFILE_ID.fullmatch(profile_id):
        raise ValueError("camera profile id must be a simple lowercase identifier")
    path = (settings.camera_profile_root / f"{profile_id}.json").resolve()
    if not path.is_relative_to(settings.camera_profile_root.resolve()):
        raise ValueError("camera profile path escapes profile root")
    if not path.is_file():
        raise ValueError(f"unknown camera profile: {profile_id}")
    return path


def load_camera_profile(profile_id: str) -> dict[str, Any]:
    path = camera_profile_path(profile_id)
    profile = load_contract_camera_profile(path)
    if profile.id != profile_id:
        raise ValueError(f"camera profile id does not match filename: {path}")
    enabled_roles = {
        role_name: role for role_name, role in profile.roles.items() if role.enabled
    }
    if not enabled_roles:
        raise ValueError("camera profile must define at least one enabled role")
    for role_name, role in enabled_roles.items():
        if not role.model:
            raise ValueError(f"camera role {role_name} is incomplete")
        if profile.match_level == "sensor_matched" and not role.calibration_source_serial:
            raise ValueError(f"sensor-matched camera role {role_name} requires a serial")
    return profile.model_dump(mode="json")


def camera_profile_descriptors(profile_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            "id": profile["id"],
            "label": profile["label"],
            "match_level": profile["match_level"],
            "roles": [role for role, entry in profile["roles"].items() if entry.get("enabled")],
        }
        for profile in (load_camera_profile(profile_id) for profile_id in profile_ids)
    ]


def validate_session_camera_profile(profile_id: str, *, width: int, height: int) -> Path:
    profile = load_camera_profile(profile_id)
    expected = {
        (int(entry["stream"]["width"]), int(entry["stream"]["height"]))
        for entry in profile["roles"].values()
        if entry.get("enabled")
    }
    if expected != {(width, height)}:
        raise ValueError(
            f"camera profile {profile_id} requires one shared resolution {sorted(expected)}, got {(width, height)}"
        )
    return camera_profile_path(profile_id)
