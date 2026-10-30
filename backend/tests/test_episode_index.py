import json

import numpy as np

from robot_data_studio.models import SessionCreate
from robot_data_studio.routes.episodes import index as route_index
from robot_data_studio.services.episode_scanner import episode_detail, list_episodes, scan_session, update_qa
from robot_data_studio.services.session_service import create_session, restore_session, trash_session


def test_scan_detail_and_qa_keep_outcomes_separate(isolated_settings):
    session = create_session(SessionCreate(dataset_name="pilot", scene_id="cloth_corner_lift", control_mode="gello"))
    root = isolated_settings.data_root / "datasets" / "pilot" / "raw" / session["id"] / "episode_000000"
    root.mkdir()
    manifest = {
        "episode_uuid": "stable-uuid", "episode_index": 0,
        "task": "lift corner", "num_frames": 3,
        "operator_success": True, "auto_success": False, "failure_reason": "automatic_criterion_not_met",
        "camera_names": ["front"], "fps": 10, "scene": {"seed": 3},
        "created_at": "2026-08-30T00:00:00+00:00",
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "front_rgb").mkdir()
    for index in range(3):
        (root / "front_rgb" / f"{index:06d}.jpg").write_bytes(b"jpeg")
    np.savez_compressed(
        root / "trajectory.npz",
        state=np.zeros((3, 18)),
        actions=np.zeros((3, 9)),
        frame_index=np.arange(3),
        timestamp=np.arange(3) / 10,
        sim_time=np.arange(3) / 10,
        policy_state=np.zeros((3, 8)),
        policy_action=np.ones((3, 8)),
        reward=np.zeros(3),
    )
    result = scan_session(session["id"])
    assert {key: result[key] for key in ("indexed", "skipped", "invalid")} == {"indexed": 1, "skipped": 0, "invalid": 0}
    assert result["invalid_episodes"] == []
    episode = list_episodes()[0]
    assert episode["operator_success"] == 1
    assert episode["auto_success"] == 0
    assert episode["qa_status"] == "pending"
    assert episode["episode_index"] == 0
    assert episode["fps"] == 10
    assert episode["duration_s"] == 0.3
    assert episode["scene_id"] == "cloth_corner_lift"
    assert episode["engine_id"] == "genesis"
    assert episode["control_mode"] == "gello"
    assert episode["seed"] == 3
    assert episode["source_trajectory"] is None
    assert episode["duplicate_group_size"] == 1
    assert episode["is_duplicate"] is False
    assert list_episodes(dataset_id=session["dataset_id"])[0]["id"] == episode["id"]
    assert list_episodes(engine_id="genesis")[0]["id"] == episode["id"]
    assert list_episodes(engine_id="isaac_sim") == []
    assert list_episodes(dataset_id=session["dataset_id"] + 1) == []
    update_qa(episode["id"], "accepted", "human override after replay")
    detail = episode_detail(episode["id"])
    assert detail["qa_status"] == "accepted"
    assert detail["operator_success"] == 1 and detail["auto_success"] == 0
    assert detail["engine_id"] == "genesis"
    assert detail["dataset_id"] == session["dataset_id"]
    assert len(detail["trajectory"]["policy_action"]) == 3

    trash_session(session["id"])
    assert list_episodes() == []
    restore_session(session["id"])
    assert list_episodes()[0]["episode_uuid"] == "stable-uuid"


def test_roboverse_is_an_allowlisted_episode_filter(isolated_settings) -> None:
    assert route_index(engine_id="roboverse") == []


def test_duplicate_source_trajectory_is_visible_across_sessions(isolated_settings):
    sessions = [
        create_session(
            SessionCreate(
                dataset_name="duplicate-pilot",
                scene_id="cloth_corner_lift",
                control_mode="gello",
            )
        )
        for _ in range(2)
    ]
    for index, session in enumerate(sessions):
        root = (
            isolated_settings.data_root
            / "datasets"
            / "duplicate-pilot"
            / "raw"
            / session["id"]
            / "episode_000000"
        )
        root.mkdir()
        manifest = {
            "episode_uuid": f"duplicate-uuid-{index}",
            "episode_index": 0,
            "task": "lift corner",
            "num_frames": 3,
            "operator_success": True,
            "auto_success": True,
            "failure_reason": None,
            "camera_names": [],
            "fps": 10,
            "scene": {
                "seed": 17,
                "parameters": {"source_demo_trajectory": "traj_17"},
            },
            "created_at": f"2026-08-30T00:00:0{index}+00:00",
        }
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        np.savez_compressed(
            root / "trajectory.npz",
            state=np.zeros((3, 18)),
            actions=np.zeros((3, 9)),
            frame_index=np.arange(3),
            timestamp=np.arange(3) / 10,
            sim_time=np.arange(3) / 10,
            policy_state=np.zeros((3, 8)),
            policy_action=np.ones((3, 8)),
            reward=np.zeros(3),
        )
        scan = scan_session(session["id"])
        assert scan["indexed"] == 1, scan

    filtered = list_episodes(session_id=sessions[0]["id"])
    assert len(filtered) == 1
    assert filtered[0]["source_trajectory"] == "traj_17"
    assert filtered[0]["seed"] == 17
    assert filtered[0]["duplicate_group_size"] == 2
    assert filtered[0]["is_duplicate"] is True
