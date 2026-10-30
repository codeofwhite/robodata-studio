from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time
from typing import Any
from uuid import uuid4

import numpy as np

from .episode import AugmentationLineageV1, EpisodeManifestV1, EvaluatorResultV1, SceneProvenanceV1, SoftwareProvenanceV1
from .features import ActionProfileV1, FeatureSpecV1


@dataclass
class _ActiveEpisode:
    index: int
    task: str
    path: Path
    uuid: str
    started_ns: int
    arrays: dict[str, list[np.ndarray | np.generic]] = field(default_factory=dict)


class EpisodeWriter:
    def __init__(self, root: str | Path, *, fps: int, robot_id: str, control_source: str,
                 features: tuple[FeatureSpecV1, ...], action_profile: ActionProfileV1,
                 camera_names: tuple[str, ...], camera_calibration: dict[str, dict[str, Any]],
                 scene: SceneProvenanceV1, software: SoftwareProvenanceV1,
                 lineage: AugmentationLineageV1, jpeg_quality: int = 95) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.fps = int(fps)
        if self.fps <= 0:
            raise ValueError("fps must be positive")
        self.robot_id, self.control_source = robot_id, control_source
        self.features, self.action_profile = tuple(features), action_profile
        self.camera_names, self.camera_calibration = tuple(camera_names), dict(camera_calibration)
        if set(self.camera_names) != set(self.camera_calibration):
            raise ValueError("camera names and calibration must match")
        self.scene, self.software, self.lineage = scene, software, lineage
        self.jpeg_quality = int(jpeg_quality)
        self._active: _ActiveEpisode | None = None

    @property
    def is_recording(self) -> bool:
        return self._active is not None

    @property
    def frame_count(self) -> int:
        return 0 if self._active is None else len(self._active.arrays.get("frame_index", []))

    def start(self, task: str) -> int:
        if self.is_recording:
            raise RuntimeError("an episode is already recording")
        if not task.strip():
            raise ValueError("task must not be empty")
        index = self._next_index()
        while True:
            path = self.root / f"episode_{index:06d}.tmp"
            try:
                path.mkdir()
                break
            except FileExistsError:
                index += 1
        for camera in self.camera_names:
            (path / f"{camera}_rgb").mkdir()
        self._active = _ActiveEpisode(index, task.strip(), path, str(uuid4()), time.monotonic_ns())
        return index

    def add_frame(self, *, images: dict[str, np.ndarray], values: dict[str, np.ndarray],
                  simulation_time_s: float, control_source_timestamp_ns: int = -1,
                  control_receive_timestamp_ns: int = -1, capture_timestamp_ns: int | None = None,
                  control_sequence: int = -1) -> None:
        active = self._require_active()
        expected = {spec.key for spec in self.features}
        if not expected <= set(values):
            raise ValueError(f"frame features are missing {sorted(expected - set(values))}")
        if set(images) != set(self.camera_names):
            raise ValueError("image cameras do not match manifest cameras")
        staged: dict[str, np.ndarray] = {}
        for spec in self.features:
            array = np.asarray(values[spec.key], dtype=np.dtype(spec.dtype))
            if array.shape != spec.shape or (np.issubdtype(array.dtype, np.number) and not np.isfinite(array).all()):
                raise ValueError(f"feature {spec.key} must be finite with shape {spec.shape}")
            staged[spec.key] = array
        for key in sorted(set(values) - expected):
            array = np.asarray(values[key])
            if array.ndim == 0 or not np.isfinite(array).all():
                raise ValueError(f"auxiliary feature {key} must be finite and non-scalar")
            if key in active.arrays and array.shape != np.asarray(active.arrays[key][0]).shape:
                raise ValueError(f"auxiliary feature {key} changed shape")
            staged[key] = array
        index = self.frame_count
        temporary_images: list[tuple[Path, Path]] = []
        try:
            for camera, image in images.items():
                final = active.path / f"{camera}_rgb" / f"{index:06d}.jpg"
                temporary = final.with_suffix(".tmp.jpg")
                temporary_images.append((temporary, final))
                self._write_rgb(temporary, image)
            for temporary, final in temporary_images:
                temporary.rename(final)
        except Exception:
            for temporary, final in temporary_images:
                temporary.unlink(missing_ok=True)
                final.unlink(missing_ok=True)
            raise
        for key, array in staged.items():
            active.arrays.setdefault(key, []).append(array)
        active.arrays.setdefault("frame_index", []).append(np.int64(index))
        active.arrays.setdefault("episode_time_s", []).append(np.float64(index / self.fps))
        active.arrays.setdefault("simulation_time_s", []).append(np.float64(simulation_time_s))
        active.arrays.setdefault("control_source_timestamp_ns", []).append(np.int64(control_source_timestamp_ns))
        active.arrays.setdefault("control_receive_timestamp_ns", []).append(np.int64(control_receive_timestamp_ns))
        active.arrays.setdefault("control_sequence", []).append(np.int64(control_sequence))
        captured = time.monotonic_ns() if capture_timestamp_ns is None else capture_timestamp_ns
        active.arrays.setdefault("capture_timestamp_ns", []).append(np.int64(captured))

    def finish(self, *, operator_success: bool | None, evaluator: EvaluatorResultV1,
               failure_reason: str | None = None) -> Path:
        active = self._require_active()
        if self.frame_count <= 0:
            raise RuntimeError("cannot save an empty episode")
        arrays = {key: np.stack(value) for key, value in active.arrays.items()}
        length = self.frame_count
        arrays.update({"reward": np.zeros(length, np.float32), "discount": np.ones(length, np.float32),
                       "is_first": np.zeros(length, np.bool_), "is_last": np.zeros(length, np.bool_),
                       "is_terminal": np.zeros(length, np.bool_)})
        arrays["is_first"][0] = True
        arrays["is_last"][-1] = True
        if evaluator.success is True:
            arrays["reward"][-1], arrays["discount"][-1], arrays["is_terminal"][-1] = 1.0, 0.0, True
        np.savez_compressed(active.path / "trajectory.npz", **arrays)
        manifest = EpisodeManifestV1(
            episode_uuid=active.uuid, episode_index=active.index, task=active.task, robot_id=self.robot_id,
            control_source=self.control_source, fps=self.fps, num_frames=length, features=self.features,
            action_profile=self.action_profile, camera_names=self.camera_names,
            camera_calibration=self.camera_calibration, scene=self.scene, software=self.software,
            evaluator=evaluator, lineage=self.lineage, operator_success=operator_success,
            failure_reason=failure_reason, created_at=datetime.now(timezone.utc),
        )
        (active.path / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
        final = self.root / f"episode_{active.index:06d}"
        active.path.rename(final)
        self._active = None
        return final

    def discard(self) -> None:
        active = self._require_active()
        shutil.rmtree(active.path)
        self._active = None

    def _next_index(self) -> int:
        values = []
        for path in self.root.glob("episode_[0-9]*"):
            suffix = path.name.removesuffix(".tmp").removeprefix("episode_")
            if suffix.isdigit(): values.append(int(suffix))
        return max(values, default=-1) + 1

    def _require_active(self) -> _ActiveEpisode:
        if self._active is None: raise RuntimeError("no episode is recording")
        return self._active

    def _write_rgb(self, path: Path, image: np.ndarray) -> None:
        image = np.asarray(image)
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[-1] not in {3, 4}:
            raise ValueError(f"expected uint8 HWC RGB/RGBA image, got {image.dtype} {image.shape}")
        rgb = image[..., :3]
        try:
            import cv2
        except ImportError:
            from PIL import Image

            Image.fromarray(rgb).save(path, format="JPEG", quality=self.jpeg_quality)
            return
        ok = cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        if not ok: raise OSError(f"failed to write image: {path}")
