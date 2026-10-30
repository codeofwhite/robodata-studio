from datetime import datetime, timezone

import pytest

from robot_data_studio.models import SessionCreate
from robot_data_studio.db import transaction
from robot_data_studio.services.session_service import (
    build_session_id,
    create_session,
    get_session,
    list_sessions,
    permanently_delete_session,
    restore_session,
    trash_session,
)


def test_session_id_is_human_readable_and_time_sortable() -> None:
    session_id = build_session_id(
        "rigid_pick_place",
        "keyboard",
        created_at=datetime(2026, 9, 2, 14, 15, 30, tzinfo=timezone.utc),
        unique_suffix="38b22c62",
    )
    assert session_id == "20260902T221530+0800_rigid_pick_place_keyboard_38b22c62"


def test_session_id_normalizes_components_and_rejects_bad_suffix() -> None:
    session_id = build_session_id(
        "Rigid Pick/Place",
        "Browser Keyboard",
        created_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        unique_suffix="abcdef01",
    )
    assert session_id == "20260902T080000+0800_rigid_pick_place_browser_keyboard_abcdef01"
    with pytest.raises(ValueError, match="8 lowercase hex"):
        build_session_id("scene", "keyboard", unique_suffix="NOT-HEX")


def test_create_and_get_session(isolated_settings):
    payload = SessionCreate(
        dataset_name="pilot", scene_id="cloth_corner_lift", control_mode="gello",
        target_episodes=20, port=8084, gpu=1,
    )
    session = create_session(payload)
    assert session["status"] == "draft"
    assert session["engine_id"] == "genesis"
    assert session["config"]["control_mode"] == "gello"
    assert session["config"]["camera_profile_id"] == "lab_d435i_dual_v1"
    assert session["config"]["renderer_profile_id"] is None
    assert session["config"]["sim_dt"] == pytest.approx(0.01)
    assert session["config"]["physics_steps_per_control"] == 10
    assert session["id"].endswith("_cloth_corner_lift_gello_" + session["id"][-8:])
    detail = get_session(session["id"])
    assert detail["episode_count"] == 0
    assert detail["collector_url"] == "http://127.0.0.1:8084"


def test_rejects_unsafe_dataset_name(isolated_settings):
    with pytest.raises(ValueError, match="simple name"):
        SessionCreate(dataset_name="../escape", scene_id="rigid_pick_place", control_mode="keyboard")


def test_isaac_session_persists_engine_and_accepts_keyboard_control(isolated_settings):
    payload = SessionCreate(
        engine_id="isaac_sim",
        dataset_name="isaac_pilot",
        scene_id="franka_empty",
        control_mode="gello",
    )
    session = create_session(payload)
    assert session["engine_id"] == "isaac_sim"
    assert session["adapter_id"] == "isaac_sim"
    assert session["config"]["renderer_profile_id"] == "isaac_balanced_v1"

    keyboard_session = create_session(
        SessionCreate(
            engine_id="isaac_sim",
            dataset_name="isaac_keyboard_pilot",
            scene_id="franka_empty",
            control_mode="keyboard",
        )
    )
    assert keyboard_session["engine_id"] == "isaac_sim"
    assert keyboard_session["control_mode"] == "keyboard"
    assert keyboard_session["config"]["control_mode"] == "keyboard"


def test_renderer_profile_is_rejected_for_non_isaac_engine() -> None:
    with pytest.raises(ValueError, match="only by Isaac Sim"):
        SessionCreate(
            dataset_name="pilot", scene_id="rigid_pick_place", control_mode="keyboard",
            renderer_profile_id="isaac_quality_v1",
        )


def test_physics_backend_is_rejected_for_non_isaac_engine() -> None:
    with pytest.raises(ValueError, match="only by Isaac Sim"):
        SessionCreate(
            dataset_name="pilot", scene_id="rigid_pick_place", control_mode="keyboard",
            physics_backend="newton",
        )


def test_isaac_session_keeps_the_requested_physics_backend(isolated_settings):
    """A POSTed physics_backend must survive into the stored config.

    SessionCreate has no `model_config`, so pydantic's default `extra="ignore"`
    drops unknown keys without an error -- the session still creates and the
    adapter quietly falls back to settings. This asserts the field is declared.
    """
    session = create_session(
        SessionCreate(
            engine_id="isaac_sim",
            dataset_name="isaac_newton_pilot",
            scene_id="franka_empty",
            control_mode="gello",
            physics_backend="newton",
        )
    )
    assert session["config"]["physics_backend"] == "newton"

    default_session = create_session(
        SessionCreate(
            engine_id="isaac_sim",
            dataset_name="isaac_default_pilot",
            scene_id="franka_empty",
            control_mode="gello",
        )
    )
    # None means "adapter fills it from settings", not "physx".
    assert default_session["config"]["physics_backend"] is None


def test_roboverse_session_is_noninteractive_batch_worker(isolated_settings):
    session = create_session(
        SessionCreate(
            engine_id="roboverse",
            dataset_name="roboverse_pilot",
            scene_id="maniskill_pick_cube_native",
            control_mode="scripted",
            target_episodes=1,
            control_fps=20,
            camera_profile_id="roboverse_sapien_base_v1",
                scene_params={},
        )
    )
    assert session["engine_id"] == "roboverse"
    assert session["collector_url"] is None


def test_session_can_move_to_trash_and_restore(isolated_settings) -> None:
    session = create_session(
        SessionCreate(dataset_name="pilot", scene_id="rigid_pick_place", control_mode="keyboard")
    )
    original_root = isolated_settings.data_root / "datasets" / "pilot" / "raw" / session["id"]
    (original_root / "marker.txt").write_text("keep", encoding="utf-8")

    trashed = trash_session(session["id"])

    trash_root = isolated_settings.data_root / "trash" / "sessions" / session["id"]
    assert trashed["status"] == "trashed"
    assert not original_root.exists()
    assert (trash_root / "marker.txt").read_text(encoding="utf-8") == "keep"
    assert session["id"] not in {item["id"] for item in list_sessions()}
    assert session["id"] in {item["id"] for item in list_sessions(include_trashed=True)}

    restored = restore_session(session["id"])

    assert restored["status"] == "draft"
    assert (original_root / "marker.txt").read_text(encoding="utf-8") == "keep"
    assert not trash_root.exists()


def test_permanent_delete_requires_trash_and_accepted_confirmation(isolated_settings) -> None:
    session = create_session(
        SessionCreate(dataset_name="pilot", scene_id="rigid_pick_place", control_mode="keyboard")
    )
    root = isolated_settings.data_root / "datasets" / "pilot" / "raw" / session["id"]
    with transaction() as connection:
        connection.execute(
            """INSERT INTO episodes(session_id, episode_uuid, path, task, operator_success,
               auto_success, qa_status, failure_reason, num_frames, manifest_json, created_at, indexed_at)
               VALUES (?, ?, ?, 'task', 1, 1, 'accepted', NULL, 1, '{}', NULL, 'now')""",
            (session["id"], "episode-uuid", str(root / "episode_000000")),
        )
    with pytest.raises(ValueError, match="move the session to trash"):
        permanently_delete_session(
            session["id"], confirm_session_id=session["id"], delete_accepted_data=True
        )

    trash_session(session["id"])
    with pytest.raises(ValueError, match="accepted episodes"):
        permanently_delete_session(
            session["id"], confirm_session_id=session["id"], delete_accepted_data=False
        )
    with pytest.raises(ValueError, match="exactly match"):
        permanently_delete_session(
            session["id"], confirm_session_id="wrong", delete_accepted_data=True
        )

    result = permanently_delete_session(
        session["id"], confirm_session_id=session["id"], delete_accepted_data=True
    )

    assert result == {"deleted": True, "session_id": session["id"]}
    assert get_session(session["id"]) is None
    assert not (isolated_settings.data_root / "trash" / "sessions" / session["id"]).exists()
