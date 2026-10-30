from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from robot_data_studio.worker_supervisor import main as supervisor_main


FAKE_WORKER = Path(__file__).parent / "fixtures" / "fake_worker.py"
SUPERVISOR = Path(__file__).parents[1] / "src" / "robot_data_studio" / "worker_supervisor.py"


def wait_state(path: Path, status: str, timeout: float = 4.0) -> dict:
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        if path.is_file():
            latest = json.loads(path.read_text(encoding="utf-8"))
            if latest["status"] == status:
                return latest
        time.sleep(0.02)
    raise AssertionError(f"state never reached {status}: {latest}")


def launch_supervisor(
    tmp_path: Path, worker_args: list[str], *, readiness_timeout_s: float = 2.0
) -> tuple[subprocess.Popen, Path]:
    state_path = tmp_path / "state.json"
    ready_path = tmp_path / "ready.json"
    spec_path = tmp_path / "launch.json"
    spec_path.write_text(
        json.dumps(
            {
                "run_id": "test-run",
                "command": [sys.executable, str(FAKE_WORKER), *worker_args],
                "cwd": str(tmp_path),
                "log_path": str(tmp_path / "worker.log"),
                "state_path": str(state_path),
                "readiness": {
                    "kind": "marker",
                    "path": str(ready_path),
                    "timeout_s": readiness_timeout_s,
                },
                "heartbeat_interval_s": 0.05,
                "child_stop_timeout_s": 0.1,
            }
        ),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["ROBOT_DATA_STUDIO_READY_FILE"] = str(ready_path)
    process = subprocess.Popen(
        [sys.executable, str(SUPERVISOR), "--spec", str(spec_path)],
        env=env,
        start_new_session=True,
    )
    return process, state_path


def test_supervisor_ready_heartbeat_and_sigterm(tmp_path: Path) -> None:
    process, state_path = launch_supervisor(tmp_path, [])
    try:
        running = wait_state(state_path, "running")
        first_heartbeat = running["heartbeat_at"]
        time.sleep(0.08)
        assert json.loads(state_path.read_text(encoding="utf-8"))["heartbeat_at"] != first_heartbeat
        os.killpg(process.pid, signal.SIGTERM)
        assert process.wait(timeout=3) == 0
        stopped = wait_state(state_path, "stopped")
        assert stopped["ready_at"] is not None
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)


def test_supervisor_records_nonzero_exit(tmp_path: Path) -> None:
    process, state_path = launch_supervisor(
        tmp_path, ["--exit-code", "23", "--lifetime", "0.1"]
    )
    assert process.wait(timeout=3) == 23
    failed = wait_state(state_path, "failed")
    assert failed["return_code"] == 23
    assert "return code 23" in failed["error"]


def test_supervisor_records_launch_failure(tmp_path: Path) -> None:
    spec_path = tmp_path / "launch.json"
    state_path = tmp_path / "state.json"
    spec_path.write_text(
        json.dumps(
            {
                "run_id": "missing-command",
                "command": [str(tmp_path / "does-not-exist")],
                "cwd": str(tmp_path),
                "log_path": str(tmp_path / "worker.log"),
                "state_path": str(state_path),
                "readiness": {"kind": "process", "timeout_s": 1.0},
            }
        ),
        encoding="utf-8",
    )
    assert supervisor_main(["--spec", str(spec_path)]) == 127
    failed = wait_state(state_path, "failed")
    assert failed["return_code"] == 127
    assert "launch failed" in failed["error"]


def test_supervisor_kills_child_that_ignores_sigterm(tmp_path: Path) -> None:
    process, state_path = launch_supervisor(tmp_path, ["--ignore-sigterm"])
    try:
        wait_state(state_path, "running")
        os.killpg(process.pid, signal.SIGTERM)
        assert process.wait(timeout=3) == 0
        stopped = wait_state(state_path, "stopped")
        assert stopped["return_code"] == -int(signal.SIGKILL)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)


def test_supervisor_fails_when_ready_handshake_times_out(tmp_path: Path) -> None:
    process, state_path = launch_supervisor(
        tmp_path,
        ["--ready-delay", "1.0"],
        readiness_timeout_s=0.1,
    )
    assert process.wait(timeout=3) == 124
    failed = wait_state(state_path, "failed")
    assert failed["ready_at"] is None
    assert "readiness timeout" in failed["error"]
