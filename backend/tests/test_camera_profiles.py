import json

import pytest

from robot_data_studio.camera_profiles import load_camera_profile, validate_session_camera_profile
from robot_data_studio.config import settings


def test_lab_d435i_profile_has_two_active_roles_and_one_inactive_inventory_camera():
    profile = load_camera_profile("lab_d435i_dual_v1")
    assert profile["match_level"] == "nominal_pending_intrinsics"
    assert profile["roles"]["agentview"]["calibration_source_serial"] == "261722075807"
    assert profile["roles"]["wrist"]["calibration_source_serial"] == "261622075579"
    assert [item["serial"] for item in profile["inventory"] if not item["active"]] == ["261622078553"]


def test_profile_rejects_resolution_mismatch():
    with pytest.raises(ValueError, match="requires one shared resolution"):
        validate_session_camera_profile("lab_d435i_dual_v1", width=1280, height=720)


def test_synthetic_roboverse_profile_can_have_one_enabled_role():
    profile = load_camera_profile("roboverse_sapien_base_v1")
    assert list(profile["roles"]) == ["agentview"]
    assert profile["roles"]["agentview"]["calibration_source_serial"] is None
    assert validate_session_camera_profile(
        "roboverse_sapien_base_v1", width=640, height=480
    ).name == "roboverse_sapien_base_v1.json"


def test_calibrated_match_level_requires_intrinsics(tmp_path):
    source = load_camera_profile("lab_d435i_dual_v1")
    source["id"] = "invalid_calibrated"
    source["match_level"] = "intrinsics_matched"
    root = tmp_path / "profiles"
    root.mkdir()
    (root / "invalid_calibrated.json").write_text(json.dumps(source), encoding="utf-8")
    original = settings.camera_profile_root
    object.__setattr__(settings, "camera_profile_root", root)
    try:
        with pytest.raises(ValueError, match="requires calibrated intrinsics"):
            load_camera_profile("invalid_calibrated")
    finally:
        object.__setattr__(settings, "camera_profile_root", original)
