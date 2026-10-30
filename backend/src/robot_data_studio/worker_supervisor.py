from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def ready(probe: dict[str, Any]) -> bool:
    kind = probe["kind"]
    if kind == "process":
        return True
    if kind == "marker":
        return Path(probe["path"]).is_file()
    if kind == "tcp":
        try:
            with socket.create_connection(
                (str(probe["host"]), int(probe["port"])), timeout=0.2
            ):
                return True
        except OSError:
            return False
    raise ValueError(f"unsupported readiness probe: {kind}")


def terminate_child(child: subprocess.Popen[Any], *, timeout_s: float = 5.0) -> None:
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=2.0)


def supervise(spec_path: Path) -> int:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    state_path = Path(spec["state_path"])
    log_path = Path(spec["log_path"])
    readiness = dict(spec["readiness"])
    heartbeat_interval_s = float(spec.get("heartbeat_interval_s", 1.0))
    child_stop_timeout_s = float(spec.get("child_stop_timeout_s", 5.0))
    state: dict[str, Any] = {
        "run_id": spec["run_id"],
        "status": "starting",
        "supervisor_pid": os.getpid(),
        "child_pid": None,
        "ready_at": None,
        "heartbeat_at": now(),
        "stopped_at": None,
        "return_code": None,
        "error": None,
    }
    write_state(state_path, state)
    stop_requested = False

    def request_stop(_signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True

    previous_sigterm = signal.signal(signal.SIGTERM, request_stop)
    previous_sigint = signal.signal(signal.SIGINT, request_stop)
    child: subprocess.Popen[Any] | None = None
    started = time.monotonic()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab", buffering=0) as log_file:
            try:
                child = subprocess.Popen(
                    list(spec["command"]),
                    cwd=spec["cwd"],
                    env=dict(os.environ),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                )
            except OSError as error:
                state.update(
                    status="failed",
                    heartbeat_at=now(),
                    stopped_at=now(),
                    return_code=127,
                    error=f"worker launch failed: {error}",
                )
                write_state(state_path, state)
                return 127
            state["child_pid"] = child.pid
            write_state(state_path, state)
            while True:
                return_code = child.poll()
                if return_code is not None:
                    status = "stopped" if stop_requested or return_code == 0 else "failed"
                    state.update(
                        status=status,
                        heartbeat_at=now(),
                        stopped_at=now(),
                        return_code=return_code,
                        error=(
                            None
                            if status == "stopped"
                            else f"worker exited with return code {return_code}"
                        ),
                    )
                    write_state(state_path, state)
                    return 0 if status == "stopped" else return_code
                if stop_requested:
                    state.update(status="stopping", heartbeat_at=now())
                    write_state(state_path, state)
                    terminate_child(child, timeout_s=child_stop_timeout_s)
                    continue
                if state["status"] == "starting" and ready(readiness):
                    state.update(status="running", ready_at=now())
                if (
                    state["status"] == "starting"
                    and time.monotonic() - started > float(readiness["timeout_s"])
                ):
                    state.update(
                        status="failed",
                        heartbeat_at=now(),
                        error=f"readiness timeout after {readiness['timeout_s']} seconds",
                    )
                    write_state(state_path, state)
                    terminate_child(child, timeout_s=child_stop_timeout_s)
                    state.update(stopped_at=now(), return_code=124)
                    write_state(state_path, state)
                    return 124
                state["heartbeat_at"] = now()
                write_state(state_path, state)
                time.sleep(heartbeat_interval_s)
    except BaseException as error:
        if child is not None:
            terminate_child(child, timeout_s=child_stop_timeout_s)
        state.update(
            status="failed",
            heartbeat_at=now(),
            stopped_at=now(),
            return_code=1,
            error=f"supervisor failure: {type(error).__name__}: {error}",
        )
        write_state(state_path, state)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGINT, previous_sigint)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Durable Robot Data Studio worker supervisor")
    parser.add_argument("--spec", type=Path, required=True)
    args = parser.parse_args(argv)
    return supervise(args.spec)


if __name__ == "__main__":
    raise SystemExit(main())
