from pathlib import Path

import pytest

from robot_data_studio.adapters.roboverse import RoboVerseAdapter
from robot_data_studio.config import CONTRACTS_SRC, PROJECT_ROOT, settings
from robot_data_studio.roboverse_tasks import ROBOVERSE_TASKS


def config(**updates):
    value = {
        "scene_id": "maniskill_pick_cube_native",
        "control_mode": "scripted",
        "target_episodes": 1,
        "gpu": 3,
        "control_fps": 20,
        "width": 640,
        "height": 480,
        "scene_params": {},
        "camera_profile_id": "roboverse_sapien_base_v1",
    }
    value.update(updates)
    return value


def test_roboverse_launch_is_isolated_and_allowlisted() -> None:
    adapter = RoboVerseAdapter()
    launch = adapter.build_worker_launch(config(), Path("/tmp/roboverse-data"))

    assert launch.command[:3] == [
        str(settings.roboverse_python),
        "-m",
        "robot_data_studio.workers.roboverse",
    ]
    assert launch.command[launch.command.index("--scene") + 1] == "maniskill_pick_cube_native"
    assert launch.command[launch.command.index("--episodes") + 1] == "1"
    assert launch.command[launch.command.index("--steps") + 1] == "50"
    assert launch.command[launch.command.index("--demo-file") + 1] == str(
        settings.roboverse_demo_root
        / ROBOVERSE_TASKS["maniskill_pick_cube_native"].demo_h5
    )
    assert launch.command[launch.command.index("--demo-metadata-file") + 1] == str(
        settings.roboverse_demo_root
        / ROBOVERSE_TASKS["maniskill_pick_cube_native"].demo_metadata
    )
    assert launch.command[launch.command.index("--demo-offset") + 1] == "0"
    assert "--seed" not in launch.command
    assert launch.cwd == settings.roboverse_root
    assert launch.env_updates["CUDA_VISIBLE_DEVICES"] == "3"
    assert launch.readiness.kind == "marker"
    assert "gpu:3" in launch.resources
    assert not any(resource.startswith("tcp:") for resource in launch.resources)
    python_path = launch.env_updates["PYTHONPATH"].split(":")
    assert str(PROJECT_ROOT / "backend" / "src") in python_path
    assert str(CONTRACTS_SRC) in python_path
    assert str(settings.roboverse_root / "packages" / "metasim") in python_path


def test_roboverse_descriptor_exposes_session_constraints() -> None:
    descriptor = RoboVerseAdapter().descriptor()

    assert descriptor["session_limits"]["target_episodes"] == {
        "minimum": 1,
        "maximum": 10,
        "default": 1,
    }
    assert descriptor["runtime"]["headless"] is True
    assert descriptor["runtime"]["uses_gpu"] is True
    assert descriptor["runtime"]["uses_collector_port"] is False
    assert set(descriptor["scenes"]) == set(ROBOVERSE_TASKS)
    for scene in descriptor["scenes"].values():
        assert [item["key"] for item in scene["parameters"]] == [
            "episode_steps",
            "demo_offset",
        ]


def test_roboverse_task_descriptor_drives_launch_arguments() -> None:
    adapter = RoboVerseAdapter()
    launch = adapter.build_collect_command(
        config(
            scene_id="maniskill_stack_cube_native",
            target_episodes=3,
            scene_params={"episode_steps": 12, "demo_offset": 7},
        ),
        Path("/tmp/stack-data"),
    )

    assert launch[launch.index("--scene") + 1] == "maniskill_stack_cube_native"
    assert launch[launch.index("--steps") + 1] == "12"
    assert launch[launch.index("--demo-offset") + 1] == "7"
    assert launch[launch.index("--demo-file") + 1].endswith(
        "StackCube-v1/rl/trajectory.none.pd_joint_delta_pos.physx_cuda.h5"
    )


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"control_mode": "gello"}, "scripted control only"),
        ({"scene_id": "untrusted"}, "unsupported RoboVerse scene"),
        ({"target_episodes": 11}, "1 to 10"),
        ({"control_fps": 10}, "control_fps=20"),
        ({"scene_params": {"shell": 1}}, "not allowlisted"),
        ({"scene_params": {"episode_steps": 51}}, "episode_steps must be between"),
        ({"scene_params": {"episode_steps": 12.5}}, "episode_steps must be an integer"),
        ({"scene_params": {"demo_offset": -1}}, "demo_offset must be between"),
    ],
)
def test_roboverse_rejects_out_of_scope_configuration(updates, message) -> None:
    with pytest.raises(ValueError, match=message):
        RoboVerseAdapter().validate_config(config(**updates))
