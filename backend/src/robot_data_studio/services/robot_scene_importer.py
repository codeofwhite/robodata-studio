"""Import frozen static scene assets without rewriting historical revisions."""
import json
from pathlib import Path
from robot_data_contracts.asset import AssetDraft
from .asset_service import AssetRegistry, AssetConflict
SOURCE = "robot-cloth-scenes-v1"

def import_robot_scenes(registry: AssetRegistry, dry_run: bool = False) -> dict:
    source = registry.sources().get(SOURCE)
    if not source:
        raise ValueError("scene source is not configured")
    bundle = json.loads((Path(source["root"]) / "registry_manifest.json").read_text())
    if bundle.get("schema_version") != 1:
        raise ValueError("unsupported bundle schema")
    drafts = [AssetDraft.model_validate(item) for item in bundle["assets"]]
    by_id = {d.asset_id:d for d in drafts}
    if len(by_id) != len(drafts):
        raise ValueError("duplicate asset ID")
    for draft in drafts:
        for artifact in draft.artifacts:
            if artifact.sha256 is None or artifact.size_bytes is None:
                raise ValueError("frozen fingerprints required")
            registry.inspect_artifact(artifact)
        for ref in draft.references:
            if ref.asset_id in by_id:
                if ref.version != 1:
                    raise ValueError("bundle references must use v1")
            else:
                registry.get(ref.asset_id,ref.version)
        history = registry.versions(draft.asset_id)
        if history and not any(AssetDraft.model_validate(r.model_dump(include=set(AssetDraft.model_fields))) == draft for r in history):
            raise AssetConflict("existing asset differs: "+draft.asset_id)
    ordered=[]; visited=set(); pending=drafts[:]
    while pending:
        ready=[d for d in pending if all(r.asset_id not in by_id or r.asset_id in visited for r in d.references)]
        if not ready:raise ValueError("cyclic bundle references")
        for draft in ready:
            pending.remove(draft);visited.add(draft.asset_id);ordered.append(draft)
    if dry_run:return {"source":SOURCE,"dry_run":True,"assets":len(drafts),"created":0}
    created=unchanged=0
    for draft in ordered:
        _,changed=registry.publish(draft,expected_version=0,idempotent=True)
        created+=int(changed);unchanged+=int(not changed)
    return {"source":SOURCE,"assets":len(drafts),"created":created,"unchanged":unchanged}
