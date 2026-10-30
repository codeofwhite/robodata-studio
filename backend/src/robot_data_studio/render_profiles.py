from __future__ import annotations

from pathlib import Path
import re

from robot_data_contracts.rendering import load_renderer_profile as load_contract_renderer_profile

from .config import settings


SAFE_PROFILE_ID = re.compile(r"^[a-z][a-z0-9_]*$")
SAFE_KIT_SETTINGS = {"/UJITSO/geometry", "/persistent/UJITSO/geometry"}


def renderer_profile_path(profile_id: str) -> Path:
    if not SAFE_PROFILE_ID.fullmatch(profile_id):
        raise ValueError("renderer profile id must be a simple lowercase identifier")
    root = settings.renderer_profile_root.resolve()
    path = (root / f"{profile_id}.json").resolve()
    if not path.is_relative_to(root):
        raise ValueError("renderer profile path escapes profile root")
    if not path.is_file():
        raise ValueError(f"unknown renderer profile: {profile_id}")
    return path


def load_renderer_profile(profile_id: str) -> dict:
    path = renderer_profile_path(profile_id)
    profile = load_contract_renderer_profile(path)
    if profile.id != profile_id:
        raise ValueError(f"renderer profile id does not match filename: {path}")
    unknown = sorted(set(profile.kit_settings) - SAFE_KIT_SETTINGS)
    if unknown:
        raise ValueError("renderer profile contains non-allowlisted Kit settings: " + ", ".join(unknown))
    return profile.model_dump(mode="json")


def renderer_profile_descriptors(profile_ids: tuple[str, ...]) -> list[dict]:
    return [
        {"id": profile["id"], "label": profile["label"], "description": profile["description"],
         "profile_version": profile["profile_version"], "rendering_mode": profile["rendering_mode"]}
        for profile in (load_renderer_profile(profile_id) for profile_id in profile_ids)
    ]


def validate_session_renderer_profile(profile_id: str) -> Path:
    load_renderer_profile(profile_id)
    return renderer_profile_path(profile_id)
