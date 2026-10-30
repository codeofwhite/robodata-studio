import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from robot_data_studio.db import transaction
from robot_data_studio.models import ExportCreate, SessionCreate
from robot_data_studio.services.export_service import (
    _build_export_launch,
    _export_environment,
    _resolve_selected_episodes,
    _stage_selected_episodes,
    create_export,
    list_exports,
)
from robot_data_studio.services.consumer_smoke_service import _smoke_environment, start_automatic_smoke
from robot_data_studio.services.session_service import create_session, trash_session


@pytest.mark.parametrize("format_name", ["lerobot", "rlds", "robomimic"])
def test_export_format_uses_studio_exporter(format_name, isolated_settings):
    payload = ExportCreate(
        dataset_id=1, episode_ids=[1], format=format_name, output_name="test",
        repo_id="local/test" if format_name == "lerobot" else None,
    )
    command, cwd = _build_export_launch(payload, Path("/tmp/raw"), Path("/tmp/out"))
    expected_module = "lerobot_v3" if format_name == "lerobot" else format_name
    assert command[1:3] == ["-m", f"robot_data_studio.exporters.{expected_module}"]
    assert cwd.name == "robot-data-studio"


def test_openpi_v21_requires_its_explicit_profile_and_repo_id():
    with pytest.raises(ValidationError, match="requires profile openpi_franka_joint8"):
        ExportCreate(
            dataset_id=1, episode_ids=[1], format="openpi_lerobot_v21",
            output_name="openpi", repo_id="local/openpi", profile="physical_joint8",
        )
    with pytest.raises(ValidationError, match="require repo_id"):
        ExportCreate(
            dataset_id=1, episode_ids=[1], format="openpi_lerobot_v21",
            output_name="openpi", profile="openpi_franka_joint8",
        )


def test_openpi_v21_uses_openpi_interpreter_and_studio_exporter(isolated_settings):
    payload = ExportCreate(
        dataset_id=1, episode_ids=[1], format="openpi_lerobot_v21",
        output_name="openpi", repo_id="local/openpi", profile="openpi_franka_joint8",
    )
    command, cwd = _build_export_launch(payload, Path("/tmp/raw"), Path("/tmp/out"))
    assert command[0].endswith("openpi/.venv/bin/python")
    assert command[1:3] == ["-m", "robot_data_studio.exporters.openpi_lerobot_v21"]
    assert cwd.name == "robot-data-studio"


def test_export_request_requires_distinct_selected_episodes():
    with pytest.raises(ValidationError, match="at least 1 item"):
        ExportCreate(dataset_id=1, episode_ids=[], format="lerobot", output_name="pilot")
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        ExportCreate(dataset_id=1, episode_ids=[1, 1], format="lerobot", output_name="pilot")


def test_selected_export_resolves_only_accepted_episodes(isolated_settings):
    session = create_session(
        SessionCreate(dataset_name="pilot", scene_id="rigid_pick_place", control_mode="keyboard")
    )
    other = create_session(
        SessionCreate(dataset_name="other", scene_id="rigid_pick_place", control_mode="keyboard")
    )
    episode_ids: dict[str, int] = {}
    with transaction() as connection:
        for owner, status, name in (
            (session, "accepted", "accepted"),
            (session, "pending", "pending"),
            (other, "accepted", "other"),
        ):
            episode_root = Path(owner["config"]["episode_root"]) / name
            episode_root.mkdir(parents=True)
            cursor = connection.execute(
                """INSERT INTO episodes(session_id, episode_uuid, path, task, operator_success,
                   auto_success, qa_status, failure_reason, num_frames, manifest_json, created_at, indexed_at)
                   VALUES (?, ?, ?, 'task', 1, 1, ?, NULL, 1, '{}', NULL, 'now')""",
                (owner["id"], f"episode-{name}", str(episode_root), status),
            )
            episode_ids[name] = cursor.lastrowid

    selected = _resolve_selected_episodes(session["dataset_id"], [episode_ids["accepted"]])
    assert [episode["id"] for episode in selected] == [episode_ids["accepted"]]
    staging = _stage_selected_episodes(selected, isolated_settings.data_root / "staging")
    assert [path.name for path in staging.iterdir()] == ["episode-accepted"]

    with pytest.raises(ValueError, match="not QA-accepted"):
        _resolve_selected_episodes(session["dataset_id"], [episode_ids["pending"]])
    with pytest.raises(ValueError, match="does not belong"):
        _resolve_selected_episodes(session["dataset_id"], [episode_ids["other"]])

    trash_session(session["id"])
    with pytest.raises(ValueError, match="trashed session"):
        _resolve_selected_episodes(session["dataset_id"], [episode_ids["accepted"]])


def test_export_environment_includes_local_contracts_source():
    paths = _export_environment()["PYTHONPATH"].split(":")
    assert any(path.endswith("packages/robot-data-contracts/src") for path in paths)


def test_failed_preflight_creates_neither_job_nor_staging(isolated_settings):
    session = create_session(
        SessionCreate(dataset_name="pilot", scene_id="rigid_pick_place", control_mode="keyboard")
    )
    episode_root = Path(session["config"]["episode_root"]) / "invalid"
    episode_root.mkdir(parents=True)
    with transaction() as connection:
        cursor = connection.execute(
            """INSERT INTO episodes(session_id, episode_uuid, path, task, operator_success,
               auto_success, qa_status, failure_reason, num_frames, manifest_json, created_at, indexed_at)
               VALUES (?, 'invalid-canonical', ?, 'task', 1, 1, 'accepted', NULL, 1, '{}', NULL, 'now')""",
            (session["id"], str(episode_root)),
        )
        episode_id = cursor.lastrowid

    with pytest.raises(ValueError, match="episode preflight failed"):
        create_export(
            ExportCreate(
                dataset_id=session["dataset_id"], episode_ids=[episode_id],
                format="robomimic", output_name="must_not_exist",
            )
        )

    export_root = isolated_settings.data_root / "datasets" / "pilot" / "exports"
    assert not export_root.exists()
    with transaction() as connection:
        assert connection.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0


def test_export_persists_selection_and_rejects_reserved_output(
    isolated_settings, monkeypatch
):
    session = create_session(
        SessionCreate(dataset_name="pilot", scene_id="rigid_pick_place", control_mode="keyboard")
    )
    episode_root = Path(session["config"]["episode_root"]) / "accepted"
    episode_root.mkdir(parents=True)
    with transaction() as connection:
        cursor = connection.execute(
            """INSERT INTO episodes(session_id, episode_uuid, path, task, operator_success,
               auto_success, qa_status, failure_reason, num_frames, manifest_json, created_at, indexed_at)
               VALUES (?, 'episode-selected', ?, 'task', 1, 1, 'accepted', NULL, 1, ?, NULL, 'now')""",
            (session["id"], str(episode_root), json.dumps({"episode_index": 12})),
        )
        episode_id = cursor.lastrowid

    class FakeProcess:
        pid = 1234

    class NoopThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(
        "robot_data_studio.services.export_service.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )
    monkeypatch.setattr(
        "robot_data_studio.services.export_service.threading.Thread", NoopThread
    )
    monkeypatch.setattr(
        "robot_data_studio.services.export_service.preflight_export",
        lambda *args, **kwargs: {"compatible": True},
    )
    payload = ExportCreate(
        dataset_id=session["dataset_id"],
        episode_ids=[episode_id],
        format="openpi_lerobot_v21",
        output_name="selected_v1",
        repo_id="local/selected_v1",
        images=True,
        profile="openpi_franka_joint8",
    )

    job = create_export(payload)

    assert job["episode_ids"] == [episode_id]
    assert job["episode_count"] == 1
    assert job["profile"] == "openpi_franka_joint8"
    assert job["images"] == 1
    assert job["episode_refs"] == [{
        "episode_id": episode_id,
        "session_id": session["id"],
        "episode_index": 12,
        "engine_id": None,
        "engine_version": None,
        "worker_id": None,
        "scene_id": None,
        "position": 0,
    }]
    assert list_exports()[0]["episode_ids"] == [episode_id]
    assert list_exports()[0]["episode_refs"] == job["episode_refs"]
    with pytest.raises(ValueError, match="already reserved"):
        create_export(payload)


def test_fastwam_export_creates_separate_processor_smoke_job(
    isolated_settings, monkeypatch
):
    session = create_session(
        SessionCreate(dataset_name="pilot", scene_id="rigid_pick_place", control_mode="keyboard")
    )
    episode_root = Path(session["config"]["episode_root"]) / "accepted"
    episode_root.mkdir(parents=True)
    with transaction() as connection:
        cursor = connection.execute(
            """INSERT INTO episodes(session_id, episode_uuid, path, task, operator_success,
               auto_success, qa_status, failure_reason, num_frames, manifest_json, created_at, indexed_at)
               VALUES (?, 'episode-fastwam', ?, 'task', 1, 1, 'accepted', NULL, 1, '{}', NULL, 'now')""",
            (session["id"], str(episode_root)),
        )
        episode_id = cursor.lastrowid

    class FakeProcess:
        pid = 4321

    class NoopThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(
        "robot_data_studio.services.export_service.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )
    monkeypatch.setattr(
        "robot_data_studio.services.export_service.threading.Thread", NoopThread,
    )
    monkeypatch.setattr(
        "robot_data_studio.services.export_service.preflight_export",
        lambda *args, **kwargs: {"compatible": True},
    )
    job = create_export(
        ExportCreate(
            dataset_id=session["dataset_id"], episode_ids=[episode_id], format="lerobot",
            output_name="fastwam", repo_id="local/fastwam", profile="fastwam_franka_joint8",
        )
    )
    monkeypatch.setattr(
        "robot_data_studio.services.consumer_smoke_service.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )
    monkeypatch.setattr(
        "robot_data_studio.services.consumer_smoke_service.threading.Thread", NoopThread,
    )
    smoke = start_automatic_smoke(job["id"])
    assert smoke["consumer"] == "fastwam"
    assert smoke["status"] == "running"
    assert smoke["command"][0].endswith("envs/lerobot-fastwam/bin/python")
    assert smoke["report_path"].endswith("consumer_smoke/fastwam.json")


def test_openpi_smoke_uses_local_checkpoint_and_one_visible_gpu(
    isolated_settings, monkeypatch
):
    session = create_session(
        SessionCreate(dataset_name="pilot", scene_id="rigid_pick_place", control_mode="keyboard")
    )
    with transaction() as connection:
        connection.execute(
            """INSERT INTO exports(id, dataset_id, format, status, output_path, created_at, updated_at)
               VALUES ('openpi-job', ?, 'openpi_lerobot_v21', 'completed', ?, 'now', 'now')""",
            (
                session["dataset_id"],
                str(isolated_settings.data_root / "exports" / "openpi"),
            ),
        )
        connection.execute(
            """INSERT INTO export_specs(export_id, output_name, repo_id, images, profile)
               VALUES ('openpi-job', 'openpi', 'local/openpi', 0, 'openpi_franka_joint8')"""
        )

    class FakeProcess:
        pid = 9876

    class NoopThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(
        "robot_data_studio.services.consumer_smoke_service.subprocess.Popen",
        lambda *args, **kwargs: FakeProcess(),
    )
    monkeypatch.setattr(
        "robot_data_studio.services.consumer_smoke_service.threading.Thread", NoopThread,
    )
    smoke = start_automatic_smoke("openpi-job")
    command = smoke["command"]
    assert command[command.index("--checkpoint") + 1].endswith(
        "checkpoints/pi05_franka_joint8_lora/seed0_train16_step2000_v1/1999"
    )
    assert command[command.index("--config-name") + 1] == "pi05_franka_joint8_lora"
    assert command[command.index("--inference-steps") + 1] == "2"
    environment = _smoke_environment("openpi")
    assert environment["CUDA_VISIBLE_DEVICES"] == "7"
    assert environment["JAX_PLATFORMS"] == "cuda"
