from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .common import (
    deterministic_split, discover_episodes, load_canonical_episodes,
    normalize_franka_joint8, provenance_record, read_rgb,
)


def _hdf5_attribute_value(value):
    """Encode nullable or structured provenance as HDF5-safe scalar values."""
    if value is None or isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def export_robomimic(episode_paths: list[Path], output: Path) -> Path:
    try:
        import h5py
    except ImportError as error:
        raise RuntimeError("h5py is required in the configured robomimic export environment") from error
    episodes = load_canonical_episodes(episode_paths)
    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite robomimic output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    split_members: dict[str, list[str]] = {"train": [], "valid": [], "test": []}
    total = 0
    with h5py.File(output, "x") as file:
        data = file.create_group("data")
        data.attrs["env_args"] = json.dumps({
            "env_name": "RobotDataFranka", "env_type": 1,
            "env_kwargs": {"action_profile": "franka_joint8_absolute_normalized"},
        })
        for output_index, episode in enumerate(episodes):
            actions_absolute = episode.arrays["applied_action"].astype(np.float32)
            actions = np.stack([normalize_franka_joint8(action) for action in actions_absolute])
            name = f"demo_{output_index}"
            demo = data.create_group(name)
            demo.attrs["num_samples"] = episode.length
            demo.attrs["task"] = episode.manifest.task
            demo.attrs["operator_success_json"] = json.dumps(episode.manifest.operator_success)
            demo.attrs["evaluator_json"] = episode.manifest.evaluator.model_dump_json()
            for key, value in provenance_record(episode, output_index).items():
                demo.attrs[key] = _hdf5_attribute_value(value)
            demo.create_dataset("states", data=episode.arrays["policy_state"], compression="gzip")
            demo.create_dataset("actions", data=actions, compression="gzip")
            demo.create_dataset("actions_absolute", data=actions_absolute, compression="gzip")
            demo.create_dataset("rewards", data=episode.arrays["reward"])
            demo.create_dataset("dones", data=episode.arrays["is_last"].astype(np.uint8))
            demo.create_dataset("is_terminal", data=episode.arrays["is_terminal"].astype(np.uint8))
            obs = demo.create_group("obs")
            next_obs = demo.create_group("next_obs")
            observations = {"state": episode.arrays["policy_state"]}
            for key in ("ee_pose", "object_pose"):
                if key in episode.arrays:
                    observations[key] = episode.arrays[key]
            for camera in episode.manifest.camera_names:
                observations[f"{camera}_image"] = np.stack([
                    read_rgb(episode.image_path(camera, index)) for index in range(episode.length)
                ])
            for key, value in observations.items():
                obs.create_dataset(key, data=value, compression="gzip")
                next_obs.create_dataset(key, data=np.concatenate([value[1:], value[-1:]], axis=0), compression="gzip")
            split = deterministic_split(episode.manifest.episode_uuid)
            split_members[split].append(name)
            total += episode.length
        data.attrs["total"] = total
        mask = file.create_group("mask")
        text_dtype = h5py.string_dtype(encoding="utf-8")
        for split, members in split_members.items():
            mask.create_dataset(split, data=np.asarray(members, dtype=text_dtype))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Export EpisodeContract v1 to robomimic HDF5")
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(export_robomimic(discover_episodes(args.input_root), args.output))


if __name__ == "__main__":
    main()
