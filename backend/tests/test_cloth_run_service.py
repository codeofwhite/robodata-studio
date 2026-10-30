from __future__ import annotations

import json
from pathlib import Path

from robot_data_contracts.asset import AssetArtifact, AssetDraft
from robot_data_studio.services.asset_service import AssetRegistry
from robot_data_studio.services.cloth_run_service import ClothRunManager


def make_registry(tmp_path: Path):
    source = tmp_path / "source"
    runs = tmp_path / "runs"
    source.mkdir(); runs.mkdir()
    (source / "config.json").write_text("{}\n")
    sources = tmp_path / "sources.json"
    sources.write_text(json.dumps({"schema_version": 1, "sources": {
        "test": {"root": str(source)}, "studio-cloth-runs": {"root": str(runs)}}}))
    registry = AssetRegistry(tmp_path / "registry", sources)
    config, _ = registry.publish(AssetDraft(
        asset_id="CFG-textile_feeding__light", kind="config", name="Feed light", engines=["genesis"],
        data={"parameters": {"id": "textile_feeding", "task": "feed", "duration_s": 6.0}},
        artifacts=[AssetArtifact(source_id="test", path="config.json")], change_note="test"))
    return registry, config, runs


def test_completed_run_registers_exact_config_and_evidence(tmp_path):
    registry, config, runs = make_registry(tmp_path)
    manager = ClothRunManager(registry=registry, run_root=runs, runner_root=tmp_path, python="python")
    run_id = "run-20260917t120000z-1234abcd"
    directory = runs / run_id
    output = directory / "output"
    output.mkdir(parents=True)
    (output / "config.json").write_text("{}\n")
    (output / "trajectory.npz").write_bytes(b"trajectory")
    (output / "replay.mp4").write_bytes(b"video")
    (output / "evaluation.json").write_text(json.dumps({"status": "FAIL", "gates": {"finite": True, "task": False}, "metrics": {"com_shift_x_m": 0.01}, "limitation": "Cartesian gripper"}))
    log = directory / "run.log"; log.write_text("RESULT FAIL\n")
    state = {"run_id": run_id, "config_asset_id": config.asset_id, "config_version": config.version}
    validation = manager._publish_validation(state, output, log, 0)
    assert validation.data["outcome"] == "failed"
    assert validation.data["failed_gates"] == ["task"]
    assert validation.references[0].asset_id == config.asset_id
    assert validation.references[0].version == config.version
    assert {artifact.role for artifact in validation.artifacts} >= {"trajectory", "video", "evaluation", "log"}


def test_execution_failure_is_preserved_as_unavailable(tmp_path):
    registry, config, runs = make_registry(tmp_path)
    manager = ClothRunManager(registry=registry, run_root=runs, runner_root=tmp_path, python="python")
    run_id = "run-20260917t120001z-1234abcd"
    directory = runs / run_id; directory.mkdir()
    log = directory / "run.log"; log.write_text("CUDA error\n")
    state = {"run_id": run_id, "config_asset_id": config.asset_id, "config_version": config.version}
    validation = manager._publish_validation(state, directory / "output", log, 1, "CUDA error")
    assert validation.data["outcome"] == "unavailable"
    assert validation.data["failed_gates"] == ["execution_error"]
    assert validation.artifacts[0].role == "log"
