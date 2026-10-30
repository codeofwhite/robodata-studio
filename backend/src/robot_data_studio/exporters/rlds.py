from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from robot_data_contracts import iter_training_frames

from .common import discover_episodes, load_canonical_episodes, read_rgb, write_directory_provenance


def export_rlds(episode_paths: list[Path], output: Path) -> Path:
    try:
        import tensorflow_datasets as tfds
    except ImportError as error:
        raise RuntimeError("tensorflow and tensorflow-datasets are required in the configured RLDS environment") from error
    episodes = load_canonical_episodes(episode_paths)
    output = output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Refusing to overwrite non-empty RLDS output: {output}")
    first = episodes[0]
    image_shapes = {
        name: read_rgb(first.image_path(name, 0)).shape for name in first.manifest.camera_names
    }

    class RobotDataRlds(tfds.core.GeneratorBasedBuilder):
        VERSION = tfds.core.Version("1.0.0")

        def _info(self):
            observation = {
                "state": tfds.features.Tensor((16,), np.float32),
                "images": {name: tfds.features.Image(shape=shape, dtype=np.uint8) for name, shape in image_shapes.items()},
            }
            for key in ("ee_pose", "object_pose"):
                if key in first.arrays:
                    observation[key] = tfds.features.Tensor(first.arrays[key].shape[1:], np.float32)
            step = {
                "observation": observation,
                "action": tfds.features.Tensor((8,), np.float32),
                "reward": tfds.features.Scalar(np.float32), "discount": tfds.features.Scalar(np.float32),
                "is_first": tfds.features.Scalar(np.bool_), "is_last": tfds.features.Scalar(np.bool_),
                "is_terminal": tfds.features.Scalar(np.bool_), "language_instruction": tfds.features.Text(),
            }
            return self.dataset_info_from_configs(features=tfds.features.FeaturesDict({
                "steps": tfds.features.Dataset(step),
                "episode_metadata": {
                    "episode_id": tfds.features.Text(), "engine_id": tfds.features.Text(),
                    "engine_version": tfds.features.Text(), "worker_id": tfds.features.Text(),
                    "scene_id": tfds.features.Text(), "seed": tfds.features.Scalar(np.int64),
                    "operator_success_json": tfds.features.Text(), "evaluator_json": tfds.features.Text(),
                    "action_profile": tfds.features.Text(),
                },
            }))

        def _split_generators(self, _download_manager):
            return {tfds.Split.TRAIN: self._generate_examples(episodes)}

        def _generate_examples(self, selected):
            for episode in selected:
                steps = []
                for frame in iter_training_frames(episode, "physical_joint8"):
                    index = int(frame["frame_index"])
                    observation = {
                        "state": frame["state"],
                        "images": {name: read_rgb(path) for name, path in frame["images"].items()},
                    }
                    for key in ("ee_pose", "object_pose"):
                        if key in episode.arrays:
                            observation[key] = episode.arrays[key][index]
                    steps.append({
                        "observation": observation, "action": frame["action"],
                        "reward": episode.arrays["reward"][index], "discount": episode.arrays["discount"][index],
                        "is_first": episode.arrays["is_first"][index], "is_last": episode.arrays["is_last"][index],
                        "is_terminal": episode.arrays["is_terminal"][index], "language_instruction": frame["task"],
                    })
                manifest = episode.manifest
                yield manifest.episode_uuid, {
                    "steps": steps,
                    "episode_metadata": {
                        "episode_id": manifest.episode_uuid, "engine_id": manifest.software.engine_id,
                        "engine_version": manifest.software.engine_version, "worker_id": manifest.software.worker_id,
                        "scene_id": manifest.scene.scene_id, "seed": manifest.scene.seed,
                        "operator_success_json": str(manifest.operator_success).lower() if manifest.operator_success is not None else "null",
                        "evaluator_json": manifest.evaluator.model_dump_json(), "action_profile": manifest.action_profile.id,
                    },
                }

    output.mkdir(parents=True, exist_ok=True)
    RobotDataRlds(data_dir=output).download_and_prepare()
    write_directory_provenance(output, episodes)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Export EpisodeContract v1 to RLDS/TFDS")
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(export_rlds(discover_episodes(args.input_root), args.output))


if __name__ == "__main__":
    main()
