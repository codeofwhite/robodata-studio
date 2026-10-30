from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

from .episode import EpisodeManifestV1
from .training import TrainingProfileId, adapt_franka_joint8
from .validation import inspect_episode


@dataclass(frozen=True)
class CanonicalEpisode:
    """Validated, read-only view of one EpisodeContract v1 directory."""

    path: Path
    manifest: EpisodeManifestV1
    arrays: dict[str, np.ndarray]

    @property
    def length(self) -> int:
        return self.manifest.num_frames

    def image_path(self, camera_name: str, frame_index: int) -> Path:
        if camera_name not in self.manifest.camera_names:
            raise KeyError(f"unknown camera: {camera_name}")
        if not 0 <= frame_index < self.length:
            raise IndexError(frame_index)
        return self.path / f"{camera_name}_rgb" / f"{frame_index:06d}.jpg"


def open_canonical_episode(
    path: str | Path,
    *,
    array_keys: set[str] | None = None,
) -> CanonicalEpisode:
    """Validate and load a canonical episode without simulator dependencies."""

    episode_path = Path(path).expanduser().resolve()
    payload = json.loads((episode_path / "manifest.json").read_text(encoding="utf-8"))
    manifest = EpisodeManifestV1.model_validate(payload)
    inspect_episode(episode_path / "manifest.json")
    with np.load(episode_path / "trajectory.npz", allow_pickle=False) as archive:
        selected = set(archive.files) if array_keys is None else set(array_keys)
        missing = selected - set(archive.files)
        if missing:
            raise ValueError(f"episode is missing selected arrays: {sorted(missing)}")
        arrays = {key: archive[key].copy() for key in selected}
    return CanonicalEpisode(path=episode_path, manifest=manifest, arrays=arrays)


def iter_training_frames(
    episode: CanonicalEpisode,
    profile: TrainingProfileId,
) -> Iterator[dict[str, object]]:
    """Yield an explicit training view while leaving canonical arrays untouched."""

    for frame_index in range(episode.length):
        state, action = adapt_franka_joint8(
            episode.arrays["policy_state"][frame_index],
            episode.arrays["applied_action"][frame_index],
            profile,
        )
        yield {
            "frame_index": frame_index,
            "state": state,
            "action": action,
            "task": episode.manifest.task,
            "images": {
                name: episode.image_path(name, frame_index)
                for name in episode.manifest.camera_names
            },
        }
