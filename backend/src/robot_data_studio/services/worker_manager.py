from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ..adapters import get_engine
from .session_service import get_session
from .worker_runtime import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    active_runs,
    create_run,
    get_run,
    identity_matches,
    latest_run,
    mark_run,
    process_identity,
    read_state,
    reconcile_legacy_sessions,
    run_resources,
    set_supervisor_identity,
    update_run_from_state,
    write_json_atomic,
)


SUPERVISOR_PATH = Path(__file__).resolve().parents[1] / "worker_supervisor.py"


class WorkerManager:
    def __init__(
        self,
        *,
        monitor_interval_s: float = 1.0,
        stop_timeout_s: float = 8.0,
        kill_timeout_s: float = 3.0,
    ) -> None:
        self.monitor_interval_s = monitor_interval_s
        self.stop_timeout_s = stop_timeout_s
        self.kill_timeout_s = kill_timeout_s
        self._lock = threading.RLock()
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None

    def command_for(self, session: dict[str, Any]) -> list[str]:
        adapter = get_engine(session["engine_id"])
        launch = adapter.build_worker_launch(
            session["config"], Path(session["config"]["episode_root"])
        )
        return launch.command

    def _format_run(self, run: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": run["status"],
            "run_id": run["run_id"],
            "pid": run.get("supervisor_pid"),
            "supervisor_pid": run.get("supervisor_pid"),
            "child_pid": run.get("child_pid"),
            "return_code": run.get("return_code"),
            "ready_at": run.get("ready_at"),
            "heartbeat_at": run.get("heartbeat_at"),
            "error": run.get("error"),
            "log_path": run.get("log_path"),
            "engine_id": run.get("engine_id"),
            "resources": run_resources(run["run_id"]),
            "command": run.get("command"),
        }

    def _signal_verified(self, run: dict[str, Any], sig: signal.Signals) -> bool:
        pid = run.get("supervisor_pid")
        if not identity_matches(
            pid, run.get("supervisor_boot_id"), run.get("supervisor_start_ticks")
        ):
            return False
        try:
            os.killpg(int(pid), sig)
        except ProcessLookupError:
            return False
        return True

    def _sync_run(self, run: dict[str, Any]) -> dict[str, Any]:
        # start() holds this lock through PID identity registration. Monitoring
        # may have read an earlier row before waiting, so refresh it under the
        # same lock before testing identity or releasing any resources.
        with self._lock:
            current = get_run(run["run_id"])
            if current is None:
                raise RuntimeError("worker run record disappeared")
            return self._sync_registered_run(current)

    def _sync_registered_run(self, run: dict[str, Any]) -> dict[str, Any]:
        # Terminal database state is authoritative. A supervisor that was killed
        # may leave an older active state file behind; it must not resurrect a run.
        if run["status"] not in ACTIVE_STATUSES:
            return run
        state = read_state(run["state_path"])
        if state is not None and state.get("run_id") == run["run_id"]:
            run = update_run_from_state(run["run_id"], state)
        if run["status"] not in ACTIVE_STATUSES:
            return run
        if not identity_matches(
            run.get("supervisor_pid"),
            run.get("supervisor_boot_id"),
            run.get("supervisor_start_ticks"),
        ):
            # The supervisor atomically writes its terminal state immediately
            # before exiting. It may disappear between the first state read
            # above and this identity check, so read once more before declaring
            # the run orphaned. A missing/still-active state remains orphaned.
            final_state = read_state(run["state_path"])
            if (
                final_state is not None
                and final_state.get("run_id") == run["run_id"]
                and final_state.get("status") in TERMINAL_STATUSES
            ):
                return update_run_from_state(run["run_id"], final_state)
            return mark_run(
                run["run_id"],
                status="orphaned",
                error="supervisor process identity is missing or changed",
                return_code=run.get("return_code"),
            )
        return run

    def reconcile(self) -> dict[str, Any]:
        legacy_orphans = reconcile_legacy_sessions()
        reconciled: list[str] = []
        for run in active_runs():
            self._sync_run(run)
            reconciled.append(run["run_id"])
        return {"legacy_orphans": legacy_orphans, "reconciled_runs": reconciled}

    def _monitor_loop(self) -> None:
        while not self._monitor_stop.wait(self.monitor_interval_s):
            try:
                self.reconcile()
            except Exception:
                # Status endpoints still perform synchronous reconciliation. A monitor
                # iteration must not permanently kill the background thread.
                continue

    def start_monitor(self) -> dict[str, Any]:
        result = self.reconcile()
        if self._monitor_thread and self._monitor_thread.is_alive():
            return result
        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="studio-worker-monitor",
            daemon=True,
        )
        self._monitor_thread.start()
        return result

    def shutdown_monitor(self) -> None:
        self._monitor_stop.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=max(2.0, self.monitor_interval_s * 2))
        self._monitor_thread = None

    def _preflight_ports(self, resources: tuple[str, ...]) -> None:
        for resource in resources:
            protocol, separator, raw_port = resource.partition(":")
            if not separator or protocol not in {"tcp", "udp"}:
                continue
            port = int(raw_port)
            sock_type = socket.SOCK_STREAM if protocol == "tcp" else socket.SOCK_DGRAM
            with socket.socket(socket.AF_INET, sock_type) as probe:
                # For a while after a stop, this port looks taken: the collector's
                # own client sockets linger on it, in FIN_WAIT_2 if the browser is
                # still connected and TIME_WAIT once it is not. The worker binds
                # with SO_REUSEADDR (asyncio does by default), so it starts fine;
                # probing with reuse disabled reported a conflict that was not
                # there and refused the launch. A live listener still fails.
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    probe.bind(("0.0.0.0", port))
                except OSError as error:
                    raise RuntimeError(
                        f"host {protocol.upper()} port {port} is unavailable: {error}"
                    ) from error

    def is_running(self, session_id: str) -> bool:
        run = latest_run(session_id)
        if run is None:
            return False
        return self._sync_run(run)["status"] in ACTIVE_STATUSES

    def start(self, session_id: str) -> dict[str, Any]:
        session = get_session(session_id)
        if not session:
            raise KeyError(session_id)
        if session["config"].get("imported_read_only"):
            raise ValueError("Imported evidence cannot launch a collector")
        if session["status"] == "trashed":
            raise ValueError("restore the session before starting its worker")
        with self._lock:
            existing = latest_run(session_id)
            if existing is not None:
                existing = self._sync_run(existing)
                if existing["status"] in ACTIVE_STATUSES:
                    return self._format_run(existing)
            adapter = get_engine(session["engine_id"])
            output_root = Path(session["config"]["episode_root"])
            launch = adapter.build_worker_launch(session["config"], output_root)
            run_id = uuid.uuid4().hex
            runtime_root = output_root / ".studio" / "runs" / run_id
            spec_path = runtime_root / "launch.json"
            state_path = runtime_root / "state.json"
            marker_path = runtime_root / "ready.json"
            log_path = output_root / "collector.log"
            readiness = launch.readiness.as_dict()
            if readiness["kind"] == "marker":
                readiness["path"] = str(marker_path)
            resources = tuple(sorted(set(launch.resources)))
            create_run(
                run_id=run_id,
                session_id=session_id,
                engine_id=adapter.adapter_id,
                command=launch.command,
                cwd=launch.cwd,
                log_path=log_path,
                state_path=state_path,
                readiness=readiness,
                resources=resources,
            )
            try:
                self._preflight_ports(resources)
                spec = {
                    "run_id": run_id,
                    "command": launch.command,
                    "cwd": str(launch.cwd),
                    "log_path": str(log_path),
                    "state_path": str(state_path),
                    "readiness": readiness,
                    "heartbeat_interval_s": 1.0,
                    "child_stop_timeout_s": min(5.0, self.stop_timeout_s),
                }
                write_json_atomic(spec_path, spec)
                env = dict(os.environ)
                for name in launch.unset_env:
                    env.pop(name, None)
                env.update(launch.env_updates)
                env["ROBOT_DATA_STUDIO_RUN_ID"] = run_id
                if readiness["kind"] == "marker":
                    env["ROBOT_DATA_STUDIO_READY_FILE"] = str(marker_path)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open("ab", buffering=0) as supervisor_log:
                    process = subprocess.Popen(
                        [sys.executable, str(SUPERVISOR_PATH), "--spec", str(spec_path)],
                        cwd=launch.cwd,
                        env=env,
                        stdout=supervisor_log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                process_boot_id, start_ticks = process_identity(process.pid)
                set_supervisor_identity(
                    run_id,
                    pid=process.pid,
                    process_boot_id=process_boot_id,
                    start_ticks=start_ticks,
                )
            except BaseException as error:
                mark_run(
                    run_id,
                    status="failed",
                    error=f"worker supervisor launch failed: {type(error).__name__}: {error}",
                )
                raise
            run = get_run(run_id)
            assert run is not None
            return self._format_run(run)

    def status(self, session_id: str) -> dict[str, Any]:
        session = get_session(session_id)
        if not session:
            raise KeyError(session_id)
        run = latest_run(session_id)
        if run is None:
            if session["status"] in ACTIVE_STATUSES:
                reconcile_legacy_sessions()
                session = get_session(session_id) or session
            return {
                "status": session["status"] if session["status"] == "orphaned" else "not_managed",
                "run_id": None,
                "pid": None,
                "supervisor_pid": None,
                "child_pid": None,
                "engine_id": session["engine_id"],
                "error": (
                    "legacy worker state has no durable run record"
                    if session["status"] == "orphaned"
                    else None
                ),
                "resources": [],
            }
        return self._format_run(self._sync_run(run))

    def stop(self, session_id: str) -> dict[str, Any]:
        session = get_session(session_id)
        if not session:
            raise KeyError(session_id)
        with self._lock:
            run = latest_run(session_id)
            if run is None:
                if session["status"] in ACTIVE_STATUSES:
                    reconcile_legacy_sessions()
                return self.status(session_id)
            run = self._sync_run(run)
            if run["status"] not in ACTIVE_STATUSES:
                return self._format_run(run)
            if not self._signal_verified(run, signal.SIGTERM):
                run = mark_run(
                    run["run_id"],
                    status="orphaned",
                    error="refused to stop worker because process identity changed",
                )
                return self._format_run(run)
            mark_run(run["run_id"], status="stopping")
            deadline = time.monotonic() + self.stop_timeout_s
            while time.monotonic() < deadline:
                time.sleep(0.1)
                current = get_run(run["run_id"])
                assert current is not None
                current = self._sync_run(current)
                if current["status"] not in ACTIVE_STATUSES:
                    return self._format_run(current)
            current = get_run(run["run_id"])
            assert current is not None
            self._signal_verified(current, signal.SIGKILL)
            kill_deadline = time.monotonic() + self.kill_timeout_s
            while time.monotonic() < kill_deadline:
                if not identity_matches(
                    current.get("supervisor_pid"),
                    current.get("supervisor_boot_id"),
                    current.get("supervisor_start_ticks"),
                ):
                    break
                time.sleep(0.05)
            current = mark_run(
                run["run_id"],
                status="stopped",
                error="worker required SIGKILL after stop timeout",
                return_code=-int(signal.SIGKILL),
            )
            return self._format_run(current)


worker_manager = WorkerManager()
