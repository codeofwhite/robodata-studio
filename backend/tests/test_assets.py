import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from robot_data_contracts.asset import AssetArtifact, AssetDraft, AssetReference
from types import SimpleNamespace
from robot_data_studio.routes.assets import router
from robot_data_studio.services.asset_service import AssetRegistry, AssetConflict, AssetIntegrityError, AssetNotFound


@pytest.fixture
def registry(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "material.json").write_text('{"mass": 1}\n')
    config = tmp_path / "sources.json"
    config.write_text(json.dumps({"schema_version": 1, "sources": {"test": {"root": str(source)}}}))
    return AssetRegistry(tmp_path / "registry", config)


def material(registry, **updates):
    body = dict(asset_id="MAT-test", kind="material", name="Test fabric", change_note="Initial",
                artifacts=[AssetArtifact(source_id="test", path="material.json")], data={"parameters": {"mass": 1}})
    body.update(updates)
    return AssetDraft(**body)


def test_immutable_revisions_and_no_evidence_inheritance(registry):
    first, _ = registry.publish(material(registry))
    config, _ = registry.publish(AssetDraft(asset_id="CFG-test", kind="config", name="Config", change_note="Initial",
                                           references=[AssetReference(asset_id=first.asset_id, version=1, role="material")]))
    validation, _ = registry.publish(AssetDraft(asset_id="VAL-test", kind="validation", name="Prior result", change_note="Initial",
        references=[AssetReference(asset_id=config.asset_id, version=1, role="tested_config")], artifacts=first.artifacts,
        data={"outcome": "passed", "scope": "fixture", "engine_id": "newton", "evaluator_version": "1", "metrics": {}, "failed_gates": []}))
    original = (registry.root / first.asset_id / "v000001.json").read_bytes()
    second, _ = registry.publish(material(registry, change_note="Changed mass", data={"parameters": {"mass": 2}}), expected_version=1)
    assert second.version == 2
    assert (registry.root / first.asset_id / "v000001.json").read_bytes() == original
    assert registry.detail(first.asset_id, 2)["referenced_by"] == []
    assert registry.get(config.asset_id).references[0].version == 1
    assert registry.get(validation.asset_id).references[0].version == 1
    with pytest.raises(AssetConflict):
        registry.publish(material(registry), expected_version=1)


def test_missing_reference_and_concurrent_publication(registry):
    with pytest.raises(AssetNotFound):
        registry.publish(material(registry, references=[AssetReference(asset_id="SCN-missing", version=1, role="scene")]))
    def publish():
        try:
            registry.publish(material(registry))
            return "ok"
        except AssetConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: publish(), range(2)))
    assert sorted(results) == ["conflict", "ok"]
    assert len(registry.versions("MAT-test")) == 1


def test_stale_dependencies_and_corrupt_record(registry):
    record, _ = registry.publish(material(registry))
    config, _ = registry.publish(AssetDraft(asset_id="CFG-test", kind="config", name="Config", change_note="Initial",
                                           references=[AssetReference(asset_id=record.asset_id, version=1, role="material")]))
    path = registry.artifact_path(record.artifacts[0])
    path.write_text('{"mass": 2}\n')
    assert registry.integrity(config)["status"] == "stale"
    assert registry.catalog(integrity="stale")["total"] == 2
    saved = registry.root / record.asset_id / "v000001.json"
    body = json.loads(saved.read_text())
    body["name"] = "Tampered"
    saved.write_text(json.dumps(body))
    with pytest.raises(AssetIntegrityError):
        registry.get(record.asset_id)


def test_symlink_escape_and_mismatched_hash_rejected(registry, tmp_path):
    source = registry.artifact_path(AssetArtifact(source_id="test", path="material.json")).parent
    secret = tmp_path / "outside.json"
    secret.write_text("{}")
    (source / "escape.json").symlink_to(secret)
    with pytest.raises(ValueError, match="escapes"):
        registry.inspect_artifact(AssetArtifact(source_id="test", path="escape.json"))
    with pytest.raises(AssetIntegrityError):
        registry.inspect_artifact(AssetArtifact(source_id="test", path="material.json", sha256="0" * 64))


def test_api_search_versions_and_download_integrity(registry, monkeypatch):
    monkeypatch.setattr("robot_data_studio.services.asset_service.settings", SimpleNamespace(asset_root=registry.root, asset_sources_file=registry.sources_file))
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as client:
        response = client.post("/api/assets", json={"draft": material(registry, engines=["newton"]).model_dump(), "expected_version": 0})
        assert response.status_code == 201, response.text
        assert client.get("/api/assets", params={"q": "fabric", "kind": "material", "engine": "newton"}).json()["total"] == 1
        assert client.get("/api/assets?offset=-1").status_code == 422
        assert client.get("/api/assets/MAT-test?version=1").json()["record"]["version"] == 1
        assert client.post("/api/assets", json={"draft": material(registry).model_dump()}).status_code == 409
        url = "/api/assets/MAT-test/versions/1/artifacts/0"
        assert client.get(url).status_code == 200
        registry.artifact_path(AssetArtifact(source_id="test", path="material.json")).write_text("changed")
        assert client.get(url).status_code == 422
        assert client.get("/api/assets/MAT-test").json()["integrity"]["status"] == "stale"
