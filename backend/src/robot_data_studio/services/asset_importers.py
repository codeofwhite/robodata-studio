"""Read-only source import; source experiments are never rewritten or rerun."""
from pathlib import Path
import json

from robot_data_contracts.asset import AssetArtifact, AssetDraft, AssetReference
from .asset_service import AssetRegistry, AssetNotFound, file_digest, fingerprint

SOURCE = "cloth-batch-v1"
VISUAL_WORKSTATION_SOURCE = "visual-workstation-v1"
BIMANUAL_TABLETOP_SOURCE = "visual-bimanual-tabletop-v1"
NOTE = "Import existing cloth-batch-v1 evidence; not a new simulation run."
VISUAL_WORKSTATION_NOTE = (
    "Register the packaged household workstation and its exact visual dependencies."
)
BIMANUAL_TABLETOP_NOTE = (
    "Register the fixed dual-Franka PBR tabletop and its exact visual dependencies."
)


def cloth_drafts(registry: AssetRegistry):
    root = Path(registry.sources()[SOURCE]["root"])
    catalog = json.loads((root / "catalog.json").read_text())
    materials = json.loads((root / "materials.json").read_text())
    report = json.loads((root / "runs/batch_report.json").read_text())
    if len(catalog["scenes"]) != 8 or len(materials["presets"]) != 3 or len(report["cases"]) != 24:
        raise ValueError("unexpected cloth-batch-v1 source cardinality")

    def artifact(path, role="source", expected=None):
        return registry.inspect_artifact(AssetArtifact(source_id=SOURCE, path=str(path), role=role, sha256=expected))

    def ref(asset_id, role):
        try:
            version = registry.get(asset_id).version
        except AssetNotFound:
            version = 1
        return AssetReference(asset_id=asset_id, version=version, role=role)

    for scene in catalog["scenes"]:
        yield AssetDraft(asset_id="SCN-" + scene["id"], kind="scene", name=scene["label"],
                         description="Cloth scene template; Cartesian jaws, not full-arm reachability evidence.",
                         tags=[scene["family"], scene["task"], SOURCE], engines=["genesis", "isaac_sim"],
                         data=scene, artifacts=[artifact("catalog.json")], change_note=NOTE)
    units = {"gsm": "g/m2", "thickness_m": "m", "young_pa": "Pa", "bend_multiplier": "1", "poisson": "1", "friction": "1", "color": "RGB"}
    for key, material in materials["presets"].items():
        yield AssetDraft(asset_id="MAT-cloth-" + key, kind="material", name=material["label"],
                         description="Synthetic engineering preset; not a calibrated physical fabric.",
                         tags=["synthetic", "uncalibrated", key], engines=["genesis", "isaac_sim"],
                         data={"calibrated": False, "parameters": {k: {"value": v, "unit": units.get(k, "")} for k, v in material.items() if k != "label"},
                               "backend_mapping": materials["mapping"], "parameter_ranges": materials["ranges"], "damping_support": materials["damping"]},
                         artifacts=[artifact("materials.json")], change_note=NOTE)
    for case in report["cases"]:
        cid = case["id"] + "__" + case["preset"]
        folder = Path("runs/scenes") / cid
        config = json.loads((root / folder / "config.json").read_text())
        manifest = json.loads((root / folder / "manifest.json").read_text())["files"]
        names = ["scene.blend", "scene_visual.glb", "cloth_rest.obj", "cloth_initial.obj", "mesh.npz", "furniture.json", "preview.png", "cloth_visual_texture.png", "visual_provenance.json"]
        yield AssetDraft(asset_id="MDL-" + cid, kind="model", name=case["label"] + " / " + case["preset"],
                         description="Versioned geometry bundle; visual GLB/Blend and native cloth mesh are separate artifacts.",
                         tags=[SOURCE, "geometry", case["preset"]], engines=["genesis", "isaac_sim"],
                         data={"model_type": "geometry_bundle", "units": "m", "formats": ["blend", "glb", "obj", "npz"], "controller": catalog["controller"]},
                         references=[ref("SCN-" + case["id"], "scene")],
                         artifacts=[artifact(str(folder / name), "preview" if name == "preview.png" else "model", manifest[name]) for name in names],
                         change_note=NOTE)
        yield AssetDraft(asset_id="CFG-" + cid, kind="config", name=case["label"] + " / " + case["preset"] + " config",
                         tags=[SOURCE, case["preset"]], engines=["genesis", "isaac_sim"],
                         data={"parameters": config, "parameters_sha256": fingerprint(config), "units": catalog["units"],
                               "runtime_grasp_attachments": catalog["runtime_grasp_attachments"]},
                         references=[ref("SCN-" + case["id"], "scene"), ref("MAT-cloth-" + case["preset"], "material"), ref("MDL-" + cid, "model")],
                         artifacts=[artifact(str(folder / "config.json"), "configuration")], change_note=NOTE)
        for source_engine, engine_case in case["engines"].items():
            engine = {"isaac": "isaac_sim", "genesis": "genesis"}[source_engine]
            for trial in engine_case["trials"]:
                run = folder / source_engine / trial["run"]
                run_config = json.loads((root / run / "config.json").read_text())
                if fingerprint(run_config) != fingerprint(config):
                    raise ValueError("validated config differs from catalog config: " + str(run))
                runtime = json.loads((root / run / "runtime.json").read_text())
                yield AssetDraft(asset_id="VAL-" + cid + "-" + source_engine + "-" + trial["run"], kind="validation",
                                 name=case["label"] + " / " + case["preset"] + " / " + source_engine + " / " + trial["run"],
                                 description="Imported historical trial. PASS and FAIL are preserved under the original evaluation rules.",
                                 tags=[SOURCE, trial["status"].lower()], engines=[engine],
                                 data={"outcome": {"PASS": "passed", "FAIL": "failed"}[trial["status"]],
                                       "engine_id": engine, "runtime": runtime, "evaluator_version": "cloth-batch-v1+interaction-audit-v2",
                                       "scope": "cartesian_cloth_interaction", "review_status": report["review_status"],
                                       "metrics": trial["metrics"], "failed_gates": trial["failed_gates"],
                                       "screening_status": trial["screening_status"], "interaction_audit": trial["interaction_audit"],
                                       "source_config_sha256": trial["config_sha"], "parameters_sha256": fingerprint(run_config),
                                       "trajectory_sha256": trial["trajectory_sha"],
                                       "source_trial": str(run), "limitations": report["limitations"]},
                                 references=[ref("CFG-" + cid, "tested_config")],
                                 artifacts=[artifact("runs/batch_report.json", "report"),
                                            artifact(str(run / "config.json"), "configuration", trial["config_sha"]),
                                            artifact(str(run / "trajectory.npz"), "trajectory", trial["trajectory_sha"]),
                                            artifact(str(run / "evaluation.json"), "screening"),
                                            artifact(str(run / "interaction_audit_v2.json"), "interaction"),
                                            artifact(str(run / "source_hashes.json"), "evaluator_source_hashes"),
                                            artifact(str(run / "runtime.json"), "runtime")], change_note=NOTE)


def import_cloth(registry: AssetRegistry, dry_run=False) -> dict:
    # Fully inspect evidence before the first write; publications remain individually
    # atomic and a retry resumes idempotently if interrupted between revisions.
    drafts = list(cloth_drafts(registry))
    counts = {kind: sum(d.kind == kind for d in drafts) for kind in ("scene", "material", "model", "config", "validation")}
    expected = {"scene": 8, "material": 3, "model": 24, "config": 24, "validation": 144}
    if counts != expected:
        raise ValueError("unexpected import counts: " + str(counts))
    if dry_run:
        return {"dry_run": True, "counts": counts, "total": len(drafts)}
    created = unchanged = 0
    imported_versions = {}
    for draft in drafts:
        # Bind dependencies to the imported source revision, not a user-edited latest revision.
        references = [r.model_copy(update={"version": imported_versions[r.asset_id]}) for r in draft.references]
        draft = draft.model_copy(update={"references": references})
        try:
            previous = registry.get(draft.asset_id).version
        except AssetNotFound:
            previous = 0
        record, changed = registry.publish(draft, expected_version=previous, idempotent=True)
        imported_versions[draft.asset_id] = record.version
        created += int(changed)
        unchanged += int(not changed)
    return {"dry_run": False, "counts": counts, "created": created, "unchanged": unchanged, "total": len(drafts)}


def visual_workstation_draft(registry: AssetRegistry) -> AssetDraft:
    """Build one immutable scene record from the portable workstation pack."""
    root = Path(registry.sources()[VISUAL_WORKSTATION_SOURCE]["root"])
    manifest = json.loads((root / "asset_manifest.json").read_text())
    if manifest.get("format") != "robot_data_visual_asset_pack":
        raise ValueError("unexpected visual workstation manifest format")
    if manifest.get("id") != "household_workstation_v1":
        raise ValueError("unexpected visual workstation manifest id")

    artifact_roles = {
        "asset_manifest.json": "manifest",
        "workstation.usda": "scene",
        "source_scene.usda": "source_scene",
        "hdri/photo_studio_01_4k.hdr": "hdri",
        "textures/bread_color.png": "texture",
        "textures/bread_normal.png": "texture",
        "textures/fabric_normal.png": "texture",
        "textures/floorwood_color.png": "texture",
        "textures/oak_color.png": "texture",
        "textures/walnut_color.png": "texture",
        "textures/wood_normal.png": "texture",
    }
    artifacts = [
        registry.inspect_artifact(
            AssetArtifact(
                source_id=VISUAL_WORKSTATION_SOURCE,
                path=path,
                role=role,
                sha256=(
                    manifest["hdri"]["sha256"]
                    if path == manifest["hdri"]["path"]
                    else None
                ),
            )
        )
        for path, role in artifact_roles.items()
    ]
    return AssetDraft(
        asset_id="SCN-household-workstation",
        kind="scene",
        name=manifest["label"],
        description=(
            "Portable Isaac Sim workstation composed from the simulation-demos "
            "dining-room USD, generated PBR textures, authored RectLights, and a "
            "versioned CC0 HDRI. Decorative room meshes are visual-only."
        ),
        tags=[
            VISUAL_WORKSTATION_SOURCE,
            "isaac-sim",
            "usd",
            "pbr",
            "hdri",
            "internal-source-license-unverified",
        ],
        engines=["isaac_sim"],
        data={
            "asset_type": "visual_workstation",
            "entrypoint": manifest["entrypoint"],
            "units": manifest["units"],
            "up_axis": manifest["up_axis"],
            "source": manifest["source"],
            "composition": manifest["composition"],
            "hdri": manifest["hdri"],
            "limitations": manifest["limitations"],
        },
        artifacts=artifacts,
        change_note=VISUAL_WORKSTATION_NOTE,
    )


def import_visual_workstation(
    registry: AssetRegistry, dry_run: bool = False
) -> dict:
    draft = visual_workstation_draft(registry)
    if dry_run:
        return {
            "dry_run": True,
            "counts": {"scene": 1},
            "created": 0,
            "unchanged": 0,
            "total": 1,
        }
    try:
        previous = registry.get(draft.asset_id).version
    except AssetNotFound:
        previous = 0
    record, changed = registry.publish(
        draft, expected_version=previous, idempotent=True
    )
    return {
        "dry_run": False,
        "counts": {"scene": 1},
        "created": int(changed),
        "unchanged": int(not changed),
        "total": 1,
        "asset_id": record.asset_id,
        "version": record.version,
    }


def bimanual_tabletop_draft(registry: AssetRegistry) -> AssetDraft:
    """Build the immutable static dual-Franka tabletop scene record."""
    root = Path(registry.sources()[BIMANUAL_TABLETOP_SOURCE]["root"])
    manifest_name = (
        "asset_manifest_bimanual_v15.json"
        if (root / "asset_manifest_bimanual_v15.json").is_file()
        else (
            "asset_manifest_bimanual_v14.json"
            if (root / "asset_manifest_bimanual_v14.json").is_file()
            else (
                "asset_manifest_bimanual_v13.json"
                if (root / "asset_manifest_bimanual_v13.json").is_file()
                else (
                    "asset_manifest_bimanual_v12.json"
                    if (root / "asset_manifest_bimanual_v12.json").is_file()
                    else (
                        "asset_manifest_bimanual_v11.json"
                        if (root / "asset_manifest_bimanual_v11.json").is_file()
                        else (
                            "asset_manifest_bimanual_v10.json"
                            if (root / "asset_manifest_bimanual_v10.json").is_file()
                            else (
                                "asset_manifest_bimanual_v9.json"
                                if (root / "asset_manifest_bimanual_v9.json").is_file()
                                else (
                                    "asset_manifest_bimanual_v8.json"
                                    if (root / "asset_manifest_bimanual_v8.json").is_file()
                                    else (
                                        "asset_manifest_bimanual_v7.json"
                                        if (root / "asset_manifest_bimanual_v7.json").is_file()
                                        else (
                                            "asset_manifest_bimanual_v6.json"
                                            if (root / "asset_manifest_bimanual_v6.json").is_file()
                                            else (
                                                "asset_manifest_bimanual_v5.json"
                                                if (root / "asset_manifest_bimanual_v5.json").is_file()
                                                else (
                                                    "asset_manifest_bimanual_v4.json"
                                                    if (root / "asset_manifest_bimanual_v4.json").is_file()
                                                    else (
                                                        "asset_manifest_bimanual_v3.json"
                                                        if (root / "asset_manifest_bimanual_v3.json").is_file()
                                                        else (
                                                            "asset_manifest_bimanual_v2.json"
                                                            if (root / "asset_manifest_bimanual_v2.json").is_file()
                                                            else "asset_manifest_bimanual.json"
                                                        )
                                                    )
                                                )
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
            )
        )
    )
    if (root / "asset_manifest_bimanual_v16.json").is_file():
        manifest_name = "asset_manifest_bimanual_v16.json"
    if (root / "asset_manifest_bimanual_v17.json").is_file():
        manifest_name = "asset_manifest_bimanual_v17.json"
    manifest = json.loads((root / manifest_name).read_text())
    if manifest.get("format") != "robot_data_visual_asset_pack":
        raise ValueError("unexpected bimanual tabletop manifest format")
    if manifest.get("id") not in {
        "bimanual_tabletop_v1",
        "bimanual_tabletop_v2",
        "bimanual_tabletop_v3",
        "bimanual_tabletop_v4",
        "bimanual_tabletop_v5",
        "bimanual_tabletop_v6",
        "bimanual_tabletop_v7",
        "bimanual_tabletop_v8",
        "bimanual_tabletop_v9",
        "bimanual_tabletop_v10",
        "bimanual_tabletop_v11",
        "bimanual_tabletop_v12",
        "bimanual_tabletop_v13",
        "bimanual_tabletop_v14",
        "bimanual_tabletop_v15",
        "bimanual_tabletop_v16",
        "bimanual_tabletop_v17",
    }:
        raise ValueError("unexpected bimanual tabletop manifest id")

    artifact_roles = {
        manifest_name: "manifest",
        manifest["entrypoint"]: "scene",
        manifest["hdri"]["path"]: "hdri",
    }
    if manifest["id"] not in {"bimanual_tabletop_v16", "bimanual_tabletop_v17"}:
        artifact_roles.update({
            "source_scene.usda": "source_scene",
            "textures/oak_color.png": "texture",
            "textures/walnut_color.png": "texture",
            "textures/wood_normal.png": "texture",
        })
    if manifest["id"] in {"bimanual_tabletop_v16", "bimanual_tabletop_v17"}:
        preview_dir = f"previews/bimanual_lab_v{manifest['registry']['asset_version']}"
        artifact_roles[f"{preview_dir}/base.jpg"] = "preview"
        for camera in ("top", "left", "right"):
            artifact_roles[f"{preview_dir}/{camera}.jpg"] = f"preview_{camera}"
        for camera in ("base", "top", "left", "right"):
            artifact_roles[f"{preview_dir}/{camera}.mp4"] = "video"
        artifact_roles[f"{preview_dir}/provenance.json"] = "visual_validation"
    recorded_pose = manifest.get("composition", {}).get("recorded_visual_pose")
    if recorded_pose is not None:
        artifact_roles[recorded_pose["path"]] = "recorded_visual_pose"
    artifacts = [
        registry.inspect_artifact(
            AssetArtifact(
                source_id=BIMANUAL_TABLETOP_SOURCE,
                path=path,
                role=role,
                sha256=(
                    manifest["hdri"]["sha256"]
                    if path == manifest["hdri"]["path"]
                    else None
                ),
            )
        )
        for path, role in artifact_roles.items()
    ]
    return AssetDraft(
        asset_id=manifest["registry"]["asset_id"],
        kind="scene",
        name=manifest["label"],
        description=(
            "Static dual-Franka laboratory bench with fully supported mounting plates. "
            "Dimensions are nominal estimates from reference photographs. Robot control "
            "and episode contracts remain single-arm."
            if manifest["id"] in {"bimanual_tabletop_v16", "bimanual_tabletop_v17"}
            else "Static dual-Franka visual workstation using the source PBR table and legs."
        ),
        tags=[
            BIMANUAL_TABLETOP_SOURCE,
            "isaac-sim",
            "usd",
            "pbr",
            "dual-franka",
            "static-visual-layout",
            "internal-source-license-unverified",
        ],
        engines=["isaac_sim"],
        data={
            "asset_type": "bimanual_tabletop_visual",
            "entrypoint": manifest["entrypoint"],
            "units": manifest["units"],
            "up_axis": manifest["up_axis"],
            "source": manifest["source"],
            "composition": manifest["composition"],
            "hdri": manifest["hdri"],
            "limitations": manifest["limitations"],
        },
        artifacts=artifacts,
        change_note=BIMANUAL_TABLETOP_NOTE,
    )


def import_bimanual_tabletop(
    registry: AssetRegistry, dry_run: bool = False
) -> dict:
    draft = bimanual_tabletop_draft(registry)
    if dry_run:
        return {
            "dry_run": True,
            "counts": {"scene": 1},
            "created": 0,
            "unchanged": 0,
            "total": 1,
        }
    try:
        previous = registry.get(draft.asset_id).version
    except AssetNotFound:
        previous = 0
    record, changed = registry.publish(
        draft, expected_version=previous, idempotent=True
    )
    return {
        "dry_run": False,
        "counts": {"scene": 1},
        "created": int(changed),
        "unchanged": int(not changed),
        "total": 1,
        "asset_id": record.asset_id,
        "version": record.version,
    }
