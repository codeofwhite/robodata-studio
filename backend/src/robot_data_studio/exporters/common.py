from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np

from robot_data_contracts import CanonicalEpisode, open_canonical_episode


PROVENANCE_FILE = "robot_data_provenance.jsonl"


def discover_episodes(root: Path) -> list[Path]:
    source = root.expanduser().resolve()
    if (source / "manifest.json").is_file():
        return [source]
    return sorted(
        path.parent
        for path in source.rglob("manifest.json")
        if not path.parent.name.endswith(".tmp")
    )


def load_canonical_episodes(paths: Iterable[Path]) -> list[CanonicalEpisode]:
    episodes = [open_canonical_episode(path) for path in paths]
    if not episodes:
        raise ValueError("No canonical episodes were selected")
    first = episodes[0].manifest
    for episode in episodes[1:]:
        manifest = episode.manifest
        if manifest.robot_id != first.robot_id:
            raise ValueError(
                f"robot_id mismatch: {first.episode_uuid} uses {first.robot_id}, "
                f"{manifest.episode_uuid} uses {manifest.robot_id}"
            )
        if manifest.fps != first.fps:
            raise ValueError(
                f"fps mismatch: {first.episode_uuid} uses {first.fps}, "
                f"{manifest.episode_uuid} uses {manifest.fps}"
            )
        if manifest.action_profile != first.action_profile:
            raise ValueError(
                f"action profile mismatch between {first.episode_uuid} and {manifest.episode_uuid}"
            )
        if tuple(manifest.camera_names) != tuple(first.camera_names):
            raise ValueError(
                f"camera mismatch: {first.episode_uuid} uses {list(first.camera_names)}, "
                f"{manifest.episode_uuid} uses {list(manifest.camera_names)}"
            )
        for key in ("ee_pose", "object_pose"):
            if (key in episode.arrays) != (key in episodes[0].arrays):
                raise ValueError(
                    f"optional observation mismatch for {key}: "
                    f"{first.episode_uuid} and {manifest.episode_uuid} differ"
                )
    return episodes


def preflight_canonical_episodes(
    paths: Iterable[Path], *, format_name: str, profile: str,
) -> dict:
    episodes = load_canonical_episodes(paths)
    first = episodes[0].manifest
    if format_name in {"lerobot", "openpi_lerobot_v21", "rlds"} and not first.camera_names:
        raise ValueError(f"{format_name} export requires at least one RGB camera")
    consumer_cameras: list[str] = []
    if format_name == "openpi_lerobot_v21":
        consumer_cameras = ["base", "wrist"]
        missing = sorted(set(consumer_cameras) - set(first.camera_names))
        if missing:
            raise ValueError(
                "OpenPI Franka joint8 requires RGB cameras: " + ", ".join(missing)
            )
    engine_counts: dict[str, int] = {}
    scenes: set[str] = set()
    for episode in episodes:
        engine = episode.manifest.software.engine_id
        engine_counts[engine] = engine_counts.get(engine, 0) + 1
        scenes.add(episode.manifest.scene.scene_id)
    optional = [key for key in ("ee_pose", "object_pose") if key in episodes[0].arrays]
    warnings = []
    if len(engine_counts) > 1:
        warnings.append("mixed simulator export; use per-episode provenance for domain-aware training")
    if len(scenes) > 1:
        warnings.append("multiple scenes selected")
    if format_name == "openpi_lerobot_v21":
        unused = sorted(set(first.camera_names) - set(consumer_cameras))
        if unused:
            warnings.append(
                "OpenPI Franka joint8 trains on base+wrist; recorded QA-only cameras: "
                + ", ".join(unused)
            )
    return {
        "compatible": True,
        "episode_count": len(episodes),
        "engine_counts": engine_counts,
        "engine_ids": sorted(engine_counts),
        "scene_ids": sorted(scenes),
        "robot_id": first.robot_id,
        "fps": first.fps,
        "action_profile": first.action_profile.id,
        "training_profile": profile,
        "camera_names": list(first.camera_names),
        "consumer_camera_names": consumer_cameras,
        "optional_observations": optional,
        "provenance_complete": all(
            bool(episode.manifest.software.engine_id)
            and bool(episode.manifest.software.engine_version)
            and bool(episode.manifest.software.worker_id)
            for episode in episodes
        ),
        "warnings": warnings,
    }


def read_rgb(path: Path) -> np.ndarray:
    try:
        from PIL import Image
    except ImportError as error:
        raise RuntimeError("Pillow is required in the configured image export environment") from error
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"))


def provenance_record(episode: CanonicalEpisode, output_episode_index: int) -> dict:
    manifest = episode.manifest
    software = manifest.software
    return {
        "output_episode_index": output_episode_index,
        "source_episode_uuid": manifest.episode_uuid,
        "source_episode_index": manifest.episode_index,
        "engine_id": software.engine_id,
        "engine_version": software.engine_version,
        "worker_id": software.worker_id,
        "scene_id": manifest.scene.scene_id,
        "seed": manifest.scene.seed,
        "control_source": manifest.control_source,
        "generation_method": manifest.lineage.generation_method,
        "operator_success": manifest.operator_success,
        "automatic_success": manifest.evaluator.success,
        "evaluator_id": manifest.evaluator.evaluator_id,
        "evaluator_metrics": manifest.evaluator.metrics,
        "git_revisions": software.git_revisions,
    }


def write_directory_provenance(output: Path, episodes: list[CanonicalEpisode]) -> Path:
    metadata_root = output / "meta"
    metadata_root.mkdir(parents=True, exist_ok=True)
    destination = metadata_root / PROVENANCE_FILE
    rows = [
        json.dumps(provenance_record(episode, index), sort_keys=True)
        for index, episode in enumerate(episodes)
    ]
    destination.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return destination


def deterministic_split(episode_uuid: str, explicit: str | None = None) -> str:
    if explicit in {"train", "valid", "test"}:
        return explicit
    bucket = int(hashlib.sha256(episode_uuid.encode()).hexdigest()[:8], 16) % 100
    return "valid" if bucket < 10 else "test" if bucket < 20 else "train"


_FRANKA_JOINT8_LOW = np.asarray(
    [-2.8973, -1.7628, -2.8973, -3.0718, -2.8973, -0.0175, -2.8973, 0.0], dtype=np.float32
)
_FRANKA_JOINT8_HIGH = np.asarray(
    [2.8973, 1.7628, 2.8973, -0.0698, 2.8973, 3.7525, 2.8973, 0.08], dtype=np.float32
)


def _normalize_to_unit_range(value: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    return np.clip(2.0 * (value - low) / (high - low) - 1.0, -1.0, 1.0).astype(np.float32)


def normalize_franka_joint8(action: np.ndarray) -> np.ndarray:
    value = np.asarray(action, dtype=np.float32).reshape(-1)
    if value.shape != (8,) or not np.isfinite(value).all():
        raise ValueError("canonical Franka action must contain 8 finite values")
    return _normalize_to_unit_range(value, _FRANKA_JOINT8_LOW, _FRANKA_JOINT8_HIGH)


def normalize_dual_franka_joint16(action: np.ndarray) -> np.ndarray:
    """Normalize a left-then-right 16-D dual Franka action with the single-arm limits."""
    value = np.asarray(action, dtype=np.float32).reshape(-1)
    if value.shape != (16,) or not np.isfinite(value).all():
        raise ValueError("canonical dual Franka action must contain 16 finite values")
    low = np.concatenate([_FRANKA_JOINT8_LOW, _FRANKA_JOINT8_LOW])
    high = np.concatenate([_FRANKA_JOINT8_HIGH, _FRANKA_JOINT8_HIGH])
    return _normalize_to_unit_range(value, low, high)
