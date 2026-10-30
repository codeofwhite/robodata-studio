"""Append the audited ClothForge recipe without rewriting pilot evidence."""
from __future__ import annotations

import json
from pathlib import Path

from robot_data_contracts.asset import AssetArtifact, AssetDraft, AssetReference
from .asset_service import AssetRegistry, AssetIntegrityError, AssetConflict, fingerprint, file_digest

SOURCE = "clothforge-repair-v2"


def import_clothforge(registry: AssetRegistry, dry_run: bool = False) -> dict:
    root = Path(registry.sources()[SOURCE]["root"]).resolve()
    audit = json.loads((root / "acceptance.json").read_text())
    if audit.get("outcome") != "passed" or audit.get("verified_runs") != 48:
        raise AssetIntegrityError("ClothForge acceptance is incomplete")
    if file_digest(root / "scenario_recipe/recipe.json") != audit["recipe_sha256"]:
        raise AssetIntegrityError("ClothForge recipe changed after acceptance")
    evidence = {row["run"]: row["artifact_sha256"] for row in audit["checks"]}
    configs, validations = [], []
    for row in audit["results"]:
        folder = root / row["folder"]
        if root not in folder.resolve().parents:
            raise AssetIntegrityError("run folder escapes repair source")
        hashes = evidence[folder.name]
        artifacts = {}
        for name, sha in hashes.items():
            artifact = AssetArtifact(source_id=SOURCE, path=(folder / name).relative_to(root).as_posix(), sha256=sha)
            artifacts[name] = registry.inspect_artifact(artifact)
        result = json.loads((folder / "validation.json").read_text())
        if result["outcome"] != "passed" or result["failed_gates"] or result["trajectory_sha256"] != hashes["trajectory.npz"]:
            raise AssetIntegrityError("accepted run no longer matches its evidence")
        if any(result[key] != row[key] for key in result):
            raise AssetIntegrityError("acceptance row differs from original validation")
        request = json.loads((folder / "request.json").read_text())
        geometry = registry.get("MDL-clothforge-" + result["garment_id"], 1)
        material = registry.get("MAT-clothforge-" + result["material_id"], 1)
        for record in [geometry, material]:
            if registry.integrity(record)["status"] != "current":
                raise AssetIntegrityError("original model/material evidence changed")
        name = f"{geometry.name} · 中等材料 · {'悬挂' if result['scenario'] == 'hanging' else '落地'}"
        suffix = result["garment_id"] + "-" + result["material_id"] + "-" + result["scenario"]
        config_id = "CFG-clothforge-v2-" + suffix
        configs.append(AssetDraft(
            asset_id=config_id, kind="config", name=name,
            description="ClothForge 固定数值配置；通过范围仅为当前合成材料、场景及两秒保存帧检查。",
            tags=["clothforge", "repair-v2", geometry.data["category"], result["scenario"]], engines=["newton_vbd"],
            data={"runner": "clothforge", "garment_id": result["garment_id"], "scenario": result["scenario"],
                  "parameters": request["config"], "profile": request["profile"], "cohort": row["role"]},
            references=[AssetReference(asset_id=geometry.asset_id, version=1, role="geometry"),
                        AssetReference(asset_id=material.asset_id, version=1, role="material")],
            artifacts=[artifacts["request.json"].model_copy(update={"role": "configuration"})],
            change_note="Import audited repair configuration; original pilot configuration remains unchanged."))
        roles = {"validation.json": "metrics", "trajectory.npz": "trajectory", "replay.html": "interactive_replay",
                 "preview.png": "preview", "final.glb": "final_mesh", "request.json": "configuration",
                 "initialization.json": "initialization", "diagnostics.json": "diagnostics"}
        validations.append(AssetDraft(
            asset_id="VAL-clothforge-v2-" + suffix, kind="validation", name=name + " · 物理通过",
            description="已审计的真实 Newton 轨迹；单次物理检查通过不代表重复性、机器人任务或实物标定。",
            tags=["clothforge", "repair-v2", row["role"], result["scenario"]], engines=["newton_vbd"],
            data={**result, "cohort": row["role"], "source_trial": row["folder"]},
            references=[AssetReference(asset_id=config_id, version=1, role="tested_config")],
            artifacts=[artifacts[n].model_copy(update={"role": role}) for n, role in roles.items()],
            change_note="Append audited repair evidence; preserve every historical failure."))
    drafts = configs + validations
    if len(drafts) != 96 or len({d.asset_id for d in drafts}) != 96:
        raise AssetIntegrityError("expected 48 distinct config/validation pairs")
    # Complete the entire preflight before the first registry write.
    for draft in drafts:
        history = registry.versions(draft.asset_id)
        if history and (len(history) != 1 or history[0].content_sha256 != fingerprint(draft.model_dump(mode="json"))):
            raise AssetConflict("existing repair asset differs: " + draft.asset_id)
    if dry_run:
        return {"source": SOURCE, "dry_run": True, "configs": 48, "validations": 48, "created": 0}
    created = sum(registry.publish(d, expected_version=0, idempotent=True)[1] for d in drafts)
    return {"source": SOURCE, "configs": 48, "validations": 48, "created": created, "unchanged": len(drafts) - created}
