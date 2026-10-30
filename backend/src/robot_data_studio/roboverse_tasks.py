from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


EvaluatorKind = Literal["pick_cube", "push_cube", "stack_cube"]


@dataclass(frozen=True)
class RoboVerseTaskDescriptor:
    scene_id: str
    label: str
    description: str
    family: str
    task_id: str
    gym_id: str
    demo_h5: Path
    demo_metadata: Path
    max_steps: int
    demo_robot_name: str
    object_names: tuple[str, ...]
    goal_actor: str | None
    evaluator_kind: EvaluatorKind

    @property
    def task_state_names(self) -> tuple[str, ...]:
        names: list[str] = []
        for object_name in self.object_names:
            names.extend(
                f"object/{object_name}/{component}"
                for component in (
                    "position/x_m",
                    "position/y_m",
                    "position/z_m",
                    "quaternion/w",
                    "quaternion/x",
                    "quaternion/y",
                    "quaternion/z",
                )
            )
        if self.goal_actor is not None:
            names.extend(
                f"goal/{component}"
                for component in ("position/x_m", "position/y_m", "position/z_m")
            )
        return tuple(names)

    def studio_scene(self) -> dict:
        return {
            "label": self.label,
            "description": self.description,
            "family": self.family,
            "automatic_outcome": True,
            "parameters": [
                {
                    "key": "episode_steps",
                    "label": "Episode steps",
                    "unit": "steps",
                    "minimum": 2,
                    "maximum": self.max_steps,
                    "default": self.max_steps,
                    "step": 1,
                    "scale": "linear",
                },
                {
                    "key": "demo_offset",
                    "label": "Successful demo offset",
                    "unit": "trajectories",
                    "minimum": 0,
                    "maximum": 100_000,
                    "default": 0,
                    "step": 1,
                    "scale": "linear",
                },
            ],
        }


def _official_rl_demo(task: str) -> tuple[Path, Path]:
    root = Path(task) / "rl"
    stem = "trajectory.none.pd_joint_delta_pos.physx_cuda"
    return root / f"{stem}.h5", root / f"{stem}.json"


_PICK_H5, _PICK_JSON = _official_rl_demo("PickCube-v1")
_PUSH_H5, _PUSH_JSON = _official_rl_demo("PushCube-v1")
_STACK_H5, _STACK_JSON = _official_rl_demo("StackCube-v1")


ROBOVERSE_TASKS: dict[str, RoboVerseTaskDescriptor] = {
    "maniskill_pick_cube_native": RoboVerseTaskDescriptor(
        scene_id="maniskill_pick_cube_native",
        label="ManiSkill PickCube Native",
        description=(
            "RoboVerse MetaSim 的 ManiSkill Panda PickCube 原生任务；"
            "使用官方 pd_joint_delta_pos demonstration 完成抓取与三维目标放置。"
        ),
        family="rigid_pick_place",
        task_id="maniskill.pick_cube_native",
        gym_id="PickCube-v1",
        demo_h5=_PICK_H5,
        demo_metadata=_PICK_JSON,
        max_steps=50,
        demo_robot_name="panda",
        object_names=("cube",),
        goal_actor="goal_site",
        evaluator_kind="pick_cube",
    ),
    "maniskill_push_cube_native": RoboVerseTaskDescriptor(
        scene_id="maniskill_push_cube_native",
        label="ManiSkill PushCube Native",
        description=(
            "RoboVerse MetaSim 的 ManiSkill Panda PushCube 原生任务；"
            "使用官方 pd_joint_delta_pos demonstration 将方块推入桌面目标区域。"
        ),
        family="rigid_push",
        task_id="maniskill.push_cube_native",
        gym_id="PushCube-v1",
        demo_h5=_PUSH_H5,
        demo_metadata=_PUSH_JSON,
        max_steps=50,
        demo_robot_name="panda",
        object_names=("cube",),
        goal_actor="goal_region",
        evaluator_kind="push_cube",
    ),
    "maniskill_stack_cube_native": RoboVerseTaskDescriptor(
        scene_id="maniskill_stack_cube_native",
        label="ManiSkill StackCube Native",
        description=(
            "RoboVerse MetaSim 的 ManiSkill Panda StackCube 原生任务；"
            "使用官方 pd_joint_delta_pos demonstration 抓取、堆叠并释放方块。"
        ),
        family="rigid_stack",
        task_id="maniskill.stack_cube_native",
        gym_id="StackCube-v1",
        demo_h5=_STACK_H5,
        demo_metadata=_STACK_JSON,
        max_steps=50,
        demo_robot_name="panda_wristcam",
        object_names=("cubeA", "cubeB"),
        goal_actor=None,
        evaluator_kind="stack_cube",
    ),
}


def task_descriptor(scene_id: str) -> RoboVerseTaskDescriptor:
    try:
        return ROBOVERSE_TASKS[scene_id]
    except KeyError as error:
        raise ValueError(f"unsupported RoboVerse scene: {scene_id}") from error
