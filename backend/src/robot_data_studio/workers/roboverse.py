from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import os
import signal
import sys
from pathlib import Path
from typing import Any

import numpy as np

from robot_data_contracts import (
    AugmentationLineageV1,
    EpisodeWriter,
    EvaluatorResultV1,
    FeatureRole,
    FeatureSpecV1,
    SceneProvenanceV1,
)
from robot_data_contracts.profiles.franka import (
    FRANKA_JOINT8_ACTION,
    franka_feature_specs,
    policy_action_from_native,
    policy_state_from_native,
)
from robot_data_contracts.provenance import collect_software_provenance

from robot_data_studio.roboverse_tasks import (
    ROBOVERSE_TASKS,
    RoboVerseTaskDescriptor,
    task_descriptor,
)


ARM_JOINTS = tuple(f"panda_joint{index}" for index in range(1, 8))
FINGER_JOINTS = ("panda_finger_joint1", "panda_finger_joint2")
NATIVE_JOINTS = ARM_JOINTS + FINGER_JOINTS
CAMERA_POSITION = (1.1, -1.1, 0.9)
CAMERA_LOOK_AT = (-0.1, 0.0, 0.15)
CAMERA_VERTICAL_FOV_DEG = 42.0
CAMERA_FOCAL_LENGTH = 24.0


def _as_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def _named_values(names: list[str], values: Any, expected: tuple[str, ...]) -> np.ndarray:
    flat = _as_numpy(values).reshape(-1)
    if len(names) != len(flat):
        raise ValueError(f"joint name/value mismatch: {len(names)} names for {len(flat)} values")
    by_name = dict(zip(names, flat, strict=True))
    missing = [name for name in expected if name not in by_name]
    if missing:
        raise ValueError(f"RoboVerse Panda state is missing joints: {missing}")
    return np.asarray([by_name[name] for name in expected], dtype=np.float32)


def extract_native_state(task: Any) -> np.ndarray:
    robot = task.handler.object_ids["panda"]
    active_names = [joint.get_name() for joint in robot.get_active_joints()]
    qpos = _named_values(active_names, robot.get_qpos(), NATIVE_JOINTS)
    qvel = _named_values(active_names, robot.get_qvel(), NATIVE_JOINTS)
    return np.concatenate([qpos, qvel]).astype(np.float32)


def absolute_native_target(task: Any, normalized_action: Any) -> np.ndarray:
    target = _as_numpy(task._targets_from_action(normalized_action)).reshape(-1)
    sorted_names = list(task.handler.get_joint_names("panda", sort=True))
    return _named_values(sorted_names, target, NATIVE_JOINTS)


def _camera_geometry(width: int, height: int) -> tuple[float, list[list[float]]]:
    horizontal_aperture = (
        2.0
        * CAMERA_FOCAL_LENGTH
        * math.tan(math.radians(CAMERA_VERTICAL_FOV_DEG) / 2.0)
        * width
        / height
    )
    focal_pixels = width * CAMERA_FOCAL_LENGTH / horizontal_aperture
    return horizontal_aperture, [
        [focal_pixels, 0.0, width / 2.0],
        [0.0, focal_pixels, height / 2.0],
        [0.0, 0.0, 1.0],
    ]


def _camera_image(observation: Any) -> np.ndarray:
    try:
        rgb = observation.cameras["base"].rgb
    except (AttributeError, KeyError) as error:
        raise RuntimeError("RoboVerse SAPIEN3 observation is missing base RGB") from error
    image = _as_numpy(rgb)
    if image.ndim == 4:
        image = image[0]
    if image.dtype != np.uint8:
        if np.issubdtype(image.dtype, np.floating) and image.max(initial=0) <= 1.0:
            image = image * 255.0
        image = np.clip(image, 0, 255).astype(np.uint8)
    return image[..., :3]


def _object_observation(
    task: Any, descriptor: RoboVerseTaskDescriptor
) -> tuple[np.ndarray, np.ndarray]:
    poses = [
        np.concatenate([task.obj_pos(name), task.obj_quat(name)])
        for name in descriptor.object_names
    ]
    velocities = [
        np.concatenate([task.obj_linvel(name), task.obj_angvel(name)])
        for name in descriptor.object_names
    ]
    return (
        np.concatenate(poses).astype(np.float32),
        np.concatenate(velocities).astype(np.float32),
    )


def _task_state(task: Any, descriptor: RoboVerseTaskDescriptor) -> np.ndarray:
    object_pose, _ = _object_observation(task, descriptor)
    values = [object_pose]
    if descriptor.goal_actor is not None:
        values.append(np.asarray(task.goal_pos, dtype=np.float32).reshape(3))
    state = np.concatenate(values).astype(np.float32)
    if state.shape != (len(descriptor.task_state_names),):
        raise ValueError(
            f"{descriptor.scene_id} task state has shape {state.shape}; "
            f"expected {(len(descriptor.task_state_names),)}"
        )
    return state


def _asset_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _announce_ready() -> None:
    raw_path = os.environ.get("ROBOT_DATA_STUDIO_READY_FILE")
    if not raw_path:
        return
    path = Path(raw_path)
    payload = {
        "run_id": os.environ.get("ROBOT_DATA_STUDIO_RUN_ID"),
        "worker_id": "roboverse_maniskill_worker",
        "ready": True,
        "pid": os.getpid(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_demo_metadata(
    path: Path, descriptor: RoboVerseTaskDescriptor
) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    env_info = payload.get("env_info", {})
    env_kwargs = env_info.get("env_kwargs", {})
    if env_info.get("env_id") != descriptor.gym_id:
        raise ValueError(
            f"demo metadata env_id={env_info.get('env_id')!r}; "
            f"expected {descriptor.gym_id!r}"
        )
    if env_kwargs.get("control_mode") != "pd_joint_delta_pos":
        raise ValueError("demo metadata must use pd_joint_delta_pos")
    if int(env_info.get("max_episode_steps", -1)) != descriptor.max_steps:
        raise ValueError(
            f"demo metadata max_episode_steps must be {descriptor.max_steps}"
        )
    episodes: dict[str, dict[str, Any]] = {}
    for item in payload.get("episodes", []):
        episode_id = int(item["episode_id"])
        key = f"traj_{episode_id}"
        if key in episodes:
            raise ValueError(f"duplicate demo metadata entry: {key}")
        if "episode_seed" not in item:
            raise ValueError(f"demo metadata {key} has no episode_seed")
        episodes[key] = item
    if not episodes:
        raise ValueError("demo metadata contains no episodes")
    return episodes


def successful_demo_keys(
    demos: Any,
    count: int,
    *,
    offset: int = 0,
    metadata: dict[str, dict[str, Any]] | None = None,
    task_label: str = "demo",
) -> list[str]:
    keys = sorted(
        (key for key in demos if key.startswith("traj_")),
        key=lambda key: int(key.split("_")[1]),
    )
    successful: list[str] = []
    for key in keys:
        group = demos[key]
        actions = np.asarray(group["actions"])
        success = np.asarray(group["success"])
        if actions.ndim != 2 or actions.shape[1] != 8:
            raise ValueError(f"{key} has invalid pd_joint_delta_pos actions: {actions.shape}")
        metadata_success = True
        if metadata is not None:
            if key not in metadata:
                raise ValueError(f"demo metadata is missing {key}")
            metadata_success = bool(metadata[key].get("success"))
        if success.size and bool(success.reshape(-1)[-1]) and metadata_success:
            successful.append(key)
    selected = successful[offset : offset + count]
    if len(selected) != count:
        raise ValueError(
            f"{task_label} has {len(successful)} successful trajectories; "
            f"offset {offset} cannot provide {count} episodes"
        )
    return selected


def restore_demo_initial_state(
    task: Any, demo: Any, descriptor: RoboVerseTaskDescriptor
) -> None:
    import sapien
    import sapien.physx as physx

    states = demo["env_states"]
    articulations = states["articulations"]
    if descriptor.demo_robot_name not in articulations:
        raise ValueError(
            f"{descriptor.gym_id} demo is missing articulation "
            f"{descriptor.demo_robot_name}"
        )
    articulation = np.asarray(articulations[descriptor.demo_robot_name])[0]
    root_state_dimension = 13
    joint_count = (len(articulation) - root_state_dimension) // 2
    if joint_count != len(NATIVE_JOINTS):
        raise ValueError(
            f"{descriptor.gym_id} demo Panda has {joint_count} joints; "
            f"expected {len(NATIVE_JOINTS)}"
        )
    robot = task.handler.object_ids["panda"]
    robot.set_qpos(
        articulation[
            root_state_dimension : root_state_dimension + joint_count
        ].astype(np.float32)
    )
    robot.set_qvel(
        articulation[
            root_state_dimension + joint_count : root_state_dimension + 2 * joint_count
        ].astype(np.float32)
    )
    demo_actors = states["actors"]
    for name in descriptor.object_names:
        if name not in demo_actors:
            raise ValueError(f"{descriptor.gym_id} demo is missing actor {name}")
        actor_state = np.asarray(demo_actors[name])[0]
        actor = task.handler.object_ids[name]
        actor.set_pose(sapien.Pose(actor_state[:3], actor_state[3:7]))
        component = actor.find_component_by_type(physx.PhysxRigidDynamicComponent)
        if component is not None and len(actor_state) >= root_state_dimension:
            component.set_linear_velocity(actor_state[7:10].astype(np.float32))
            component.set_angular_velocity(actor_state[10:13].astype(np.float32))
    if descriptor.goal_actor is not None:
        if descriptor.goal_actor not in demo_actors:
            raise ValueError(
                f"{descriptor.gym_id} demo is missing goal actor {descriptor.goal_actor}"
            )
        task.goal_pos = np.asarray(demo_actors[descriptor.goal_actor])[0][:3].astype(
            np.float64
        )


def _write_native_payload(path: Path, arrays: dict[str, list[np.ndarray]]) -> None:
    payload_path = path / "native_trajectory.npz"
    np.savez_compressed(
        payload_path,
        **{name: np.stack(values) for name, values in arrays.items()},
    )
    digest = _asset_sha256(payload_path)
    (path / "native_payload.sha256").write_text(
        f"{digest}  native_trajectory.npz\n", encoding="utf-8"
    )


def _build_task(descriptor: RoboVerseTaskDescriptor, width: int, height: int):
    import roboverse_pack.tasks.maniskill  # noqa: F401
    from metasim.scenario.cameras import PinholeCameraCfg
    from metasim.task.registry import get_task_class

    task_class = get_task_class(descriptor.task_id)
    if int(task_class.max_episode_steps) != descriptor.max_steps:
        raise RuntimeError(
            f"{descriptor.task_id} max_episode_steps={task_class.max_episode_steps}; "
            f"descriptor declares {descriptor.max_steps}"
        )
    scenario = copy.deepcopy(task_class.scenario)
    scenario.simulator = "sapien3"
    scenario.num_envs = 1
    scenario.headless = True
    horizontal_aperture, _ = _camera_geometry(width, height)
    scenario.cameras = [
        PinholeCameraCfg(
            name="base",
            data_types=["rgb"],
            width=width,
            height=height,
            pos=CAMERA_POSITION,
            look_at=CAMERA_LOOK_AT,
            focal_length=CAMERA_FOCAL_LENGTH,
            horizontal_aperture=horizontal_aperture,
        )
    ]
    return task_class(scenario)


def task_step_metrics(
    task: Any, descriptor: RoboVerseTaskDescriptor
) -> dict[str, float | bool]:
    if descriptor.evaluator_kind == "pick_cube":
        distance = float(np.linalg.norm(task.obj_pos("cube") - task.goal_pos))
        return {
            "goal_distance_m": distance,
            "is_grasped": bool(task.is_grasped("cube")),
            "is_obj_placed": distance <= 0.025,
            "is_robot_static": bool(task.is_robot_static()),
        }
    if descriptor.evaluator_kind == "push_cube":
        cube = task.obj_pos("cube")
        distance = float(np.linalg.norm(cube[:2] - task.goal_pos[:2]))
        return {
            "goal_distance_m": distance,
            "is_obj_placed": distance < 0.1,
            "is_on_surface": float(cube[2]) < 0.025,
        }
    cube_a = task.obj_pos("cubeA")
    cube_b = task.obj_pos("cubeB")
    offset = cube_a - cube_b
    on_cube = bool(
        np.linalg.norm(offset[:2]) <= np.linalg.norm(np.asarray([0.02, 0.02])) + 0.005
        and abs(float(offset[2]) - 0.04) <= 0.005
    )
    return {
        "cube_xy_offset_m": float(np.linalg.norm(offset[:2])),
        "cube_z_offset_m": float(offset[2]),
        "is_grasped": bool(task.is_grasped("cubeA")),
        "is_on_cube": on_cube,
        "is_static": bool(task.obj_is_static("cubeA")),
    }


def summarize_task_metrics(
    descriptor: RoboVerseTaskDescriptor,
    history: list[dict[str, float | bool]],
) -> dict[str, float | bool]:
    if not history:
        raise ValueError("task metric history must not be empty")
    final = history[-1]
    summary: dict[str, float | bool] = {
        f"final_{key}": value for key, value in final.items()
    }
    if descriptor.evaluator_kind in {"pick_cube", "push_cube"}:
        summary["minimum_goal_distance_m"] = min(
            float(item["goal_distance_m"]) for item in history
        )
        summary["ever_obj_placed"] = any(
            bool(item["is_obj_placed"]) for item in history
        )
    if descriptor.evaluator_kind in {"pick_cube", "stack_cube"}:
        summary["ever_grasped"] = any(bool(item["is_grasped"]) for item in history)
    if descriptor.evaluator_kind == "stack_cube":
        summary["ever_on_cube"] = any(bool(item["is_on_cube"]) for item in history)
        summary["ever_released_on_cube"] = any(
            bool(item["is_on_cube"]) and not bool(item["is_grasped"])
            for item in history
        )
    return summary


def classify_task_failure(
    descriptor: RoboVerseTaskDescriptor,
    metrics: dict[str, float | bool],
) -> str:
    if descriptor.evaluator_kind == "pick_cube":
        if not bool(metrics["ever_grasped"]):
            return "never_grasped"
        if not bool(metrics["ever_obj_placed"]):
            return "goal_not_reached"
        if not bool(metrics["final_is_robot_static"]):
            return "robot_not_static"
    elif descriptor.evaluator_kind == "push_cube":
        if not bool(metrics["final_is_on_surface"]):
            return "object_left_surface"
        if not bool(metrics["ever_obj_placed"]):
            return "goal_not_reached"
    else:
        if not bool(metrics["ever_grasped"]):
            return "never_grasped"
        if not bool(metrics["ever_on_cube"]):
            return "stack_alignment_not_reached"
        if bool(metrics["final_is_grasped"]):
            return "not_released"
        if bool(metrics["final_is_on_cube"]) and not bool(metrics["final_is_static"]):
            return "stack_unstable"
    return "timeout_without_success"


def _software_provenance() -> Any:
    return collect_software_provenance(
        engine_id="roboverse_sapien3",
        engine_version=importlib.metadata.version("sapien"),
        worker_id="roboverse_maniskill_worker",
        git_roots={"roboverse": Path.cwd()},
        packages=("roboverse-py", "sapien", "torch", "numpy"),
    )


def collect(args: argparse.Namespace) -> list[Path]:
    import h5py

    descriptor = task_descriptor(args.scene)
    if not 1 <= args.episodes <= 10:
        raise ValueError("episodes must be between 1 and 10")
    if not 2 <= args.steps <= descriptor.max_steps:
        raise ValueError(f"steps must be between 2 and {descriptor.max_steps}")
    if not 0 <= args.demo_offset <= 100_000:
        raise ValueError("demo_offset must be between 0 and 100000")
    if args.fps != 20:
        raise ValueError("ManiSkill native collection requires fps=20")
    demo_file = args.demo_file.expanduser().resolve()
    if not demo_file.is_file():
        raise FileNotFoundError(
            f"ManiSkill {descriptor.gym_id} demo is unavailable: {demo_file}"
        )
    demo_metadata_file = args.demo_metadata_file.expanduser().resolve()
    if not demo_metadata_file.is_file():
        raise FileNotFoundError(
            f"ManiSkill {descriptor.gym_id} demo metadata is unavailable: "
            f"{demo_metadata_file}"
        )
    demo_metadata = load_demo_metadata(demo_metadata_file, descriptor)
    demo_sha256 = _asset_sha256(demo_file)
    demo_metadata_sha256 = _asset_sha256(demo_metadata_file)
    profile = json.loads(args.camera_profile_file.read_text(encoding="utf-8"))
    role = profile["roles"]["agentview"]
    _, intrinsics = _camera_geometry(args.width, args.height)
    camera_calibration = {
        "base": {
            "role": "agentview",
            "profile": profile["id"],
            "intrinsics": intrinsics,
            "extrinsics": {
                "position_world_m": list(CAMERA_POSITION),
                "lookat_world_m": list(CAMERA_LOOK_AT),
                "convention": "sapien_x_forward_z_up",
            },
            "model": role["model"],
        }
    }
    software = _software_provenance()
    task = _build_task(descriptor, args.width, args.height)
    _announce_ready()
    saved: list[Path] = []
    stop_requested = False

    def request_stop(_signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True

    previous_sigterm = signal.signal(signal.SIGTERM, request_stop)
    try:
        with h5py.File(demo_file, "r") as demos:
            demo_keys = successful_demo_keys(
                demos,
                args.episodes,
                offset=args.demo_offset,
                metadata=demo_metadata,
                task_label=descriptor.gym_id,
            )
            for demo_key in demo_keys:
                if stop_requested:
                    break
                demo = demos[demo_key]
                actions = np.asarray(demo["actions"], dtype=np.float32)[: args.steps]
                episode_seed = int(demo_metadata[demo_key]["episode_seed"])
                task.reset(seed=episode_seed)
                restore_demo_initial_state(task, demo, descriptor)
                task_features = (
                    FeatureSpecV1(
                        key="task_state",
                        role=FeatureRole.AUXILIARY,
                        dtype="float32",
                        shape=(len(descriptor.task_state_names),),
                        names=descriptor.task_state_names,
                    ),
                )
                writer = EpisodeWriter(
                    args.data_dir,
                    fps=args.fps,
                    robot_id="franka_panda",
                    control_source="scripted_maniskill_demo_replay",
                    features=franka_feature_specs(
                        tuple(f"upstream_pd_joint_delta_pos/{index}" for index in range(8))
                    )
                    + task_features,
                    action_profile=FRANKA_JOINT8_ACTION,
                    camera_names=("base",),
                    camera_calibration=camera_calibration,
                    scene=SceneProvenanceV1(
                        scene_id=args.scene,
                        seed=episode_seed,
                        parameters={
                            "upstream_task": descriptor.task_id,
                            "upstream_gym_id": descriptor.gym_id,
                            "simulator": "sapien3",
                            "control_policy": "maniskill_official_demo_replay_v1",
                            "control_mode": "pd_joint_delta_pos",
                            "source_demo_trajectory": demo_key,
                            "source_demo_success": True,
                            "source_demo_sha256": demo_sha256,
                            "source_demo_metadata_sha256": demo_metadata_sha256,
                            "seed_semantics": "maniskill_source_episode_seed",
                            "native_payload_schema": (
                                "roboverse_maniskill_native_v2_pre_action"
                            ),
                            "episode_steps": len(actions),
                            "safety_filter": "identity_simulation_only",
                            "camera_profile_id": profile["id"],
                        },
                        assets=[
                            {
                                "role": "native_payload",
                                "path": "native_trajectory.npz",
                                "checksum": "native_payload.sha256",
                            }
                        ],
                    ),
                    software=software,
                    lineage=AugmentationLineageV1(
                        generation_method="scripted",
                        randomization_seed=episode_seed,
                        resolved_parameters={
                            "source_demo_trajectory": demo_key,
                            "source_episode_seed": episode_seed,
                            "demo_offset": args.demo_offset,
                        },
                    ),
                )
                native_arrays: dict[str, list[np.ndarray]] = {
                    "normalized_action": [],
                    "absolute_joint_target": [],
                    "pre_action_joint_state": [],
                    "pre_action_task_state": [],
                    "pre_action_object_pose": [],
                    "joint_state": [],
                    "task_state": [],
                    "object_pose": [],
                    "object_velocity": [],
                }
                writer.start(descriptor.task_id)
                succeeded = False
                last_reward = 0.0
                metric_history: list[dict[str, float | bool]] = []
                try:
                    for step, normalized in enumerate(actions):
                        if stop_requested:
                            raise InterruptedError("worker stop requested")
                        pre_action_joint_state = extract_native_state(task)
                        pre_action_object_pose, _ = _object_observation(
                            task, descriptor
                        )
                        pre_action_task_state = _task_state(task, descriptor)
                        absolute_target = absolute_native_target(task, normalized)
                        observation, reward, terminated, timeout, _ = task.step(
                            normalized[None, :]
                        )
                        state = extract_native_state(task)
                        object_pose, object_velocity = _object_observation(
                            task, descriptor
                        )
                        task_state = _task_state(task, descriptor)
                        step_metrics = task_step_metrics(task, descriptor)
                        metric_history.append(step_metrics)
                        succeeded = succeeded or bool(_as_numpy(terminated).reshape(-1)[0])
                        last_reward = float(_as_numpy(reward).reshape(-1)[0])
                        writer.add_frame(
                            images={"base": _camera_image(observation)},
                            values={
                                "native_state": state,
                                "policy_state": policy_state_from_native(state),
                                "operator_action": normalized,
                                "requested_action": policy_action_from_native(absolute_target),
                                "safe_action": policy_action_from_native(absolute_target),
                                "applied_action": policy_action_from_native(absolute_target),
                                "task_state": task_state,
                                "object_pose": object_pose,
                                "object_velocity": object_velocity,
                            },
                            simulation_time_s=(step + 1) / args.fps,
                            control_sequence=step,
                        )
                        for name, value in (
                            ("normalized_action", normalized),
                            ("absolute_joint_target", absolute_target),
                            ("pre_action_joint_state", pre_action_joint_state),
                            ("pre_action_task_state", pre_action_task_state),
                            ("pre_action_object_pose", pre_action_object_pose),
                            ("joint_state", state),
                            ("task_state", task_state),
                            ("object_pose", object_pose),
                            ("object_velocity", object_velocity),
                        ):
                            native_arrays[name].append(np.asarray(value))
                        if bool(_as_numpy(timeout).reshape(-1)[0]):
                            break
                    metrics = summarize_task_metrics(descriptor, metric_history)
                    metrics.update(
                        {
                            "last_dense_reward": last_reward,
                            "source_demo_success": True,
                            "source_demo_trajectory": demo_key,
                            "source_episode_seed": episode_seed,
                            "replay_steps": len(native_arrays["normalized_action"]),
                        }
                    )
                    evaluator = EvaluatorResultV1(
                        evaluator_id=f"roboverse_maniskill_{descriptor.evaluator_kind}_success",
                        evaluator_version="native_v2",
                        available=True,
                        success=succeeded,
                        metrics=metrics,
                    )
                    final = writer.finish(
                        operator_success=None,
                        evaluator=evaluator,
                        failure_reason=None
                        if succeeded
                        else classify_task_failure(descriptor, metrics),
                    )
                    _write_native_payload(final, native_arrays)
                    saved.append(final)
                    print(f"saved {final}", flush=True)
                except BaseException:
                    if writer.is_recording:
                        writer.discard()
                    raise
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        task.close()
    return saved


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RoboVerse to Studio canonical episode worker")
    parser.add_argument("--scene", required=True, choices=tuple(ROBOVERSE_TASKS))
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--demo-file", type=Path, required=True)
    parser.add_argument("--demo-metadata-file", type=Path, required=True)
    parser.add_argument("--demo-offset", type=int, default=0)
    parser.add_argument("--camera-profile-file", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        paths = collect(args)
    except InterruptedError as error:
        print(str(error), file=sys.stderr, flush=True)
        return 130
    print(f"completed {len(paths)} RoboVerse episode(s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
