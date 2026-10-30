from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

import robot_data_studio.services.worker_manager as worker_manager_module
from robot_data_studio.adapters.base import WorkerLaunch, WorkerReadiness
from robot_data_studio.db import transaction
from robot_data_studio.models import SessionCreate
from robot_data_studio.services.session_service import create_session, get_session
from robot_data_studio.services.worker_manager import WorkerManager
from robot_data_studio.services.worker_runtime import (
    ResourceConflict,
    create_run,
    get_run,
    mark_run,
    process_identity,
    run_resources,
    set_supervisor_identity,
)


FAKE_WORKER = Path(__file__).parent / "fixtures" / "fake_worker.py"
SUPERVISOR = Path(__file__).parents[1] / "src" / "robot_data_studio" / "worker_supervisor.py"


class FakeAdapter:
    adapter_id = "roboverse"

    def __init__(self, *args: str):
        self.args = list(args)

    def build_worker_launch(self, config, output_dir: Path) -> WorkerLaunch:
        return WorkerLaunch(
            command=[sys.executable, str(FAKE_WORKER), *self.args],
            cwd=output_dir,
            readiness=WorkerReadiness(kind="marker", timeout_s=2.0),
            resources=(
                "simulator:global",
                f"gpu:{config['gpu']}",
                f"output:{output_dir.resolve()}",
            ),
        )


class PortAdapter(FakeAdapter):
    """A launch that claims a collector port, as the Genesis adapter does."""

    def __init__(self, port: int, *args: str):
        super().__init__(*args)
        self.port = port

    def build_worker_launch(self, config, output_dir: Path) -> WorkerLaunch:
        launch = super().build_worker_launch(config, output_dir)
        return WorkerLaunch(
            command=launch.command,
            cwd=launch.cwd,
            readiness=launch.readiness,
            resources=(*launch.resources, f"tcp:{self.port}"),
        )


class MissingCommandAdapter(FakeAdapter):
    def build_worker_launch(self, config, output_dir: Path) -> WorkerLaunch:
        launch = super().build_worker_launch(config, output_dir)
        return WorkerLaunch(
            command=[str(output_dir / "does-not-exist")],
            cwd=launch.cwd,
            readiness=launch.readiness,
            resources=launch.resources,
        )


def new_session(name: str) -> dict:
    return create_session(
        SessionCreate(
            engine_id="roboverse",
            dataset_name=name,
            scene_id="maniskill_pick_cube_native",
            control_mode="scripted",
            target_episodes=1,
            control_fps=20,
            camera_profile_id="roboverse_sapien_base_v1",
            scene_params={},
        )
    )


def wait_status(
    manager: WorkerManager, session_id: str, expected: str, timeout: float = 4.0
) -> dict:
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        latest = manager.status(session_id)
        if latest["status"] == expected:
            return latest
        time.sleep(0.03)
    raise AssertionError(f"worker never reached {expected}: {latest}")


def force_cleanup(status: dict | None) -> None:
    if not status or not status.get("supervisor_pid"):
        return
    try:
        os.killpg(int(status["supervisor_pid"]), signal.SIGKILL)
    except ProcessLookupError:
        pass


def test_manager_reconciles_same_run_after_restart(isolated_settings, monkeypatch) -> None:
    session = new_session("restart_reconcile")
    monkeypatch.setattr(worker_manager_module, "get_engine", lambda _engine: FakeAdapter())
    manager = WorkerManager(monitor_interval_s=0.05)
    status = None
    try:
        started = manager.start(session["id"])
        status = wait_status(manager, session["id"], "running")
        assert status["run_id"] == started["run_id"]
        restarted_manager = WorkerManager(monitor_interval_s=0.05)
        recovered = restarted_manager.status(session["id"])
        assert recovered["status"] == "running"
        assert recovered["run_id"] == started["run_id"]
        assert recovered["heartbeat_at"] is not None
        stopped = restarted_manager.stop(session["id"])
        assert stopped["status"] == "stopped"
        status = stopped
    finally:
        force_cleanup(status)


def test_manager_recovers_supervisor_after_launching_parent_exits(
    isolated_settings,
) -> None:
    session = new_session("parent_restart_reconcile")
    output_root = Path(session["config"]["episode_root"])
    runtime_root = output_root / ".studio" / "runs" / "parent-exit-run"
    spec_path = runtime_root / "launch.json"
    state_path = runtime_root / "state.json"
    ready_path = runtime_root / "ready.json"
    log_path = output_root / "collector.log"
    create_run(
        run_id="parent-exit-run",
        session_id=session["id"],
        engine_id="roboverse",
        command=[sys.executable, str(FAKE_WORKER)],
        cwd=output_root,
        log_path=log_path,
        state_path=state_path,
        readiness={"kind": "marker", "path": str(ready_path), "timeout_s": 2.0},
        resources=("simulator:global", "gpu:0", f"output:{output_root.resolve()}"),
    )
    runtime_root.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        json.dumps(
            {
                "run_id": "parent-exit-run",
                "command": [sys.executable, str(FAKE_WORKER)],
                "cwd": str(output_root),
                "log_path": str(log_path),
                "state_path": str(state_path),
                "readiness": {
                    "kind": "marker",
                    "path": str(ready_path),
                    "timeout_s": 2.0,
                },
                "heartbeat_interval_s": 0.05,
                "child_stop_timeout_s": 0.1,
            }
        ),
        encoding="utf-8",
    )
    launcher = (
        "import subprocess,sys; "
        "p=subprocess.Popen([sys.executable,sys.argv[1],'--spec',sys.argv[2]],"
        "start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        "print(p.pid)"
    )
    env = dict(os.environ)
    env["ROBOT_DATA_STUDIO_READY_FILE"] = str(ready_path)
    parent = subprocess.run(
        [sys.executable, "-c", launcher, str(SUPERVISOR), str(spec_path)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    supervisor_pid = int(parent.stdout.strip())
    process_boot_id, start_ticks = process_identity(supervisor_pid)
    set_supervisor_identity(
        "parent-exit-run",
        pid=supervisor_pid,
        process_boot_id=process_boot_id,
        start_ticks=start_ticks,
    )
    manager = WorkerManager()
    status = None
    try:
        status = wait_status(manager, session["id"], "running")
        assert status["run_id"] == "parent-exit-run"
        assert status["heartbeat_at"] is not None
        status = manager.stop(session["id"])
        assert status["status"] == "stopped"
    finally:
        force_cleanup(status or {"supervisor_pid": supervisor_pid})


def test_manager_records_nonzero_exit_and_releases_locks(isolated_settings, monkeypatch) -> None:
    session = new_session("nonzero_exit")
    monkeypatch.setattr(
        worker_manager_module,
        "get_engine",
        lambda _engine: FakeAdapter("--exit-code", "23", "--lifetime", "0.1"),
    )
    manager = WorkerManager()
    manager.start(session["id"])
    failed = wait_status(manager, session["id"], "failed")
    assert failed["return_code"] == 23
    assert "return code 23" in failed["error"]
    assert failed["resources"] == []
    assert manager.status(session["id"])["status"] == "failed"


def test_manager_records_child_launch_failure(isolated_settings, monkeypatch) -> None:
    session = new_session("launch_failure")
    monkeypatch.setattr(
        worker_manager_module, "get_engine", lambda _engine: MissingCommandAdapter()
    )
    manager = WorkerManager()
    try:
        manager.start(session["id"])
    except OSError:
        pass
    failed = wait_status(manager, session["id"], "failed")
    assert failed["return_code"] == 127
    assert "launch failed" in failed["error"]


def test_manager_stop_handles_sigterm_and_sigkill(isolated_settings, monkeypatch) -> None:
    session = new_session("sigkill_fallback")
    monkeypatch.setattr(
        worker_manager_module,
        "get_engine",
        lambda _engine: FakeAdapter("--ignore-sigterm"),
    )
    manager = WorkerManager(stop_timeout_s=0.5, kill_timeout_s=0.5)
    status = None
    try:
        manager.start(session["id"])
        status = wait_status(manager, session["id"], "running")
        stopped = manager.stop(session["id"])
        assert stopped["status"] == "stopped"
        assert stopped["return_code"] == -int(signal.SIGKILL)
        status = stopped
    finally:
        force_cleanup(status)


def test_manager_stop_records_graceful_sigterm_as_stopped(
    isolated_settings, monkeypatch
) -> None:
    session = new_session("graceful_sigterm")
    monkeypatch.setattr(worker_manager_module, "get_engine", lambda _engine: FakeAdapter())
    manager = WorkerManager(stop_timeout_s=1.0, kill_timeout_s=0.5)
    status = None
    try:
        manager.start(session["id"])
        status = wait_status(manager, session["id"], "running")
        stopped = manager.stop(session["id"])
        assert stopped["status"] == "stopped"
        assert stopped["return_code"] == 0
        assert stopped["error"] is None
        assert stopped["resources"] == []
        status = stopped
    finally:
        force_cleanup(status)


def test_manager_rereads_terminal_state_before_marking_orphaned(
    isolated_settings, monkeypatch
) -> None:
    session = new_session("terminal_state_race")
    state_path = isolated_settings.data_root / "terminal-state.json"
    create_run(
        run_id="terminal-state-race-run",
        session_id=session["id"],
        engine_id="roboverse",
        command=["fake"],
        cwd=isolated_settings.data_root,
        log_path=isolated_settings.data_root / "terminal-state.log",
        state_path=state_path,
        readiness={"kind": "process", "timeout_s": 1.0},
        resources=("gpu:4",),
    )
    terminal_state = {
        "run_id": "terminal-state-race-run",
        "status": "stopped",
        "supervisor_pid": 999999,
        "child_pid": 999998,
        "ready_at": "2026-09-16T00:00:00+00:00",
        "heartbeat_at": "2026-09-16T00:00:01+00:00",
        "stopped_at": "2026-09-16T00:00:02+00:00",
        "return_code": -int(signal.SIGTERM),
        "error": None,
    }
    states = iter(
        [
            terminal_state | {"status": "stopping", "stopped_at": None},
            terminal_state,
        ]
    )
    monkeypatch.setattr(worker_manager_module, "read_state", lambda _path: next(states))
    monkeypatch.setattr(worker_manager_module, "identity_matches", lambda *_args: False)

    run = get_run("terminal-state-race-run")
    assert run is not None
    stopped = WorkerManager()._sync_run(run)
    assert stopped["status"] == "stopped"
    assert stopped["return_code"] == -int(signal.SIGTERM)
    assert run_resources("terminal-state-race-run") == []


def test_manager_refuses_pid_identity_mismatch(isolated_settings, monkeypatch) -> None:
    session = new_session("identity_mismatch")
    monkeypatch.setattr(worker_manager_module, "get_engine", lambda _engine: FakeAdapter())
    manager = WorkerManager()
    status = None
    try:
        manager.start(session["id"])
        status = wait_status(manager, session["id"], "running")
        with transaction() as connection:
            connection.execute(
                "UPDATE worker_runs SET supervisor_start_ticks = supervisor_start_ticks + 1 WHERE run_id = ?",
                (status["run_id"],),
            )
        orphaned = manager.status(session["id"])
        assert orphaned["status"] == "orphaned"
        assert "identity" in orphaned["error"]
        assert orphaned["resources"] == []
    finally:
        force_cleanup(status)


def test_resource_locks_report_all_conflicts(isolated_settings) -> None:
    first = new_session("lock_first")
    second = new_session("lock_second")
    resources = ("gpu:4", "tcp:18080", "output:/tmp/shared-output")
    create_run(
        run_id="first-run",
        session_id=first["id"],
        engine_id="roboverse",
        command=["fake"],
        cwd=Path("/tmp"),
        log_path=Path("/tmp/first.log"),
        state_path=Path("/tmp/first-state.json"),
        readiness={"kind": "process", "timeout_s": 1},
        resources=resources,
    )
    with pytest.raises(ResourceConflict) as caught:
        create_run(
            run_id="second-run",
            session_id=second["id"],
            engine_id="roboverse",
            command=["fake"],
            cwd=Path("/tmp"),
            log_path=Path("/tmp/second.log"),
            state_path=Path("/tmp/second-state.json"),
            readiness={"kind": "process", "timeout_s": 1},
            resources=resources,
        )
    assert {item["resource_key"] for item in caught.value.conflicts} == set(resources)
    mark_run("first-run", status="failed", error="test cleanup")
    assert run_resources("first-run") == []


def test_preflight_ignores_sockets_left_over_from_a_stopped_worker() -> None:
    """A stopped worker leaves its client sockets lingering on its own port.

    Killing the collector closes the server side of every browser connection, so
    that port holds a FIN_WAIT_2 (browser still connected) or TIME_WAIT socket for
    up to a minute. The worker binds with SO_REUSEADDR, so the next launch would
    succeed; probing with reuse disabled refused it instead, and the database
    recorded `host TCP port ... is unavailable` for a port that was in fact free.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen(1)
        with socket.create_connection(("127.0.0.1", port)) as browser:
            connection, _ = listener.accept()
            # The worker dies with the browser still attached, which is when an
            # operator stops and immediately restarts the collector.
            connection.close()
            listener.close()
            WorkerManager()._preflight_ports((f"tcp:{port}",))


def test_preflight_still_rejects_a_port_a_live_listener_holds() -> None:
    """Reuse tolerance must not blind the check to a genuinely occupied port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", 0))
        port = listener.getsockname()[1]
        listener.listen(1)
        with pytest.raises(RuntimeError, match="is unavailable"):
            WorkerManager()._preflight_ports((f"tcp:{port}",))


def test_start_succeeds_right_after_a_stop_lingered_on_the_port(
    isolated_settings, monkeypatch
) -> None:
    """The operator's stop-then-start flow, on a port the last worker left behind."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        # The collector serves through `websockets.serve`, whose listening socket
        # sets SO_REUSEADDR; accepted connections inherit it. That inherited flag
        # is what makes the leftover socket bindable again, so a listener without
        # it would not model the collector.
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen(1)
        browser = socket.create_connection(("127.0.0.1", port))
        connection, _ = listener.accept()
        session = new_session("port_lingering")
        monkeypatch.setattr(
            worker_manager_module, "get_engine", lambda _engine: PortAdapter(port)
        )
        manager = WorkerManager()
        status = None
        try:
            connection.close()
            listener.close()
            manager.start(session["id"])
            status = wait_status(manager, session["id"], "running")
            status = manager.stop(session["id"])
            assert status["status"] == "stopped"
            manager.start(session["id"])
            status = wait_status(manager, session["id"], "running")
        finally:
            browser.close()
            force_cleanup(status)


def test_legacy_running_session_becomes_orphaned(isolated_settings) -> None:
    session = new_session("legacy_orphan")
    with transaction() as connection:
        connection.execute(
            "UPDATE sessions SET status = 'running', worker_pid = 999999 WHERE id = ?",
            (session["id"],),
        )
    result = WorkerManager().reconcile()
    assert result["legacy_orphans"] == [session["id"]]
    reconciled = get_session(session["id"])
    assert reconciled["status"] == "orphaned"
    assert reconciled["worker_pid"] is None


def test_monitor_waits_for_identity_registration_and_refreshes_early_snapshot(
    isolated_settings,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    import threading
    session = new_session("identity_registration_race")
    output = Path(session["config"]["episode_root"])
    manager = WorkerManager()
    entered = threading.Event()
    def sync(snapshot):
        entered.set()
        return manager._sync_run(snapshot)
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            # Model start(): create a run and register its PID while holding the
            # manager lock. The monitor captures the pre-registration DB row.
            with manager._lock:
                create_run(run_id="registration-race",session_id=session["id"],engine_id="roboverse",
                    command=[sys.executable],cwd=output,log_path=output/"worker.log",state_path=output/"state.json",
                    readiness={"kind":"marker","timeout_s":2.},resources=("simulator:global","gpu:0"))
                snapshot = get_run("registration-race")
                assert snapshot["supervisor_pid"] is None
                pending = executor.submit(sync, snapshot)
                assert entered.wait(2)
                time.sleep(.05)
                assert not pending.done(), "monitor checked identity before launch registration finished"
                boot, ticks = process_identity(os.getpid())
                set_supervisor_identity("registration-race",pid=os.getpid(),process_boot_id=boot,start_ticks=ticks)
            result = pending.result(timeout=2)
            assert result["status"] == "starting"
            assert result["supervisor_pid"] == os.getpid()
            assert run_resources("registration-race") == ["gpu:0","simulator:global"]
            # Reentrant calls made by start()/stop() must not deadlock.
            with manager._lock:
                assert manager._sync_run(snapshot)["status"] == "starting"
        finally:
            mark_run("registration-race",status="stopped")
