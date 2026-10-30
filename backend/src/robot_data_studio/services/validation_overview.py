from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import PurePosixPath
import json
from urllib.parse import quote

from robot_data_contracts.asset import AssetArtifact, AssetDraft
from .asset_service import AssetRegistry, AssetIntegrityError, is_video_artifact

# This threshold describes the existing repeated-run screen, not real-world reliability.
MIN_REPEATS = 3
ENGINES = ("genesis", "isaac_sim", "newton_vbd")
CLOTH_REPLAY_TRIALS = (
    "home_curtain__heavy/isaac/grasp_confirm02_r1",
    "home_curtain__medium/genesis/grasp_confirm02_r1",
    "home_dining__heavy/genesis/screening01_r1",
    "home_dining__heavy/isaac/screening01_r1",
    "home_dining__light/genesis/screening01_r1",
    "home_dining__light/isaac/screening01_r1",
    "home_dining__medium/genesis/screening01_r1",
    "home_dining__medium/isaac/screening01_r1",
    "textile_feeding__heavy/genesis/screening01_r1",
    "textile_feeding__light/genesis/screening01_r1",
    "textile_feeding__light/isaac/screening01_r1",
    "textile_feeding__medium/genesis/screening01_r1",
    "textile_feeding__medium/isaac/screening01_r1",
    "textile_folding__medium/genesis/screening01_r1",
    "textile_hanging__heavy/isaac/grasp_confirm02_r1",
    "textile_inspection__heavy/genesis/screening01_r1",
)


def _latest(records):
    result = {}
    for record in records:
        previous = result.get(record.asset_id)
        if previous is None or previous.version < record.version:
            result[record.asset_id] = record
    return result


def _failures(trials):
    counts = Counter(gate for trial in trials if trial["outcome"] == "failed"
                     for gate in set(trial["failed_gates"]))
    return [{"gate": gate, "count": count}
            for gate, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _group_status(trials):
    if not trials:
        return "unverified"
    if any(t["integrity"]["status"] != "current" for t in trials):
        return "stale"
    if any(t["outcome"] == "failed" for t in trials):
        return "failed"
    if any(t["outcome"] != "passed" for t in trials) or len(trials) < MIN_REPEATS:
        return "insufficient"
    return "passed"


def _engine_summary(trials):
    groups = defaultdict(list)
    for trial in trials:
        groups[(trial["evaluator_version"], trial["scope"], trial.get("scenario", ""))].append(trial)
    protocols = []
    for (evaluator, scope, scenario), members in sorted(groups.items()):
        protocols.append({"evaluator_version": evaluator, "scope": scope,
                          "scenario": scenario,
                          "passed": sum(t["outcome"] == "passed" for t in members),
                          "total": len(members), "status": _group_status(members)})
    status = "mixed" if len(protocols) > 1 else _group_status(trials)
    videos = [t for t in trials if (t["video"] is not None or t.get("replay") is not None) and t["integrity"]["status"] == "current"]
    # Prefer a recorded failure when available, then use a stable ID tie-breaker.
    videos.sort(key=lambda t: (t["outcome"] != "failed", t["asset_id"]))
    return {"passed": sum(t["outcome"] == "passed" for t in trials),
            "total": len(trials), "status": status, "protocols": protocols,
            "failures": _failures(trials), "representative": videos[0] if videos else None}


def validation_overview(registry: AssetRegistry):
    records = registry.all()
    lookup = {(r.asset_id, r.version): r for r in records}
    latest = _latest(records)
    validations = [r for r in latest.values() if r.kind == "validation"]
    by_config = defaultdict(dict)
    matched = set()
    for record in validations:
        for ref in record.references:
            target = lookup.get((ref.asset_id, ref.version))
            if ref.role == "tested_config" and target is not None and target.kind == "config":
                by_config[(ref.asset_id, ref.version)][record.asset_id] = record
                matched.add(record.asset_id)
    rows = []
    for config in sorted((r for r in latest.values() if r.kind == "config"), key=lambda r: r.asset_id):
        trials = []
        for record in by_config[(config.asset_id, config.version)].values():
            integrity = registry.integrity(record, lookup)
            video = next(({"url": "/assets/" + quote(record.asset_id, safe="") +
                           f"/versions/{record.version}/artifacts/{index}", "path": artifact.path}
                          for index, artifact in enumerate(record.artifacts)
                          if is_video_artifact(artifact.role, artifact.path)), None)
            replay = next(({"url": "/assets/" + quote(record.asset_id, safe="") +
                            f"/versions/{record.version}/artifacts/{index}/viewer", "path": artifact.path}
                           for index, artifact in enumerate(record.artifacts)
                           if artifact.role == "interactive_replay" and PurePosixPath(artifact.path).suffix.lower() == ".html"), None)
            trials.append({"asset_id": record.asset_id, "version": record.version,
                           "engine_id": record.data["engine_id"], "outcome": record.data["outcome"],
                           "evaluator_version": record.data["evaluator_version"], "scope": record.data["scope"],
                           "source_trial": record.data.get("source_trial", record.asset_id),
                           "failed_gates": record.data["failed_gates"], "integrity": integrity, "video": video,
                           "replay": replay, "scenario": record.data.get("scenario", "")})
        trials.sort(key=lambda t: (t["engine_id"], t["source_trial"], t["asset_id"]))
        engines = {engine: _engine_summary([t for t in trials if t["engine_id"] == engine])
                   for engine in sorted(set(ENGINES) | {t["engine_id"] for t in trials})}
        integrity = registry.integrity(config, lookup)
        states = {e: engines[e]["status"] for e in ENGINES}
        if integrity["status"] == "stale" or any(t["integrity"]["status"] == "stale" for t in trials):
            status = "stale"
        elif "mixed" in states.values():
            status = "mixed"
        elif states["genesis"] == states["isaac_sim"] == "passed":
            status = "both_passed"
        elif states["genesis"] == "passed":
            status = "genesis_only"
        elif states["isaac_sim"] == "passed":
            status = "isaac_only"
        elif states["newton_vbd"] == "passed":
            status = "newton_only"
        elif "failed" in states.values():
            status = "needs_repair"
        elif (states["newton_vbd"] == "insufficient" and engines["newton_vbd"]["total"] > 0
              and engines["newton_vbd"]["passed"] == engines["newton_vbd"]["total"]):
            status = "physics_passed"
        else:
            status = "unverified"
        failures = [dict(item, engine_id=engine) for engine, summary in engines.items()
                    for item in summary["failures"]]
        failures.sort(key=lambda f: (-f["count"], f["engine_id"], f["gate"]))
        historical_count = sum(len(members) for (asset_id, version), members in by_config.items()
                               if asset_id == config.asset_id and version != config.version)
        rows.append({"asset_id": config.asset_id, "version": config.version, "name": config.name,
                     "tags": config.tags, "status": status, "integrity": integrity,
                     "engines": engines, "failures": failures, "trials": trials,
                     "historical_count": historical_count})
    counts = Counter(row["status"] for row in rows)
    return {"items": rows, "summary": {
        "configs": len(rows), "ready": sum(counts[s] for s in ("both_passed", "genesis_only", "isaac_only", "newton_only")),
        "physics_checked": counts["physics_passed"],
        "needs_repair": counts["needs_repair"], "unverified": counts["unverified"],
        "stale": counts["stale"], "mixed": counts["mixed"],
        "validations": len(validations), "current_version_trials": sum(len(r["trials"]) for r in rows),
        "unlinked_validations": len(validations) - len(matched),
        "videos": sum(bool(t["video"]) for r in rows for t in r["trials"]),
        "configs_with_video": sum(any(t["video"] for t in r["trials"]) for r in rows),
        "interactive_replays": sum(bool(t["replay"]) for r in rows for t in r["trials"]),
    }, "minimum_repeats": MIN_REPEATS}


def link_validation_videos(registry: AssetRegistry, dry_run=False):
    """Append verified replay evidence to the explicitly scoped historical trials."""
    latest = _latest(registry.all())
    plans = []
    unchanged = []
    for suffix in CLOTH_REPLAY_TRIALS:
        trial_path = "runs/scenes/" + suffix
        candidates = [r for r in latest.values() if r.kind == "validation"
                      and "cloth-batch-v1" in r.tags and r.data.get("source_trial") == trial_path]
        if len(candidates) != 1:
            raise AssetIntegrityError("expected exactly one registered trial: " + trial_path)
        record = candidates[0]
        trajectory = next((a for a in record.artifacts
                           if a.role == "trajectory" and a.source_id == "cloth-batch-v1"
                           and a.path == trial_path + "/trajectory.npz"), None)
        if trajectory is None:
            raise AssetIntegrityError("missing registered trajectory: " + record.asset_id)
        registry.inspect_artifact(trajectory)
        provenance = registry.inspect_artifact(AssetArtifact(
            source_id=trajectory.source_id, path=trial_path + "/replay_provenance.json", role="video_provenance"))
        body = json.loads(registry.artifact_path(provenance).read_text())
        if (body.get("source") != "trajectory.npz" or body.get("physical_steps") != 0
                or body.get("trajectory_sha") != trajectory.sha256
                or record.data.get("trajectory_sha256") != trajectory.sha256):
            raise AssetIntegrityError("replay provenance does not match trial: " + record.asset_id)
        video = registry.inspect_artifact(AssetArtifact(
            source_id=trajectory.source_id, path=trial_path + "/replay.mp4", role="video"))
        added = [video, provenance]
        if all(artifact in record.artifacts for artifact in added):
            unchanged.append(record.asset_id)
            continue
        if record.version != 1 or any(a.role in ("video", "video_provenance") for a in record.artifacts):
            raise AssetIntegrityError("unexpected existing revision or video: " + record.asset_id)
        status = registry.integrity(record)
        if status["status"] != "current":
            raise AssetIntegrityError("stale trial: " + record.asset_id)
        draft = AssetDraft.model_validate(record.model_dump(include=set(AssetDraft.model_fields)))
        draft = draft.model_copy(update={"artifacts": [*draft.artifacts, *added],
                                         "change_note": "Link existing recorded-state replay and verified trajectory provenance; no new simulation or outcome change."})
        plans.append((record, draft))
    # All videos and source trajectories are checked before the first publication.
    created = []
    if not dry_run:
        for record, draft in plans:
            revision, _ = registry.publish(draft, expected_version=record.version)
            created.append({"asset_id": revision.asset_id, "version": revision.version})
    return {"dry_run": dry_run, "matched": len(CLOTH_REPLAY_TRIALS), "planned": len(plans),
            "created": created, "unchanged": unchanged,
            "planned_ids": [r.asset_id for r, _ in plans]}
