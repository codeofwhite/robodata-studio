from pathlib import Path
import json
import sys
import types

import numpy as np
import pytest

from robot_data_studio.roboverse_tasks import ROBOVERSE_TASKS
from robot_data_studio.workers.roboverse import (
    NATIVE_JOINTS,
    _announce_ready,
    _camera_geometry,
    _write_native_payload,
    absolute_native_target,
    classify_task_failure,
    extract_native_state,
    load_demo_metadata,
    restore_demo_initial_state,
    summarize_task_metrics,
    successful_demo_keys,
)


class Joint:
    def __init__(self, name: str):
        self._name = name

    def get_name(self) -> str:
        return self._name


class Robot:
    def __init__(self, names: list[str]):
        self.names = names

    def get_active_joints(self):
        return [Joint(name) for name in self.names]

    def get_qpos(self):
        return np.arange(len(self.names), dtype=np.float32) + 10

    def get_qvel(self):
        return np.arange(len(self.names), dtype=np.float32) + 20


class Handler:
    def __init__(self, active_names: list[str], target_names: list[str]):
        self.object_ids = {"panda": Robot(active_names)}
        self.target_names = target_names

    def get_joint_names(self, _robot: str, *, sort: bool):
        assert sort is True
        return self.target_names


class Task:
    def __init__(self):
        active = list(reversed(NATIVE_JOINTS))
        targets = [NATIVE_JOINTS[2], *NATIVE_JOINTS[:2], *NATIVE_JOINTS[3:]]
        self.handler = Handler(active, targets)

    def _targets_from_action(self, _action):
        return np.arange(len(self.handler.target_names), dtype=np.float32)[None, :] + 100


def test_roboverse_joint_values_are_name_aligned() -> None:
    task = Task()
    state = extract_native_state(task)
    targets = absolute_native_target(task, np.zeros(8, dtype=np.float32))

    active_names = list(reversed(NATIVE_JOINTS))
    expected_qpos = [active_names.index(name) + 10 for name in NATIVE_JOINTS]
    expected_qvel = [active_names.index(name) + 20 for name in NATIVE_JOINTS]
    target_names = task.handler.target_names
    expected_targets = [target_names.index(name) + 100 for name in NATIVE_JOINTS]
    np.testing.assert_array_equal(state, np.asarray(expected_qpos + expected_qvel))
    np.testing.assert_array_equal(targets, np.asarray(expected_targets))


def test_successful_demo_selection_is_numeric_and_success_only() -> None:
    action = np.zeros((50, 8), dtype=np.float32)
    demos = {
        "traj_10": {"actions": action, "success": np.asarray([True])},
        "traj_2": {"actions": action, "success": np.asarray([True])},
        "traj_1": {"actions": action, "success": np.asarray([False])},
    }

    assert successful_demo_keys(demos, 2) == ["traj_2", "traj_10"]


def test_successful_demo_selection_applies_offset_and_metadata() -> None:
    action = np.zeros((50, 8), dtype=np.float32)
    demos = {
        f"traj_{index}": {"actions": action, "success": np.asarray([True])}
        for index in range(4)
    }
    metadata = {
        f"traj_{index}": {"success": index != 1, "episode_seed": 100 + index}
        for index in range(4)
    }

    assert successful_demo_keys(
        demos, 2, offset=1, metadata=metadata, task_label="PickCube-v1"
    ) == ["traj_2", "traj_3"]


def test_demo_metadata_validates_task_and_preserves_source_seed(tmp_path: Path) -> None:
    descriptor = ROBOVERSE_TASKS["maniskill_push_cube_native"]
    path = tmp_path / "demo.json"
    path.write_text(
        json.dumps(
            {
                "env_info": {
                    "env_id": "PushCube-v1",
                    "env_kwargs": {"control_mode": "pd_joint_delta_pos"},
                    "max_episode_steps": 50,
                },
                "episodes": [
                    {
                        "episode_id": 7,
                        "episode_seed": 123456,
                        "success": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    metadata = load_demo_metadata(path, descriptor)

    assert metadata["traj_7"]["episode_seed"] == 123456


class _FakeRigid:
    def __init__(self):
        self.linear = None
        self.angular = None

    def set_linear_velocity(self, value):
        self.linear = np.asarray(value)

    def set_angular_velocity(self, value):
        self.angular = np.asarray(value)


class _FakeActor:
    def __init__(self):
        self.pose = None
        self.rigid = _FakeRigid()

    def set_pose(self, pose):
        self.pose = pose

    def find_component_by_type(self, _kind):
        return self.rigid


class _FakeRobot:
    def __init__(self):
        self.qpos = None
        self.qvel = None

    def set_qpos(self, value):
        self.qpos = np.asarray(value)

    def set_qvel(self, value):
        self.qvel = np.asarray(value)


def test_restore_demo_initial_state_restores_all_task_actors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sapien = types.ModuleType("sapien")
    physx = types.ModuleType("sapien.physx")
    physx.PhysxRigidDynamicComponent = type("PhysxRigidDynamicComponent", (), {})
    sapien.Pose = lambda p, q: (np.asarray(p), np.asarray(q))
    sapien.physx = physx
    monkeypatch.setitem(sys.modules, "sapien", sapien)
    monkeypatch.setitem(sys.modules, "sapien.physx", physx)
    robot = _FakeRobot()
    cube_a = _FakeActor()
    cube_b = _FakeActor()
    task = types.SimpleNamespace(
        handler=types.SimpleNamespace(
            object_ids={"panda": robot, "cubeA": cube_a, "cubeB": cube_b}
        )
    )
    articulation = np.arange(13 + 2 * len(NATIVE_JOINTS), dtype=np.float32)
    actor_a = np.arange(13, dtype=np.float32)
    actor_b = np.arange(13, dtype=np.float32) + 20
    demo = {
        "env_states": {
            "articulations": {"panda_wristcam": np.asarray([articulation])},
            "actors": {
                "cubeA": np.asarray([actor_a]),
                "cubeB": np.asarray([actor_b]),
            },
        }
    }

    restore_demo_initial_state(
        task, demo, ROBOVERSE_TASKS["maniskill_stack_cube_native"]
    )

    np.testing.assert_array_equal(robot.qpos, articulation[13:22])
    np.testing.assert_array_equal(cube_a.rigid.linear, actor_a[7:10])
    np.testing.assert_array_equal(cube_b.rigid.angular, actor_b[10:13])


@pytest.mark.parametrize(
    ("scene_id", "history", "failure"),
    [
        (
            "maniskill_pick_cube_native",
            [{"goal_distance_m": 0.2, "is_grasped": False, "is_obj_placed": False, "is_robot_static": True}],
            "never_grasped",
        ),
        (
            "maniskill_push_cube_native",
            [{"goal_distance_m": 0.2, "is_obj_placed": False, "is_on_surface": True}],
            "goal_not_reached",
        ),
        (
            "maniskill_stack_cube_native",
            [{"cube_xy_offset_m": 0.2, "cube_z_offset_m": 0.0, "is_grasped": True, "is_on_cube": False, "is_static": False}],
            "stack_alignment_not_reached",
        ),
    ],
)
def test_task_failure_classification(scene_id, history, failure) -> None:
    descriptor = ROBOVERSE_TASKS[scene_id]
    metrics = summarize_task_metrics(descriptor, history)
    assert classify_task_failure(descriptor, metrics) == failure


def test_camera_intrinsics_match_the_configured_resolution() -> None:
    aperture, intrinsics = _camera_geometry(640, 480)
    assert aperture > 0
    assert intrinsics[0][0] == intrinsics[1][1]
    assert intrinsics[0][2] == 320
    assert intrinsics[1][2] == 240


def test_native_payload_has_matching_sha256(tmp_path: Path) -> None:
    arrays = {"action": [np.zeros(8, dtype=np.float32), np.ones(8, dtype=np.float32)]}
    _write_native_payload(tmp_path, arrays)
    payload = tmp_path / "native_trajectory.npz"
    checksum = (tmp_path / "native_payload.sha256").read_text(encoding="utf-8")
    assert payload.is_file()
    assert checksum.endswith("  native_trajectory.npz\n")


def test_roboverse_ready_marker_is_run_specific(tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "runtime" / "ready.json"
    monkeypatch.setenv("ROBOT_DATA_STUDIO_READY_FILE", str(marker))
    monkeypatch.setenv("ROBOT_DATA_STUDIO_RUN_ID", "run-123")

    _announce_ready()

    payload = __import__("json").loads(marker.read_text(encoding="utf-8"))
    assert payload["ready"] is True
    assert payload["run_id"] == "run-123"
