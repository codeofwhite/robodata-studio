import json

from robot_data_contracts.asset import AssetDraft, AssetReference
from robot_data_studio.services.asset_service import AssetRegistry, fingerprint
from robot_data_studio.services import asset_importers


def test_import_idempotence_and_exact_version_references(tmp_path, monkeypatch):
    config = tmp_path / "sources.json"
    config.write_text(json.dumps({"schema_version": 1, "sources": {}}))
    registry = AssetRegistry(tmp_path / "registry", config)
    # Exercise actual import transaction behavior with small synthetic records;
    # no simulator or real project data is accessed by this test.
    def drafts(_):
        for kind, count, prefix in [("scene", 8, "SCN"), ("material", 3, "MAT"), ("model", 24, "MDL"), ("config", 24, "CFG")]:
            for i in range(count):
                yield AssetDraft(asset_id=f"{prefix}-test-{i}", kind=kind, name="Test", change_note="Imported",
                    references=[AssetReference(asset_id="SCN-test-0", version=1, role="scene")] if kind == "config" else [])
        for i in range(144):
            # import_cloth counts kinds; schema validation already has separate tests.
            yield AssetDraft.model_construct(asset_id=f"VAL-test-{i}", kind="validation", name="Test", description="", tags=[], engines=[],
                data={"outcome": "unavailable", "engine_id": "test", "evaluator_version": "1", "scope": "test", "metrics": {}, "failed_gates": []},
                references=[AssetReference(asset_id="CFG-test-0", version=1, role="config")], artifacts=[], change_note="Imported")
    # Supply one real evidence file to satisfy publication invariants.
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}")
    config.write_text(json.dumps({"schema_version": 1, "sources": {"test": {"root": str(tmp_path)}}}))
    from robot_data_contracts.asset import AssetArtifact
    def valid_drafts(reg):
        for draft in drafts(reg):
            if draft.kind == "validation":
                draft = draft.model_copy(update={"artifacts": [AssetArtifact(source_id="test", path="evidence.json")]})
            yield draft
    monkeypatch.setattr(asset_importers, "cloth_drafts", valid_drafts)
    assert asset_importers.import_cloth(registry, dry_run=True)["total"] == 203
    assert not registry.root.exists()
    first = asset_importers.import_cloth(registry)
    assert first["created"] == 203
    second = asset_importers.import_cloth(registry)
    assert second["created"] == 0 and second["unchanged"] == 203
    assert registry.get("VAL-test-0").references[0].version == 1
    source_scene = registry.get("SCN-test-0")
    edited = AssetDraft.model_validate(source_scene.model_dump(include=set(AssetDraft.model_fields)))
    registry.publish(edited.model_copy(update={"name": "User edit", "change_note": "User update"}), expected_version=1)
    third = asset_importers.import_cloth(registry)
    assert third["created"] == 0 and third["unchanged"] == 203
    assert registry.get("SCN-test-0").name == "User edit"
    assert registry.get("CFG-test-0").references[0].version == 1


def test_json_formatting_and_parameter_change_have_distinct_semantics():
    a = json.loads('{"mass": 1, "friction": 0.5}')
    b = json.loads('{\n  "friction": 0.5,\n  "mass": 1\n}')
    assert fingerprint(a) == fingerprint(b)
    assert fingerprint(a) != fingerprint({**a, "mass": 2})


def test_visual_workstation_import_is_hashed_and_idempotent(tmp_path):
    source = tmp_path / "source"
    (source / "hdri").mkdir(parents=True)
    (source / "textures").mkdir()
    hdri = source / "hdri/photo_studio_01_4k.hdr"
    hdri.write_bytes(b"test-hdri")
    from robot_data_studio.services.asset_service import file_digest

    manifest = {
        "format": "robot_data_visual_asset_pack",
        "format_version": 1,
        "id": "household_workstation_v1",
        "label": "Test workstation",
        "units": "m",
        "up_axis": "Z",
        "entrypoint": "workstation.usda",
        "source": {"git_revision": "test", "license_status": "internal"},
        "composition": {"table_top_z_m": 0.76},
        "hdri": {
            "path": "hdri/photo_studio_01_4k.hdr",
            "sha256": file_digest(hdri),
        },
        "limitations": ["test fixture"],
    }
    (source / "asset_manifest.json").write_text(json.dumps(manifest))
    (source / "workstation.usda").write_text("#usda 1.0\n")
    (source / "source_scene.usda").write_text("#usda 1.0\n")
    for name in (
        "bread_color.png",
        "bread_normal.png",
        "fabric_normal.png",
        "floorwood_color.png",
        "oak_color.png",
        "walnut_color.png",
        "wood_normal.png",
    ):
        (source / "textures" / name).write_bytes(name.encode())
    sources = tmp_path / "sources.json"
    sources.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sources": {
                    "visual-workstation-v1": {"root": str(source)}
                },
            }
        )
    )
    registry = AssetRegistry(tmp_path / "registry", sources)

    dry_run = asset_importers.import_visual_workstation(registry, dry_run=True)
    assert dry_run == {
        "dry_run": True,
        "counts": {"scene": 1},
        "created": 0,
        "unchanged": 0,
        "total": 1,
    }
    first = asset_importers.import_visual_workstation(registry)
    second = asset_importers.import_visual_workstation(registry)
    assert first["created"] == 1 and first["version"] == 1
    assert second["created"] == 0 and second["unchanged"] == 1
    record = registry.get("SCN-household-workstation", 1)
    assert record.data["composition"]["table_top_z_m"] == 0.76
    assert len(record.artifacts) == 11
    assert all(artifact.sha256 for artifact in record.artifacts)


def test_bimanual_tabletop_import_is_separate_and_idempotent(tmp_path):
    source = tmp_path / "source"
    (source / "hdri").mkdir(parents=True)
    (source / "textures").mkdir()
    hdri = source / "hdri/photo_studio_01_4k.hdr"
    hdri.write_bytes(b"test-hdri")
    from robot_data_studio.services.asset_service import file_digest

    manifest = {
        "format": "robot_data_visual_asset_pack",
        "format_version": 1,
        "id": "bimanual_tabletop_v1",
        "label": "Test bimanual tabletop",
        "registry": {"asset_id": "SCN-bimanual-tabletop", "asset_version": 1},
        "units": "m",
        "up_axis": "Z",
        "entrypoint": "bimanual_tabletop.usda",
        "source": {"git_revision": "test", "license_status": "internal"},
        "composition": {
            "table_top_z_m": 0.76,
            "robot_layout": {"mode": "fixed_bimanual_visual_only"},
        },
        "hdri": {
            "path": "hdri/photo_studio_01_4k.hdr",
            "sha256": file_digest(hdri),
        },
        "limitations": ["visual only"],
    }
    (source / "asset_manifest_bimanual.json").write_text(json.dumps(manifest))
    (source / "bimanual_tabletop.usda").write_text("#usda 1.0\n")
    (source / "source_scene.usda").write_text("#usda 1.0\n")
    for name in ("oak_color.png", "walnut_color.png", "wood_normal.png"):
        (source / "textures" / name).write_bytes(name.encode())
    sources = tmp_path / "sources.json"
    sources.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sources": {
                    "visual-bimanual-tabletop-v1": {"root": str(source)}
                },
            }
        )
    )
    registry = AssetRegistry(tmp_path / "registry", sources)

    assert asset_importers.import_bimanual_tabletop(registry, dry_run=True)["total"] == 1
    first = asset_importers.import_bimanual_tabletop(registry)
    second = asset_importers.import_bimanual_tabletop(registry)
    assert first["created"] == 1 and first["version"] == 1
    assert second["created"] == 0 and second["unchanged"] == 1
    record = registry.get("SCN-bimanual-tabletop", 1)
    assert record.data["composition"]["robot_layout"]["mode"] == "fixed_bimanual_visual_only"
    assert len(record.artifacts) == 7
    assert all(artifact.sha256 for artifact in record.artifacts)
