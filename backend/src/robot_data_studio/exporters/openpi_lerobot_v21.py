from __future__ import annotations

import argparse
import json
import shutil
import uuid
from pathlib import Path

from robot_data_contracts import iter_training_frames

from .common import discover_episodes, load_canonical_episodes, read_rgb, write_directory_provenance


FORMAT = "openpi_lerobot_v21"
PROFILE = "openpi_franka_joint8"


def export_openpi_lerobot_v21(
    episode_paths: list[Path],
    output: Path,
    *,
    repo_id: str,
    use_videos: bool = True,
) -> Path:
    try:
        from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
    except ImportError as error:
        raise RuntimeError("OpenPI's vendored LeRobot v2.1 is required") from error

    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    episodes = load_canonical_episodes(episode_paths)
    fps = episodes[0].manifest.fps
    cameras = tuple(episodes[0].manifest.camera_names)
    if any(episode.manifest.fps != fps for episode in episodes):
        raise ValueError("all episodes must have the same fps")
    if any(tuple(episode.manifest.camera_names) != cameras for episode in episodes):
        raise ValueError("all episodes must have the same ordered camera set")
    if not cameras:
        raise ValueError("OpenPI export requires at least one RGB camera")

    first_image = read_rgb(episodes[0].image_path(cameras[0], 0))
    features = {
        "observation.state": {
            "dtype": "float32",
            "shape": (8,),
            "names": [
                *(f"panda_joint{i}_rad" for i in range(1, 8)),
                "gripper_closed_fraction",
            ],
        },
        "action": {
            "dtype": "float32",
            "shape": (8,),
            "names": [
                *(f"target_panda_joint{i}_rad" for i in range(1, 8)),
                "target_gripper_closed_fraction",
            ],
        },
    }
    image_dtype = "video" if use_videos else "image"
    for camera in cameras:
        image = read_rgb(episodes[0].image_path(camera, 0))
        if image.shape != first_image.shape:
            raise ValueError("OpenPI v2.1 export requires one shared source image shape")
        features[f"observation.images.{camera}"] = {
            "dtype": image_dtype,
            "shape": image.shape,
            "names": ["height", "width", "channel"],
        }

    temporary = output.with_name(f".{output.name}.tmp-{uuid.uuid4().hex[:8]}")
    try:
        dataset = LeRobotDataset.create(
            repo_id=repo_id,
            root=temporary,
            fps=fps,
            robot_type="franka_panda_parallel_gripper",
            features=features,
            use_videos=use_videos,
            image_writer_threads=4,
        )
        for episode in episodes:
            for frame in iter_training_frames(episode, PROFILE):
                value = {
                    "observation.state": frame["state"],
                    "action": frame["action"],
                    "task": frame["task"],
                }
                value.update(
                    {
                        f"observation.images.{name}": read_rgb(path)
                        for name, path in frame["images"].items()
                    }
                )
                dataset.add_frame(value)
            dataset.save_episode()
        info = json.loads((temporary / "meta" / "info.json").read_text(encoding="utf-8"))
        if info.get("codebase_version") != "v2.1":
            raise RuntimeError(
                f"wrong LeRobot writer: expected v2.1, got {info.get('codebase_version')}"
            )
        write_directory_provenance(temporary, episodes)
        temporary.rename(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Export EpisodeContract v1 to OpenPI LeRobot v2.1")
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--images", action="store_true")
    args = parser.parse_args()
    result = export_openpi_lerobot_v21(
        discover_episodes(args.input_root),
        args.output,
        repo_id=args.repo_id,
        use_videos=not args.images,
    )
    print(result)


if __name__ == "__main__":
    main()
