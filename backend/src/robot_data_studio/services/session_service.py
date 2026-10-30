from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ..adapters import canonical_engine_id, get_engine
from ..config import settings
from ..db import transaction
from ..models import SessionCreate


SESSION_DISPLAY_TIMEZONE = ZoneInfo("Asia/Shanghai")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_session_id(
    scene_id: str,
    control_mode: str,
    *,
    created_at: datetime | None = None,
    unique_suffix: str | None = None,
) -> str:
    """Build a China-time-sortable, human-readable, collision-resistant session ID."""
    timestamp = (created_at or datetime.now(timezone.utc)).astimezone(
        SESSION_DISPLAY_TIMEZONE
    )

    def slug(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
        if not normalized:
            raise ValueError("session ID component must contain a letter or number")
        return normalized[:48].rstrip("_")

    suffix = unique_suffix or uuid.uuid4().hex[:8]
    if not re.fullmatch(r"[0-9a-f]{8}", suffix):
        raise ValueError("session ID suffix must contain exactly 8 lowercase hex characters")
    return "_".join(
        [
            timestamp.strftime("%Y%m%dT%H%M%S%z"),
            slug(scene_id),
            slug(control_mode),
            suffix,
        ]
    )


def row_dict(row):
    if row is None:
        return None
    result = dict(row)
    if "config_json" in result:
        result["config"] = json.loads(result.pop("config_json"))
    if "adapter_id" in result:
        result["engine_id"] = canonical_engine_id(result["adapter_id"])
    return result


def create_session(payload: SessionCreate) -> dict:
    adapter = get_engine(payload.engine_id)
    adapter.validate_config(payload.model_dump())
    created_at = datetime.now(timezone.utc)
    timestamp = created_at.isoformat()
    session_id = build_session_id(
        payload.scene_id, payload.control_mode, created_at=created_at
    )
    dataset_root = (settings.data_root / "datasets" / payload.dataset_name).resolve()
    allowed_root = (settings.data_root / "datasets").resolve()
    if not dataset_root.is_relative_to(allowed_root):
        raise ValueError("dataset path escapes data root")
    episode_root = dataset_root / "raw" / session_id
    episode_root.mkdir(parents=True, exist_ok=True)
    config = payload.model_dump()
    config["episode_root"] = str(episode_root)
    with transaction() as connection:
        project = connection.execute("SELECT id FROM projects WHERE name = ?", ("local",)).fetchone()
        if project is None:
            cursor = connection.execute(
                "INSERT INTO projects(name, root_path, created_at) VALUES (?, ?, ?)",
                ("local", str(settings.data_root), timestamp),
            )
            project_id = cursor.lastrowid
        else:
            project_id = project["id"]
        dataset = connection.execute("SELECT id FROM datasets WHERE root_path = ?", (str(dataset_root),)).fetchone()
        if dataset is None:
            cursor = connection.execute(
                "INSERT INTO datasets(project_id, name, root_path, created_at) VALUES (?, ?, ?, ?)",
                (project_id, payload.dataset_name, str(dataset_root), timestamp),
            )
            dataset_id = cursor.lastrowid
        else:
            dataset_id = dataset["id"]
        connection.execute(
            """INSERT INTO sessions(id, dataset_id, adapter_id, scene_id, control_mode, status,
               target_episodes, collector_url, worker_pid, config_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, NULL, ?, ?, ?)""",
            (
                session_id,
                dataset_id,
                adapter.adapter_id,
                payload.scene_id,
                payload.control_mode,
                payload.target_episodes,
                (
                    f"http://127.0.0.1:{payload.port}"
                    if adapter.capabilities.get("interactive_ui", True)
                    else None
                ),
                json.dumps(config),
                timestamp,
                timestamp,
            ),
        )
        row = connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return row_dict(row)


def get_session(session_id: str) -> dict | None:
    with transaction() as connection:
        row = connection.execute(
            """SELECT s.*, d.name AS dataset_name, d.root_path AS dataset_root,
               (SELECT COUNT(*) FROM episodes e WHERE e.session_id = s.id) AS episode_count,
               (SELECT COUNT(*) FROM episodes e WHERE e.session_id = s.id AND e.qa_status = 'accepted') AS accepted_count,
               (SELECT COUNT(*) FROM episodes e WHERE e.session_id = s.id AND e.qa_status = 'pending') AS pending_count
               FROM sessions s JOIN datasets d ON d.id = s.dataset_id WHERE s.id = ?""",
            (session_id,),
        ).fetchone()
    return row_dict(row)


def list_sessions(*, include_trashed: bool = False) -> list[dict]:
    where = "" if include_trashed else "WHERE s.status != 'trashed'"
    with transaction() as connection:
        rows = connection.execute(
            f"""SELECT s.*, d.name AS dataset_name, d.root_path AS dataset_root,
               (SELECT COUNT(*) FROM episodes e WHERE e.session_id = s.id) AS episode_count,
               (SELECT COUNT(*) FROM episodes e WHERE e.session_id = s.id AND e.qa_status = 'accepted') AS accepted_count,
               (SELECT COUNT(*) FROM episodes e WHERE e.session_id = s.id AND e.qa_status = 'pending') AS pending_count
               FROM sessions s JOIN datasets d ON d.id = s.dataset_id
               {where} ORDER BY s.created_at DESC"""
        ).fetchall()
    return [row_dict(row) for row in rows]


def _validated_session_root(session: dict, root: Path) -> Path:
    resolved = root.resolve()
    allowed = (Path(session["dataset_root"]).resolve() / "raw").resolve()
    if resolved == allowed or not resolved.is_relative_to(allowed):
        raise ValueError("session episode_root is outside its dataset raw directory")
    return resolved


def trash_session(session_id: str) -> dict:
    session = get_session(session_id)
    if not session:
        raise KeyError(session_id)
    if session["config"].get("imported_read_only"):
        raise ValueError("Imported cloth evidence is read-only; source files cannot be moved or deleted")
    if session["status"] == "trashed":
        return session
    with transaction() as connection:
        active_export = connection.execute(
            "SELECT id FROM exports WHERE dataset_id = ? AND status IN ('queued', 'running') LIMIT 1",
            (session["dataset_id"],),
        ).fetchone()
    if active_export:
        raise ValueError("wait for active dataset exports before moving this session to trash")
    source = _validated_session_root(session, Path(session["config"]["episode_root"]))
    trash_root = (settings.data_root / "trash" / "sessions").resolve()
    destination = trash_root / session_id
    if destination.exists():
        raise ValueError("session trash destination already exists")
    moved = False
    if source.exists():
        trash_root.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        moved = True
    config = dict(session["config"])
    config["_lifecycle"] = {
        "previous_status": session["status"],
        "original_episode_root": str(source),
        "trashed_at": now(),
    }
    config["episode_root"] = str(destination)
    try:
        with transaction() as connection:
            connection.execute(
                "UPDATE sessions SET status = 'trashed', worker_pid = NULL, config_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(config), now(), session_id),
            )
            connection.execute(
                "UPDATE episodes SET path = replace(path, ?, ?) WHERE session_id = ?",
                (str(source), str(destination), session_id),
            )
    except Exception:
        if moved and destination.exists() and not source.exists():
            shutil.move(str(destination), str(source))
        raise
    return get_session(session_id)


def restore_session(session_id: str) -> dict:
    session = get_session(session_id)
    if not session:
        raise KeyError(session_id)
    if session["config"].get("imported_read_only"):
        raise ValueError("Imported cloth evidence is read-only; source files cannot be moved or deleted")
    if session["status"] != "trashed":
        raise ValueError("only trashed sessions can be restored")
    config = dict(session["config"])
    lifecycle = config.get("_lifecycle")
    if not isinstance(lifecycle, dict) or not lifecycle.get("original_episode_root"):
        raise ValueError("trashed session is missing restore metadata")
    source = Path(config["episode_root"]).resolve()
    trash_root = (settings.data_root / "trash" / "sessions").resolve()
    if source.parent != trash_root:
        raise ValueError("trashed session path is outside the Studio trash directory")
    destination = _validated_session_root(
        session, Path(str(lifecycle["original_episode_root"]))
    )
    if destination.exists():
        raise ValueError("session restore destination already exists")
    moved = False
    if source.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        moved = True
    previous_status = str(lifecycle.get("previous_status") or "stopped")
    if previous_status in {"running", "starting", "trashed"}:
        previous_status = "stopped"
    config["episode_root"] = str(destination)
    config.pop("_lifecycle", None)
    try:
        with transaction() as connection:
            connection.execute(
                "UPDATE sessions SET status = ?, config_json = ?, updated_at = ? WHERE id = ?",
                (previous_status, json.dumps(config), now(), session_id),
            )
            connection.execute(
                "UPDATE episodes SET path = replace(path, ?, ?) WHERE session_id = ?",
                (str(source), str(destination), session_id),
            )
    except Exception:
        if moved and destination.exists() and not source.exists():
            shutil.move(str(destination), str(source))
        raise
    return get_session(session_id)


def permanently_delete_session(
    session_id: str, *, confirm_session_id: str, delete_accepted_data: bool
) -> dict:
    session = get_session(session_id)
    if not session:
        raise KeyError(session_id)
    if session["config"].get("imported_read_only"):
        raise ValueError("Imported cloth evidence is read-only; source files cannot be moved or deleted")
    if confirm_session_id != session_id:
        raise ValueError("confirmation must exactly match the session ID")
    if session["status"] != "trashed":
        raise ValueError("move the session to trash before permanently deleting it")
    if session["accepted_count"] and not delete_accepted_data:
        raise ValueError("accepted episodes require explicit delete_accepted_data confirmation")
    source = Path(session["config"]["episode_root"]).resolve()
    trash_root = (settings.data_root / "trash" / "sessions").resolve()
    if source.parent != trash_root:
        raise ValueError("session path is outside the Studio trash directory")
    purge_path = trash_root / f".purging-{session_id}-{uuid.uuid4().hex[:8]}"
    moved = False
    if source.exists():
        source.rename(purge_path)
        moved = True
    try:
        with transaction() as connection:
            connection.execute("DELETE FROM episodes WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    except Exception:
        if moved and purge_path.exists() and not source.exists():
            purge_path.rename(source)
        raise
    if moved:
        shutil.rmtree(purge_path)
    return {"deleted": True, "session_id": session_id}


def update_worker(session_id: str, *, status: str, pid: int | None) -> None:
    with transaction() as connection:
        connection.execute(
            "UPDATE sessions SET status = ?, worker_pid = ?, updated_at = ? WHERE id = ?",
            (status, pid, now(), session_id),
        )
