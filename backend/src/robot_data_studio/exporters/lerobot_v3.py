from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from robot_data_contracts import TRAINING_PROFILES, iter_training_frames

from .common import discover_episodes, load_canonical_episodes, read_rgb, write_directory_provenance


def export_lerobot_v3(
    episode_paths: list[Path], output: Path, *, repo_id: str,
    use_videos: bool = True, profile: str = "physical_joint8",
) -> Path:
    try:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
    except ImportError as error:
        raise RuntimeError("LeRobot v3 is required in the configured export environment") from error
    if profile not in TRAINING_PROFILES:
        raise ValueError(f"Unknown training profile: {profile}")
    episodes = load_canonical_episodes(episode_paths)
    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"LeRobot output must not already exist: {output}")
    adapter = TRAINING_PROFILES[profile]
    first = episodes[0]
    image_dtype = "video" if use_videos else "image"
    features = {
        "observation.state": {"dtype": "float32", "shape": (adapter.state_dimension,), "names": list(adapter.state_names)},
        "action": {"dtype": "float32", "shape": (adapter.action_dimension,), "names": list(adapter.action_names)},
        "reward": {"dtype": "float32", "shape": (1,), "names": None},
        "discount": {"dtype": "float32", "shape": (1,), "names": None},
        "is_first": {"dtype": "bool", "shape": (1,), "names": None},
        "is_last": {"dtype": "bool", "shape": (1,), "names": None},
        "is_terminal": {"dtype": "bool", "shape": (1,), "names": None},
    }
    for key in ("ee_pose", "object_pose"):
        if key in first.arrays:
            features[f"observation.{key}"] = {"dtype": "float32", "shape": first.arrays[key].shape[1:], "names": None}
    for camera in first.manifest.camera_names:
        image = read_rgb(first.image_path(camera, 0))
        features[f"observation.images.{camera}"] = {
            "dtype": image_dtype, "shape": image.shape, "names": ["height", "width", "channel"],
        }
    dataset = LeRobotDataset.create(
        repo_id=repo_id, root=output, fps=first.manifest.fps,
        robot_type="franka_panda_parallel_gripper", features=features, use_videos=use_videos,
    )
    try:
        for episode in episodes:
            for frame in iter_training_frames(episode, profile):
                index = int(frame["frame_index"])
                value = {
                    "observation.state": frame["state"], "action": frame["action"],
                    "reward": np.asarray([episode.arrays["reward"][index]], np.float32),
                    "discount": np.asarray([episode.arrays["discount"][index]], np.float32),
                    "is_first": np.asarray([episode.arrays["is_first"][index]], np.bool_),
                    "is_last": np.asarray([episode.arrays["is_last"][index]], np.bool_),
                    "is_terminal": np.asarray([episode.arrays["is_terminal"][index]], np.bool_),
                    "task": frame["task"],
                }
                for key in ("ee_pose", "object_pose"):
                    if key in episode.arrays:
                        value[f"observation.{key}"] = episode.arrays[key][index]
                value.update({f"observation.images.{name}": read_rgb(path) for name, path in frame["images"].items()})
                dataset.add_frame(value)
            dataset.save_episode()
    finally:
        dataset.finalize()
    write_directory_provenance(output, episodes)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Export EpisodeContract v1 to LeRobot v3")
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--images", action="store_true")
    parser.add_argument("--profile", choices=tuple(TRAINING_PROFILES), default="physical_joint8")
    args = parser.parse_args()
    result = export_lerobot_v3(discover_episodes(args.input_root), args.output, repo_id=args.repo_id, use_videos=not args.images, profile=args.profile)
    print(result)


if __name__ == "__main__":
    main()
