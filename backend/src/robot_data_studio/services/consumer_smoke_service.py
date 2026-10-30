from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..config import BACKEND_ROOT, CONTRACTS_SRC, PROJECT_ROOT, settings
from ..db import transaction


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update(smoke_id: str, status: str, *, error: str | None = None, pid: int | None = None) -> None:
    with transaction() as connection:
        connection.execute(
            "UPDATE consumer_smokes SET status = ?, error = ?, worker_pid = ?, updated_at = ? WHERE id = ?",
            (status, error, pid, _now(), smoke_id),
        )


def _wait(smoke_id: str, process: subprocess.Popen) -> None:
    return_code = process.wait()
    _update(
        smoke_id,
        "passed" if return_code == 0 else "failed",
        error=None if return_code == 0 else f"consumer smoke process exited {return_code}",
    )


def start_automatic_smoke(export_id: str) -> dict | None:
    with transaction() as connection:
        row = connection.execute(
            """SELECT x.id, x.format, x.output_path, s.repo_id, s.profile
               FROM exports x JOIN export_specs s ON s.export_id = x.id WHERE x.id = ?""",
            (export_id,),
        ).fetchone()
    if row is None:
        raise KeyError(export_id)
    consumer: str | None = None
    interpreter: str | None = None
    if row["format"] == "openpi_lerobot_v21":
        consumer, interpreter = "openpi", settings.openpi_python
    elif row["format"] == "lerobot" and row["profile"] == "fastwam_franka_joint8":
        consumer, interpreter = "fastwam", settings.fastwam_python
    if consumer is None or interpreter is None:
        return None

    smoke_id = uuid.uuid4().hex[:12]
    output_path = Path(row["output_path"])
    report_path = output_path / "consumer_smoke" / f"{consumer}.json"
    log_path = output_path.parent / f"{export_id}.{consumer}.smoke.log"
    command = [
        interpreter,
        "-m",
        "robot_data_studio.consumer_smoke",
        "--consumer",
        consumer,
        "--dataset-root",
        str(output_path),
        "--repo-id",
        str(row["repo_id"]),
        "--report",
        str(report_path),
    ]
    if consumer == "openpi":
        command.extend(
            [
                "--checkpoint",
                str(settings.openpi_checkpoint),
                "--config-name",
                settings.openpi_config,
                "--inference-steps",
                str(settings.openpi_inference_steps),
            ]
        )
    timestamp = _now()
    with transaction() as connection:
        connection.execute(
            """INSERT INTO consumer_smokes(
               id, export_id, consumer, status, report_path, log_path, error,
               worker_pid, created_at, updated_at
               ) VALUES (?, ?, ?, 'queued', ?, ?, NULL, NULL, ?, ?)""",
            (smoke_id, export_id, consumer, str(report_path), str(log_path), timestamp, timestamp),
        )
    try:
        with log_path.open("ab", buffering=0) as log_file:
            process = subprocess.Popen(
                command,
                cwd=PROJECT_ROOT,
                env=_smoke_environment(consumer),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as error:
        _update(smoke_id, "failed", error=str(error))
    else:
        _update(smoke_id, "running", pid=process.pid)
        threading.Thread(target=_wait, args=(smoke_id, process), daemon=True).start()
    return get_consumer_smoke(smoke_id) | {"command": command}


def _smoke_environment(consumer: str) -> dict[str, str]:
    env = dict(os.environ)
    paths = [str(BACKEND_ROOT / "src"), str(CONTRACTS_SRC)]
    if consumer == "openpi":
        paths[0:0] = [
            str(settings.openpi_root / "src"),
            str(settings.openpi_root / "packages" / "openpi-client" / "src"),
        ]
        env["CUDA_VISIBLE_DEVICES"] = str(settings.openpi_gpu_id)
        env["JAX_PLATFORMS"] = "cuda"
        env["XLA_PYTHON_CLIENT_MEM_FRACTION"] = "0.9"
        env["JAX_COMPILATION_CACHE_DIR"] = str(settings.data_root / "cache" / "jax")
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["HF_DATASETS_CACHE"] = str(settings.data_root / "cache" / "huggingface" / "datasets")
    return env


def get_consumer_smoke(smoke_id: str) -> dict | None:
    with transaction() as connection:
        row = connection.execute("SELECT * FROM consumer_smokes WHERE id = ?", (smoke_id,)).fetchone()
    return None if row is None else _with_report(dict(row))


def list_consumer_smokes() -> list[dict]:
    with transaction() as connection:
        rows = connection.execute("SELECT * FROM consumer_smokes ORDER BY created_at DESC").fetchall()
    return [_with_report(dict(row)) for row in rows]


def _with_report(smoke: dict) -> dict:
    report_path = Path(smoke["report_path"])
    if not report_path.is_file():
        return smoke | {"report": None}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return smoke | {"report": None, "report_read_error": str(error)}
    return smoke | {"report": report}
