from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .episode import EpisodeManifestV1


@dataclass(frozen=True)
class EpisodeDescriptor:
    episode_uuid: str; task: str; num_frames: int; operator_success: bool | None
    auto_success: bool | None; failure_reason: str | None; created_at: str | None; manifest: dict[str, Any]


def inspect_episode(manifest_path: str | Path, *, engine_id: str | None = None) -> EpisodeDescriptor:
    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format") == "robot_data_episode":
        manifest = EpisodeManifestV1.model_validate(payload)
        normalized = manifest.model_dump(mode="json")
        auto_success = manifest.evaluator.success if manifest.evaluator.available else None
    else:
        return _inspect_legacy(path, payload, engine_id)
    _validate_arrays_and_images(path.parent, normalized, manifest.num_frames, manifest.fps)
    return EpisodeDescriptor(manifest.episode_uuid, manifest.task, manifest.num_frames,
                             manifest.operator_success, auto_success, manifest.failure_reason,
                             str(manifest.created_at), normalized)


def _validate_arrays_and_images(root: Path, manifest: dict[str, Any], length: int, fps: int) -> None:
    with np.load(root / "trajectory.npz", allow_pickle=False) as arrays:
        required = {"frame_index", "episode_time_s", "simulation_time_s", "capture_timestamp_ns",
                    "control_source_timestamp_ns", "control_receive_timestamp_ns", "control_sequence"}
        if "features" in manifest: required |= {item["key"] for item in manifest["features"]}
        missing = sorted(required - set(arrays.files))
        if missing: raise ValueError(f"episode is missing required arrays: {missing}")
        for name in arrays.files:
            value = arrays[name]
            if value.ndim == 0 or value.shape[0] != length: raise ValueError(f"array {name} length mismatch")
            if np.issubdtype(value.dtype, np.number) and not np.isfinite(value).all(): raise ValueError(f"array {name} contains NaN or Inf")
        if not np.array_equal(arrays["frame_index"], np.arange(length)): raise ValueError("frame_index must be contiguous")
        if not np.allclose(arrays["episode_time_s"], np.arange(length) / fps, atol=1e-6, rtol=0):
            raise ValueError("episode_time_s must equal frame_index / fps")
        if length > 1 and np.any(np.diff(arrays["simulation_time_s"]) < 0): raise ValueError("simulation_time_s must be monotonic")
        if length > 1 and np.any(np.diff(arrays["capture_timestamp_ns"]) < 0): raise ValueError("capture timestamps must be monotonic")
    for camera in manifest.get("camera_names", []):
        if len(list((root / f"{camera}_rgb").glob("*.jpg"))) != length: raise ValueError(f"camera {camera} frame count mismatch")


def _inspect_legacy(path: Path, manifest: dict[str, Any], engine_id: str | None) -> EpisodeDescriptor:
    length, fps = int(manifest["num_frames"]), int(manifest["fps"])
    with np.load(path.parent / "trajectory.npz", allow_pickle=False) as arrays:
        required = {"state", "actions", "frame_index", "timestamp", "sim_time"}
        missing = sorted(required - set(arrays.files))
        if missing: raise ValueError(f"episode is missing required arrays: {missing}")
        for name in arrays.files:
            value = arrays[name]
            if value.ndim == 0 or value.shape[0] != length: raise ValueError(f"array {name} length mismatch")
            if np.issubdtype(value.dtype, np.number) and not np.isfinite(value).all(): raise ValueError(f"array {name} contains NaN or Inf")
    for camera in manifest.get("camera_names", []):
        if len(list((path.parent / f"{camera}_rgb").glob("*.jpg"))) != length: raise ValueError(f"camera {camera} frame count mismatch")
    normalized = dict(manifest); normalized.setdefault("engine_id", engine_id)
    auto = normalized.get("auto_success") if normalized.get("automatic_outcome") != "unavailable" else None
    return EpisodeDescriptor(str(manifest["episode_uuid"]), str(manifest["task"]), length,
                             manifest.get("operator_success"), None if auto is None else bool(auto),
                             manifest.get("failure_reason"), manifest.get("created_at"), normalized)
