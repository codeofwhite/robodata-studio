import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from robot_data_contracts.asset import AssetArtifact, AssetDraft, AssetReference
from robot_data_studio.routes.assets import router
from robot_data_studio.services.asset_service import AssetRegistry, AssetIntegrityError
from robot_data_studio.services.validation_overview import validation_overview, link_validation_videos


@pytest.fixture
def registry(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "evidence.json").write_text("{}")
    sources = tmp_path / "sources.json"
    sources.write_text(json.dumps({"schema_version": 1, "sources": {"cloth-batch-v1": {"root": str(source)}}}))
    return AssetRegistry(tmp_path / "registry", sources)


def config(registry, version=1):
    return registry.publish(AssetDraft(asset_id="CFG-test", kind="config", name="Test configuration",
        change_note="Test", data={"revision": version}), expected_version=version - 1)[0]


def trial(registry, index, engine="genesis", outcome="passed", config_version=1, evaluator="v1", **kwargs):
    body = dict(asset_id=f"VAL-test-{index}", kind="validation", name=f"Trial {index}", change_note="Test",
        references=[AssetReference(asset_id="CFG-test", version=config_version, role="tested_config")],
        artifacts=[AssetArtifact(source_id="cloth-batch-v1", path="evidence.json", role="report")],
        data={"engine_id": engine, "outcome": outcome, "scope": "test", "evaluator_version": evaluator,
              "metrics": {}, "failed_gates": ["task", "task"] if outcome == "failed" else []})
    body.update(kwargs)
    return registry.publish(AssetDraft(**body))[0]


def test_latest_revision_is_one_trial_and_config_upgrade_does_not_inherit(registry):
    config(registry)
    first = trial(registry, 1)
    trial(registry, 2)
    trial(registry, 3)
    draft = AssetDraft.model_validate(first.model_dump(include=set(AssetDraft.model_fields)))
    registry.publish(draft.model_copy(update={"change_note": "Added evidence"}), expected_version=1)
    overview = validation_overview(registry)
    row = overview["items"][0]
    assert row["engines"]["genesis"]["passed"] == row["engines"]["genesis"]["total"] == 3
    assert row["status"] == "genesis_only"
    assert overview["summary"]["validations"] == 3
    config(registry, 2)
    row = validation_overview(registry)["items"][0]
    assert row["version"] == 2
    assert row["status"] == "unverified"
    assert row["trials"] == []
    assert row["historical_count"] == 3


def test_protocols_do_not_combine_and_gate_counts_are_per_trial(registry):
    config(registry)
    trial(registry, 1)
    trial(registry, 2)
    trial(registry, 3, evaluator="v2")
    trial(registry, 4, engine="isaac_sim", outcome="failed")
    row = validation_overview(registry)["items"][0]
    assert row["status"] == "mixed"
    assert row["engines"]["genesis"]["status"] == "mixed"
    assert len(row["engines"]["genesis"]["protocols"]) == 2
    assert all(p["status"] == "insufficient" for p in row["engines"]["genesis"]["protocols"])
    assert row["engines"]["isaac_sim"]["failures"] == [{"gate": "task", "count": 1}]


def test_insufficient_unavailable_and_stale_do_not_become_ready(registry):
    config(registry)
    trial(registry, 1)
    trial(registry, 2)
    assert validation_overview(registry)["items"][0]["status"] == "unverified"
    trial(registry, 3, outcome="unavailable")
    assert validation_overview(registry)["summary"]["ready"] == 0
    registry.artifact_path(AssetArtifact(source_id="cloth-batch-v1", path="evidence.json")).write_text("changed")
    row = validation_overview(registry)["items"][0]
    assert row["status"] == "stale"
    assert row["engines"]["genesis"]["passed"] == 2


def test_both_engines_and_failed_repeats(registry):
    config(registry)
    for index in range(3):
        trial(registry, index)
        trial(registry, index + 3, engine="isaac_sim")
    assert validation_overview(registry)["items"][0]["status"] == "both_passed"
    trial(registry, 6, engine="isaac_sim", outcome="failed")
    row = validation_overview(registry)["items"][0]
    assert row["status"] == "genesis_only"
    assert row["engines"]["isaac_sim"]["passed"] == 3
    assert row["engines"]["isaac_sim"]["total"] == 4


def replay_trial(registry, monkeypatch, suffix="demo/genesis/r1"):
    monkeypatch.setattr("robot_data_studio.services.validation_overview.CLOTH_REPLAY_TRIALS", (suffix,))
    root = registry.artifact_path(AssetArtifact(source_id="cloth-batch-v1", path="evidence.json")).parent
    directory = root / "runs/scenes" / suffix
    directory.mkdir(parents=True)
    (directory / "trajectory.npz").write_bytes(b"recorded physical trajectory")
    (directory / "replay.mp4").write_bytes(b"0123456789video")
    trajectory = registry.inspect_artifact(AssetArtifact(source_id="cloth-batch-v1",
        path=f"runs/scenes/{suffix}/trajectory.npz", role="trajectory"))
    (directory / "replay_provenance.json").write_text(json.dumps({
        "source": "trajectory.npz", "physical_steps": 0, "trajectory_sha": trajectory.sha256}))
    record = trial(registry, 1, tags=["cloth-batch-v1"], artifacts=[trajectory],
        data={"engine_id": "genesis", "outcome": "failed", "scope": "test", "evaluator_version": "v1",
              "metrics": {}, "failed_gates": ["task"], "trajectory_sha256": trajectory.sha256,
              "source_trial": f"runs/scenes/{suffix}"})
    return record, directory


def test_video_link_is_preflighted_versioned_and_idempotent(registry, monkeypatch):
    config(registry)
    record, directory = replay_trial(registry, monkeypatch)
    before = (registry.root / record.asset_id / "v000001.json").read_bytes()
    report = link_validation_videos(registry, dry_run=True)
    assert report["planned"] == 1
    assert len(registry.versions(record.asset_id)) == 1
    report = link_validation_videos(registry)
    assert report["created"] == [{"asset_id": record.asset_id, "version": 2}]
    assert (registry.root / record.asset_id / "v000001.json").read_bytes() == before
    assert registry.get(record.asset_id).data == record.data
    assert link_validation_videos(registry)["created"] == []
    row = validation_overview(registry)["items"][0]
    assert len(row["trials"]) == 1
    assert row["engines"]["genesis"]["representative"]["outcome"] == "failed"
    (directory / "replay.mp4").write_bytes(b"changed")
    row = validation_overview(registry)["items"][0]
    assert row["status"] == "stale"
    assert row["engines"]["genesis"]["representative"] is None


def test_wrong_video_provenance_rejects_without_new_revision(registry, monkeypatch):
    config(registry)
    record, directory = replay_trial(registry, monkeypatch)
    (directory / "replay_provenance.json").write_text(json.dumps({
        "source": "trajectory.npz", "physical_steps": 0, "trajectory_sha": "0" * 64}))
    with pytest.raises(AssetIntegrityError, match="does not match"):
        link_validation_videos(registry)
    assert len(registry.versions(record.asset_id)) == 1


def test_overview_route_and_video_mime_range_and_integrity(registry, monkeypatch):
    config(registry)
    record, directory = replay_trial(registry, monkeypatch)
    link_validation_videos(registry)
    monkeypatch.setattr("robot_data_studio.services.asset_service.settings",
        SimpleNamespace(asset_root=registry.root, asset_sources_file=registry.sources_file))
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as client:
        response = client.get("/api/assets/validation-overview")
        assert response.status_code == 200
        assert response.json()["summary"]["validations"] == 1
        url = "/api" + response.json()["items"][0]["trials"][0]["video"]["url"]
        video = client.get(url)
        assert video.headers["content-type"] == "video/mp4"
        assert "attachment" not in video.headers.get("content-disposition", "")
        ranged = client.get(url, headers={"Range": "bytes=0-3"})
        assert ranged.status_code == 206
        assert ranged.content == b"0123"
        (directory / "replay.mp4").write_bytes(b"changed")
        assert client.get(url).status_code == 422


def test_newton_single_pass_is_distinct_from_repeated_validation(registry):
    config(registry)
    trial(registry, 1, engine='newton_vbd')
    overview = validation_overview(registry)
    assert overview['items'][0]['status'] == 'physics_passed'
    assert overview['summary']['physics_checked'] == 1 and overview['summary']['ready'] == 0
    trial(registry, 2, engine='newton_vbd')
    trial(registry, 3, engine='newton_vbd')
    assert validation_overview(registry)['items'][0]['status'] == 'newton_only'
    trial(registry, 4, engine='newton_vbd', outcome='failed')
    assert validation_overview(registry)['items'][0]['status'] == 'needs_repair'
