import pytest
from pydantic import ValidationError
from robot_data_contracts.asset import AssetArtifact, AssetDraft, AssetVersion


def draft(**kwargs):
    return AssetDraft(asset_id="MAT-cloth-test", kind="material", name="Cloth", change_note="Initial", **kwargs)


def test_identity_and_finite_parameters():
    with pytest.raises(ValidationError):
        AssetDraft(asset_id="SCN-test", kind="material", name="Mismatch", change_note="Initial")
    with pytest.raises(ValidationError):
        draft(data={"mass": float("nan")})
    with pytest.raises(ValidationError):
        draft(data={"mass": float("inf")})


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "folder/../x", "a//b", "C:/secret", "folder\\secret"])
def test_source_relative_paths_only(path):
    with pytest.raises(ValidationError):
        AssetArtifact(source_id="test", path=path)


def test_passed_label_requires_target_and_evidence():
    with pytest.raises(ValidationError):
        AssetDraft(asset_id="VAL-test", kind="validation", name="Unsupported claim", change_note="Initial", data={"outcome": "passed"})


def test_published_artifacts_require_fingerprints():
    body = draft(artifacts=[AssetArtifact(source_id="test", path="mesh.obj")]).model_dump()
    with pytest.raises(ValidationError):
        AssetVersion(**body, version=1, created_at="2026-09-17", content_sha256="0" * 64)
