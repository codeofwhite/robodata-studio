from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..config import BACKEND_ROOT, CONTRACTS_SRC, PROJECT_ROOT, require_interpreter, settings
from ..db import transaction
from ..models import ExportCreate
from ..exporters.common import preflight_canonical_episodes


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update(export_id: str, status: str, error: str | None = None, pid: int | None = None) -> None:
    with transaction() as connection:
        connection.execute(
            "UPDATE exports SET status = ?, error = ?, worker_pid = ?, updated_at = ? WHERE id = ?",
            (status, error, pid, _now(), export_id),
        )


def _wait_for_export(export_id: str, process: subprocess.Popen) -> None:
    return_code = process.wait()
    if return_code != 0:
        _update(export_id, "failed", f"export process exited {return_code}")
        return
    _update(export_id, "completed")


def create_export(payload: ExportCreate) -> dict:
    with transaction() as connection:
        dataset = connection.execute("SELECT * FROM datasets WHERE id = ?", (payload.dataset_id,)).fetchone()
    if not dataset:
        raise KeyError(payload.dataset_id)
    episodes = _resolve_selected_episodes(payload.dataset_id, payload.episode_ids)
    preflight_export(payload, episodes=episodes)
    export_id = uuid.uuid4().hex[:12]
    output_root = Path(dataset["root_path"]) / "exports"
    suffix = ".hdf5" if payload.format == "robomimic" else ""
    output_path = output_root / f"{payload.output_name}{suffix}"
    _validate_output_available(payload.dataset_id, output_path)
    input_root = output_root / "inputs" / export_id
    command, cwd = _build_export_launch(payload, input_root, output_path)
    output_root.mkdir(parents=True, exist_ok=True)
    _stage_selected_episodes(episodes, input_root)
    timestamp = _now()
    with transaction() as connection:
        connection.execute(
            """INSERT INTO exports(id, dataset_id, format, status, output_path, error,
               worker_pid, created_at, updated_at)
               VALUES (?, ?, ?, 'queued', ?, NULL, NULL, ?, ?)""",
            (export_id, payload.dataset_id, payload.format, str(output_path), timestamp, timestamp),
        )
        connection.execute(
            """INSERT INTO export_specs(export_id, output_name, repo_id, images, profile)
               VALUES (?, ?, ?, ?, ?)""",
            (export_id, payload.output_name, payload.repo_id, int(payload.images), payload.profile),
        )
        connection.executemany(
            "INSERT INTO export_episodes(export_id, episode_id, position) VALUES (?, ?, ?)",
            [(export_id, episode["id"], position) for position, episode in enumerate(episodes)],
        )
    log_path = output_root / f"{export_id}.log"
    try:
        with log_path.open("ab", buffering=0) as log_file:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=_export_environment(),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as error:
        _update(export_id, "failed", str(error))
    else:
        _update(export_id, "running", pid=process.pid)
        threading.Thread(target=_wait_for_export, args=(export_id, process), daemon=True).start()
    return get_export(export_id) | {"command": command, "log_path": str(log_path)}


def preflight_export(payload: ExportCreate, *, episodes: list[dict] | None = None) -> dict:
    with transaction() as connection:
        dataset = connection.execute(
            "SELECT id, name FROM datasets WHERE id = ?", (payload.dataset_id,)
        ).fetchone()
    if not dataset:
        raise KeyError(payload.dataset_id)
    selected = episodes or _resolve_selected_episodes(payload.dataset_id, payload.episode_ids)
    try:
        report = preflight_canonical_episodes(
            [episode["source"] for episode in selected],
            format_name=payload.format,
            profile=payload.profile,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise ValueError(f"episode preflight failed: {error}") from error
    return report | {
        "dataset_id": dataset["id"],
        "dataset_name": dataset["name"],
        "episode_ids": [episode["id"] for episode in selected],
    }


def _build_export_launch(payload: ExportCreate, input_root: Path, output_path: Path) -> tuple[list[str], Path]:
    interpreters = {
        "lerobot": settings.lerobot_python,
        "openpi_lerobot_v21": settings.openpi_python,
        "rlds": settings.rlds_python,
        "robomimic": settings.robomimic_python,
    }
    modules = {
        "lerobot": "robot_data_studio.exporters.lerobot_v3",
        "openpi_lerobot_v21": "robot_data_studio.exporters.openpi_lerobot_v21",
        "rlds": "robot_data_studio.exporters.rlds",
        "robomimic": "robot_data_studio.exporters.robomimic",
    }
    variables = {
        "lerobot": "ROBOT_DATA_STUDIO_LEROBOT_PYTHON",
        "openpi_lerobot_v21": "ROBOT_DATA_STUDIO_OPENPI_PYTHON",
        "rlds": "ROBOT_DATA_STUDIO_RLDS_PYTHON",
        "robomimic": "ROBOT_DATA_STUDIO_ROBOMIMIC_PYTHON",
    }
    if payload.format not in interpreters:
        raise ValueError(f"unsupported export format: {payload.format}")
    require_interpreter(interpreters[payload.format], variables[payload.format])
    try:
        command = [
            interpreters[payload.format], "-m", modules[payload.format],
            "--input-root", str(input_root), "--output", str(output_path),
        ]
    except KeyError as error:
        raise ValueError(f"unsupported export format: {payload.format}") from error
    if payload.format in {"lerobot", "openpi_lerobot_v21"}:
        command += ["--repo-id", str(payload.repo_id)]
        if payload.images:
            command.append("--images")
    if payload.format == "lerobot":
        command += ["--profile", payload.profile]
    return command, PROJECT_ROOT


def _resolve_selected_episodes(dataset_id: int, episode_ids: list[int]) -> list[dict]:
    """Resolve and validate an ordered, explicitly selected accepted-only set."""
    if not episode_ids:
        raise ValueError("select at least one QA-accepted episode")
    if len(episode_ids) != len(set(episode_ids)):
        raise ValueError("episode selection contains duplicates")
    placeholders = ",".join("?" for _ in episode_ids)
    with transaction() as connection:
        rows = connection.execute(
            f"""SELECT e.id, e.episode_uuid, e.path, e.qa_status, s.status AS session_status,
               s.dataset_id, s.config_json AS session_config_json, d.root_path AS dataset_root FROM episodes e
               JOIN sessions s ON s.id = e.session_id
               JOIN datasets d ON d.id = s.dataset_id
               WHERE e.id IN ({placeholders})""",
            episode_ids,
        ).fetchall()
    by_id = {row["id"]: dict(row) for row in rows}
    selected: list[dict] = []
    for episode_id in episode_ids:
        episode = by_id.get(episode_id)
        if episode is None or episode["dataset_id"] != dataset_id:
            raise ValueError(f"episode {episode_id} does not belong to dataset {dataset_id}")
        if episode["qa_status"] != "accepted":
            raise ValueError(f"episode {episode_id} is not QA-accepted")
        if episode["session_status"] == "trashed":
            raise ValueError(f"episode {episode_id} belongs to a trashed session")
        source = Path(episode["path"]).resolve()
        raw_root = (Path(episode["dataset_root"]).resolve() / "raw").resolve()
        config = json.loads(episode["session_config_json"])
        if config.get("imported_read_only"):
            # Import records reference immutable delivered demonstrations in place.
            # Re-resolve against the catalog allowlist instead of trusting a DB path.
            from .cloth_catalog_service import catalog, run_path
            attempt = next((a for task in catalog()["tasks"] for a in task["attempts"]
                            if a.get("importable") and a["batch"] == config.get("source_batch")
                            and a["run_id"] == config.get("source_run")), None)
            if attempt is None:
                raise ValueError(f"episode {episode_id} imported source is no longer delivered")
            raw_root = run_path(attempt["batch"], attempt["path"]) / "episodes"
            if source.parent != raw_root or not source.name.startswith("episode_"):
                raise ValueError(f"episode {episode_id} imported source does not match its run")
        if not source.is_relative_to(raw_root) or not source.is_dir():
            raise ValueError(f"episode {episode_id} source directory is unavailable")
        episode["source"] = source
        selected.append(episode)
    return selected


def _stage_selected_episodes(episodes: list[dict], staging_root: Path) -> Path:
    """Build an immutable symlink view containing exactly the selected episodes."""
    staging_root.mkdir(parents=True, exist_ok=False)
    for episode in episodes:
        source = episode["source"]
        target = staging_root / episode["episode_uuid"]
        target.mkdir()
        for child in source.iterdir():
            (target / child.name).symlink_to(child, target_is_directory=child.is_dir())
    return staging_root


def _validate_output_available(dataset_id: int, output_path: Path) -> None:
    if output_path.exists():
        raise ValueError(f"export output already exists: {output_path.name}")
    with transaction() as connection:
        active = connection.execute(
            """SELECT id FROM exports WHERE dataset_id = ? AND output_path = ?
               AND status IN ('queued', 'running', 'completed') LIMIT 1""",
            (dataset_id, str(output_path)),
        ).fetchone()
    if active:
        raise ValueError(f"export output is already reserved by job {active['id']}")


def _export_environment() -> dict[str, str]:
    env = dict(os.environ)
    python_paths = [str(BACKEND_ROOT / "src"), str(CONTRACTS_SRC)]
    if env.get("PYTHONPATH"):
        python_paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(python_paths)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def get_export(export_id: str) -> dict | None:
    with transaction() as connection:
        row = connection.execute(
            """SELECT x.*, s.output_name, s.repo_id, s.images, s.profile,
               (SELECT COUNT(*) FROM export_episodes ee WHERE ee.export_id = x.id) AS episode_count
               FROM exports x LEFT JOIN export_specs s ON s.export_id = x.id
               WHERE x.id = ?""",
            (export_id,),
        ).fetchone()
        if not row:
            return None
        episode_rows = connection.execute(
            """SELECT ee.episode_id, ee.position, e.session_id, e.path, e.manifest_json
               FROM export_episodes ee JOIN episodes e ON e.id = ee.episode_id
               WHERE ee.export_id = ? ORDER BY ee.position""",
            (export_id,),
        ).fetchall()
    result = dict(row)
    result["episode_ids"] = [episode["episode_id"] for episode in episode_rows]
    result["episode_refs"] = [_episode_reference(episode) for episode in episode_rows]
    return result


def list_exports() -> list[dict]:
    with transaction() as connection:
        rows = connection.execute(
            """SELECT x.*, s.output_name, s.repo_id, s.images, s.profile,
               (SELECT COUNT(*) FROM export_episodes ee WHERE ee.export_id = x.id) AS episode_count
               FROM exports x LEFT JOIN export_specs s ON s.export_id = x.id
               ORDER BY x.created_at DESC"""
        ).fetchall()
        episode_rows = connection.execute(
            """SELECT ee.export_id, ee.episode_id, ee.position, e.session_id, e.path,
               e.manifest_json FROM export_episodes ee
               JOIN episodes e ON e.id = ee.episode_id
               ORDER BY ee.export_id, ee.position"""
        ).fetchall()
    episode_ids: dict[str, list[int]] = {}
    episode_refs: dict[str, list[dict]] = {}
    for episode in episode_rows:
        episode_ids.setdefault(episode["export_id"], []).append(episode["episode_id"])
        episode_refs.setdefault(episode["export_id"], []).append(_episode_reference(episode))
    return [
        dict(row)
        | {
            "episode_ids": episode_ids.get(row["id"], []),
            "episode_refs": episode_refs.get(row["id"], []),
        }
        for row in rows
    ]


def _episode_reference(row) -> dict:
    manifest = json.loads(row["manifest_json"])
    episode_index = manifest.get("episode_index")
    if not isinstance(episode_index, int):
        directory_name = Path(row["path"]).name
        suffix = directory_name.removeprefix("episode_")
        episode_index = int(suffix) if suffix.isdigit() else None
    return {
        "episode_id": row["episode_id"],
        "session_id": row["session_id"],
        "episode_index": episode_index,
        "engine_id": manifest.get("software", {}).get("engine_id"),
        "engine_version": manifest.get("software", {}).get("engine_version"),
        "worker_id": manifest.get("software", {}).get("worker_id"),
        "scene_id": manifest.get("scene", {}).get("scene_id"),
        "position": row["position"],
    }
