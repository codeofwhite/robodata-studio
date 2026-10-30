from pathlib import Path

import pytest

from robot_data_studio.config import settings
from robot_data_studio.render_profiles import (
    load_renderer_profile,
    renderer_profile_descriptors,
    validate_session_renderer_profile,
)


def test_renderer_profiles_expose_only_supported_isaac_modes():
    ids = ("isaac_performance_v1", "isaac_balanced_v1", "isaac_quality_v1")
    descriptors = renderer_profile_descriptors(ids)
    assert [item["rendering_mode"] for item in descriptors] == ["performance", "balanced", "quality"]
    assert validate_session_renderer_profile("isaac_quality_v1").name == "isaac_quality_v1.json"


def test_renderer_profile_rejects_unknown_kit_setting(tmp_path):
    root = tmp_path / "profiles"; root.mkdir()
    (root / "unsafe_v1.json").write_text(
        '{"id":"unsafe_v1","label":"Unsafe","rendering_mode":"quality",'
        '"kit_settings":{"/arbitrary/setting":true}}'
    )
    original = settings.renderer_profile_root
    object.__setattr__(settings, "renderer_profile_root", root)
    try:
        with pytest.raises(ValueError, match="non-allowlisted"):
            load_renderer_profile("unsafe_v1")
    finally:
        object.__setattr__(settings, "renderer_profile_root", original)
