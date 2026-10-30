from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import settings


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def transaction(db_path: Path | None = None):
    connection = connect(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize(db_path: Path | None = None) -> None:
    migration_paths = sorted(settings.migrations_root.glob("*.sql"))
    required = {"001_initial.sql", "002_export_selection.sql", "003_consumer_smokes.sql", "004_worker_runtime.sql"}
    missing = required - {path.name for path in migration_paths}
    if missing:
        raise ValueError(
            f"Missing database migrations in {settings.migrations_root}: {', '.join(sorted(missing))}. "
            "Install the complete backend package or configure ROBOT_DATA_STUDIO_MIGRATIONS_ROOT."
        )
    # Read before opening the database so missing/unreadable resources cannot
    # silently create an empty index and fail later in the worker monitor.
    scripts = [path.read_text(encoding="utf-8") for path in migration_paths]
    with transaction(db_path) as connection:
        for script in scripts:
            connection.executescript(script)
