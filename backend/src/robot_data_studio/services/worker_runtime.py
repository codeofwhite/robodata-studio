from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..db import transaction


ACTIVE_STATUSES = {"starting", "running", "stopping"}
TERMINAL_STATUSES = {"stopped", "failed", "orphaned"}


class ResourceConflict(RuntimeError):
    def __init__(self, conflicts: list[dict[str, str]]) -> None:
        self.conflicts = conflicts
        detail = ", ".join(
            f"{item['resource_key']} (run {item['run_id']})" for item in conflicts
        )
        super().__init__(f"worker resources are already locked: {detail}")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()


def _process_stat(pid: int) -> tuple[str, int]:
    # The process name in /proc/<pid>/stat may contain spaces and parentheses.
    payload = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    fields = payload[payload.rfind(")") + 2 :].split()
    return fields[0], int(fields[19])


def process_start_ticks(pid: int) -> int:
    return _process_stat(pid)[1]


def process_identity(pid: int) -> tuple[str, int]:
    return boot_id(), process_start_ticks(pid)


def identity_matches(pid: int | None, expected_boot_id: str | None, expected_ticks: int | None) -> bool:
    if pid is None or expected_boot_id is None or expected_ticks is None:
        return False
    try:
        actual_boot_id = boot_id()
        state, actual_ticks = _process_stat(pid)
    except (OSError, ValueError):
        return False
    return (
        state not in {"Z", "X"}
        and actual_boot_id == expected_boot_id
        and actual_ticks == expected_ticks
    )


def _decode_run(row) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    result["command"] = json.loads(result.pop("command_json"))
    result["readiness"] = json.loads(result.pop("readiness_json"))
    return result


def create_run(
    *,
    run_id: str,
    session_id: str,
    engine_id: str,
    command: list[str],
    cwd: Path,
    log_path: Path,
    state_path: Path,
    readiness: dict[str, Any],
    resources: Iterable[str],
) -> dict[str, Any]:
    timestamp = now()
    resource_keys = sorted(set(resources))
    with transaction() as connection:
        conflicts: list[dict[str, str]] = []
        for resource_key in resource_keys:
            row = connection.execute(
                "SELECT resource_key, run_id FROM worker_resource_locks WHERE resource_key = ?",
                (resource_key,),
            ).fetchone()
            if row:
                conflicts.append(dict(row))
        if conflicts:
            raise ResourceConflict(conflicts)
        connection.execute(
            """INSERT INTO worker_runs(
                   run_id, session_id, engine_id, status, command_json, cwd,
                   log_path, state_path, readiness_json, created_at, updated_at
               ) VALUES (?, ?, ?, 'starting', ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                session_id,
                engine_id,
                json.dumps(command),
                str(cwd),
                str(log_path),
                str(state_path),
                json.dumps(readiness),
                timestamp,
                timestamp,
            ),
        )
        connection.executemany(
            "INSERT INTO worker_resource_locks(resource_key, run_id, acquired_at) VALUES (?, ?, ?)",
            [(resource_key, run_id, timestamp) for resource_key in resource_keys],
        )
        connection.execute(
            "UPDATE sessions SET status = 'starting', worker_pid = NULL, updated_at = ? WHERE id = ?",
            (timestamp, session_id),
        )
    return get_run(run_id)


def set_supervisor_identity(
    run_id: str, *, pid: int, process_boot_id: str, start_ticks: int
) -> None:
    timestamp = now()
    with transaction() as connection:
        connection.execute(
            """UPDATE worker_runs
               SET supervisor_pid = ?, supervisor_boot_id = ?, supervisor_start_ticks = ?,
                   updated_at = ? WHERE run_id = ?""",
            (pid, process_boot_id, start_ticks, timestamp, run_id),
        )
        connection.execute(
            """UPDATE sessions SET worker_pid = ?, updated_at = ?
               WHERE id = (SELECT session_id FROM worker_runs WHERE run_id = ?)""",
            (pid, timestamp, run_id),
        )


def get_run(run_id: str) -> dict[str, Any] | None:
    with transaction() as connection:
        row = connection.execute(
            "SELECT * FROM worker_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    return _decode_run(row)


def latest_run(session_id: str) -> dict[str, Any] | None:
    with transaction() as connection:
        row = connection.execute(
            """SELECT * FROM worker_runs WHERE session_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (session_id,),
        ).fetchone()
    return _decode_run(row)


def active_runs() -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    with transaction() as connection:
        rows = connection.execute(
            f"SELECT * FROM worker_runs WHERE status IN ({placeholders}) ORDER BY created_at",
            tuple(sorted(ACTIVE_STATUSES)),
        ).fetchall()
    return [_decode_run(row) for row in rows]


def run_resources(run_id: str) -> list[str]:
    with transaction() as connection:
        rows = connection.execute(
            "SELECT resource_key FROM worker_resource_locks WHERE run_id = ? ORDER BY resource_key",
            (run_id,),
        ).fetchall()
    return [str(row["resource_key"]) for row in rows]


def update_run_from_state(run_id: str, state: dict[str, Any]) -> dict[str, Any]:
    status = str(state.get("status"))
    if status not in ACTIVE_STATUSES | TERMINAL_STATUSES:
        raise ValueError(f"invalid supervisor status: {status}")
    timestamp = now()
    terminal = status in TERMINAL_STATUSES
    with transaction() as connection:
        row = connection.execute(
            "SELECT session_id FROM worker_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        connection.execute(
            """UPDATE worker_runs SET status = ?, child_pid = ?, ready_at = ?,
                   heartbeat_at = ?, stopped_at = ?, return_code = ?, error = ?, updated_at = ?
               WHERE run_id = ?""",
            (
                status,
                state.get("child_pid"),
                state.get("ready_at"),
                state.get("heartbeat_at"),
                state.get("stopped_at"),
                state.get("return_code"),
                state.get("error"),
                timestamp,
                run_id,
            ),
        )
        connection.execute(
            "UPDATE sessions SET status = ?, worker_pid = ?, updated_at = ? WHERE id = ?",
            (
                status,
                None if terminal else state.get("supervisor_pid"),
                timestamp,
                row["session_id"],
            ),
        )
        if terminal:
            connection.execute(
                "DELETE FROM worker_resource_locks WHERE run_id = ?", (run_id,)
            )
    result = get_run(run_id)
    assert result is not None
    return result


def mark_run(
    run_id: str,
    *,
    status: str,
    error: str | None = None,
    return_code: int | None = None,
) -> dict[str, Any]:
    if status not in ACTIVE_STATUSES | TERMINAL_STATUSES:
        raise ValueError(f"invalid worker status: {status}")
    run = get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    state = {
        "status": status,
        "supervisor_pid": run.get("supervisor_pid"),
        "child_pid": run.get("child_pid"),
        "ready_at": run.get("ready_at"),
        "heartbeat_at": run.get("heartbeat_at"),
        "stopped_at": now() if status in TERMINAL_STATUSES else None,
        "return_code": return_code,
        "error": error,
    }
    return update_run_from_state(run_id, state)


def reconcile_legacy_sessions() -> list[str]:
    timestamp = now()
    with transaction() as connection:
        rows = connection.execute(
            """SELECT s.id FROM sessions s
               WHERE s.status IN ('starting', 'running', 'stopping')
                 AND NOT EXISTS (
                     SELECT 1 FROM worker_runs r
                     WHERE r.session_id = s.id
                       AND r.status IN ('starting', 'running', 'stopping')
                 )"""
        ).fetchall()
        session_ids = [str(row["id"]) for row in rows]
        if session_ids:
            connection.executemany(
                "UPDATE sessions SET status = 'orphaned', worker_pid = NULL, updated_at = ? WHERE id = ?",
                [(timestamp, session_id) for session_id in session_ids],
            )
    return session_ids


def read_state(path: str | Path) -> dict[str, Any] | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
