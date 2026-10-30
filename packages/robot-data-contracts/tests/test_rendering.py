import json

import pytest

from robot_data_contracts.rendering import load_renderer_profile, renderer_profile_metadata


def test_renderer_profile_is_strict_and_hashes_source(tmp_path):
    path = tmp_path / "quality.json"
    path.write_text(json.dumps({
        "format": "robot_data_renderer_profile", "format_version": 1, "profile_version": 1,
        "id": "isaac_quality_v1", "label": "Quality", "engine_id": "isaac_sim",
        "rendering_mode": "quality", "kit_settings": {"/UJITSO/geometry": False},
    }))
    profile = load_renderer_profile(path)
    metadata = renderer_profile_metadata(profile, source=path)
    assert metadata["rendering_mode"] == "quality"
    assert len(metadata["profile_sha256"]) == 64
    path.write_text(path.read_text().replace("Quality", "Changed"))
    assert renderer_profile_metadata(load_renderer_profile(path), source=path)["profile_sha256"] != metadata["profile_sha256"]


def test_renderer_profile_rejects_path_tracing(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"id": "bad", "label": "Bad", "rendering_mode": "pathtracing"}))
    with pytest.raises(ValueError, match="rendering_mode"):
        load_renderer_profile(path)
