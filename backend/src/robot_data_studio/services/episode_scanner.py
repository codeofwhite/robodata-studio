from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from robot_data_contracts.validation import inspect_episode

from ..adapters import canonical_engine_id
from ..db import transaction
from .session_service import get_session


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_trajectory(manifest: dict) -> str | None:
    scene = manifest.get("scene")
    if not isinstance(scene, dict):
        return None
    parameters = scene.get("parameters")
    if not isinstance(parameters, dict):
        return None
    source = parameters.get("source_demo_trajectory")
    return source if isinstance(source, str) and source else None


def scan_session(session_id: str) -> dict:
    session = get_session(session_id)
    if not session:
        raise KeyError(session_id)
    if session["status"] == "trashed":
        raise ValueError("restore the session before scanning episodes")
    root = Path(session["config"]["episode_root"]).resolve()
    indexed = skipped = invalid = 0
    invalid_episodes: list[dict[str, str]] = []
    for manifest_path in sorted(root.glob("episode_*/manifest.json")):
        try:
            episode = inspect_episode(manifest_path, engine_id=session["engine_id"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            invalid += 1
            invalid_episodes.append({"path": str(manifest_path.parent), "error": str(error)})
            continue
        with transaction() as connection:
            existing = connection.execute(
                "SELECT id FROM episodes WHERE episode_uuid = ?", (episode.episode_uuid,)
            ).fetchone()
            if existing:
                skipped += 1
                continue
            connection.execute(
                """INSERT INTO episodes(session_id, episode_uuid, path, task, operator_success,
                   auto_success, qa_status, failure_reason, num_frames, manifest_json, created_at, indexed_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    episode.episode_uuid,
                    str(manifest_path.parent.resolve()),
                    episode.task,
                    None if episode.operator_success is None else int(episode.operator_success),
                    None if episode.auto_success is None else int(episode.auto_success),
                    episode.failure_reason,
                    episode.num_frames,
                    json.dumps(episode.manifest),
                    episode.created_at,
                    _now(),
                ),
            )
            indexed += 1
    return {"indexed": indexed, "skipped": skipped, "invalid": invalid, "invalid_episodes": invalid_episodes}


def list_episodes(
    session_id: str | None = None,
    qa_status: str | None = None,
    dataset_id: int | None = None,
    engine_id: str | None = None,
) -> list[dict]:
    clauses: list[str] = ["s.status != 'trashed'"]
    params: list[str | int] = []
    if session_id:
        clauses.append("e.session_id = ?")
        params.append(session_id)
    if qa_status:
        clauses.append("e.qa_status = ?")
        params.append(qa_status)
    if dataset_id is not None:
        clauses.append("s.dataset_id = ?")
        params.append(dataset_id)
    if engine_id:
        clauses.append("CASE WHEN s.adapter_id = 'clothtwin' THEN 'genesis' ELSE s.adapter_id END = ?")
        params.append(engine_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with transaction() as connection:
        rows = connection.execute(
            f"""SELECT e.id, e.session_id, e.episode_uuid, e.path, e.task, e.operator_success,
                e.auto_success, e.qa_status, e.failure_reason, e.num_frames, e.created_at,
                e.manifest_json, s.dataset_id,
                CASE WHEN s.adapter_id = 'clothtwin' THEN 'genesis' ELSE s.adapter_id END AS engine_id,
                s.scene_id, s.control_mode
                FROM episodes e JOIN sessions s ON s.id = e.session_id
                {where} ORDER BY COALESCE(e.created_at, e.indexed_at) DESC""",
            params,
        ).fetchall()
        dataset_ids = sorted({int(row["dataset_id"]) for row in rows})
        duplicate_rows = []
        if dataset_ids:
            placeholders = ", ".join("?" for _ in dataset_ids)
            duplicate_rows = connection.execute(
                f"""SELECT s.dataset_id, e.task, e.manifest_json
                    FROM episodes e JOIN sessions s ON s.id = e.session_id
                    WHERE s.status != 'trashed' AND s.dataset_id IN ({placeholders})""",
                dataset_ids,
            ).fetchall()
    duplicate_counts: Counter[tuple[int, str, str, int | None]] = Counter()
    for row in duplicate_rows:
        manifest = json.loads(row["manifest_json"])
        source_trajectory = _source_trajectory(manifest)
        if source_trajectory is None:
            continue
        scene = manifest.get("scene")
        seed = scene.get("seed") if isinstance(scene, dict) else None
        duplicate_counts[
            (int(row["dataset_id"]), str(row["task"]), source_trajectory, seed)
        ] += 1
    episodes: list[dict] = []
    for row in rows:
        episode = dict(row)
        manifest = json.loads(episode.pop("manifest_json"))
        episode_index = manifest.get("episode_index")
        if not isinstance(episode_index, int):
            directory_name = Path(episode["path"]).name
            episode_index = int(directory_name.removeprefix("episode_")) if directory_name.removeprefix("episode_").isdigit() else None
        fps = manifest.get("fps")
        episode["episode_index"] = episode_index
        episode["fps"] = fps if isinstance(fps, (int, float)) and fps > 0 else None
        episode["duration_s"] = (
            episode["num_frames"] / float(episode["fps"])
            if episode["fps"] is not None
            else None
        )
        scene = manifest.get("scene")
        episode["seed"] = scene.get("seed") if isinstance(scene, dict) else None
        episode["source_trajectory"] = _source_trajectory(manifest)
        duplicate_group_size = 1
        if episode["source_trajectory"] is not None:
            duplicate_group_size = duplicate_counts[
                (
                    int(episode["dataset_id"]),
                    str(episode["task"]),
                    episode["source_trajectory"],
                    episode["seed"],
                )
            ]
        episode["duplicate_group_size"] = duplicate_group_size
        episode["is_duplicate"] = duplicate_group_size > 1
        software = manifest.get("software")
        episode["engine_version"] = software.get("engine_version") if isinstance(software, dict) else None
        episode["worker_id"] = software.get("worker_id") if isinstance(software, dict) else None
        episode["control_source"] = manifest.get("control_source")
        episodes.append(episode)
    return episodes


def episode_detail(episode_id: int) -> dict | None:
    with transaction() as connection:
        row = connection.execute(
            """SELECT e.*, s.dataset_id, s.adapter_id, s.scene_id, s.control_mode
               FROM episodes e JOIN sessions s ON s.id = e.session_id WHERE e.id = ?""",
            (episode_id,),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["manifest"] = json.loads(result.pop("manifest_json"))
    result["engine_id"] = canonical_engine_id(result.pop("adapter_id"))
    software = result["manifest"].get("software")
    result["engine_version"] = software.get("engine_version") if isinstance(software, dict) else None
    result["worker_id"] = software.get("worker_id") if isinstance(software, dict) else None
    result["control_source"] = result["manifest"].get("control_source")
    scene = result["manifest"].get("scene")
    result["seed"] = scene.get("seed") if isinstance(scene, dict) else None
    trajectory = Path(result["path"]) / "trajectory.npz"
    result["trajectory"] = {}
    if trajectory.exists():
        with np.load(trajectory, allow_pickle=False) as arrays:
            for name in ("timestamp", "policy_state", "policy_action", "reward"):
                if name in arrays:
                    values = arrays[name]
                    stride = max(1, len(values) // 200)
                    result["trajectory"][name] = values[::stride].tolist()
    return result


def update_qa(episode_id: int, qa_status: str, failure_reason: str | None) -> dict | None:
    with transaction() as connection:
        connection.execute(
            "UPDATE episodes SET qa_status = ?, failure_reason = ? WHERE id = ?",
            (qa_status, failure_reason, episode_id),
        )
        row = connection.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    return dict(row) if row else None
