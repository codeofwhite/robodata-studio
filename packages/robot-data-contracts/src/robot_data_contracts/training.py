from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict


TrainingProfileId = Literal[
    "physical_joint8", "openpi_franka_joint8", "fastwam_franka_joint8", "physical_dual_joint16"
]
DualTrainingProfileId = Literal["physical_dual_joint16"]


class TrainingAdapterProfileV1(BaseModel):
    """Versioned, lossless-to-explicit transform from stored physical values."""

    model_config = ConfigDict(extra="forbid")
    id: TrainingProfileId
    state_names: tuple[str, ...]
    action_names: tuple[str, ...]
    state_dimension: int
    action_dimension: int
    gripper_semantics: str
    consumer_settings: dict[str, int | str]


_JOINTS = tuple(f"panda_joint{i}_rad" for i in range(1, 8))
_PHYSICAL_STATE_NAMES = (
    _JOINTS + ("gripper_width_m",)
    + tuple(f"panda_joint{i}_velocity_rad_s" for i in range(1, 8))
    + ("gripper_width_velocity_m_s",)
)
_PHYSICAL_ACTION_NAMES = tuple(f"target_{name}" for name in _JOINTS) + ("target_gripper_width_m",)
_DUAL_PHYSICAL_STATE_NAMES = tuple(
    f"left/{name}" for name in _PHYSICAL_STATE_NAMES
) + tuple(f"right/{name}" for name in _PHYSICAL_STATE_NAMES)
_DUAL_PHYSICAL_ACTION_NAMES = tuple(
    f"left/{name}" for name in _PHYSICAL_ACTION_NAMES
) + tuple(f"right/{name}" for name in _PHYSICAL_ACTION_NAMES)
TRAINING_PROFILES = {
    "physical_joint8": TrainingAdapterProfileV1(
        id="physical_joint8", state_names=_PHYSICAL_STATE_NAMES,
        action_names=_PHYSICAL_ACTION_NAMES,
        state_dimension=16, action_dimension=8, gripper_semantics="total width in metres",
        consumer_settings={"dataset_family": "lerobot"},
    ),
    "physical_dual_joint16": TrainingAdapterProfileV1(
        id="physical_dual_joint16", state_names=_DUAL_PHYSICAL_STATE_NAMES,
        action_names=_DUAL_PHYSICAL_ACTION_NAMES,
        state_dimension=32, action_dimension=16,
        gripper_semantics="two total widths in metres, left then right",
        consumer_settings={"dataset_family": "lerobot"},
    ),
    "openpi_franka_joint8": TrainingAdapterProfileV1(
        id="openpi_franka_joint8", state_names=_JOINTS + ("gripper_closed_fraction",),
        action_names=tuple(f"target_{name}" for name in _JOINTS) + ("target_gripper_closed_fraction",),
        state_dimension=8, action_dimension=8, gripper_semantics="0=open, 1=closed",
        consumer_settings={"model_action_dim": 32, "dataset_action_dim": 8},
    ),
    "fastwam_franka_joint8": TrainingAdapterProfileV1(
        id="fastwam_franka_joint8", state_names=_JOINTS + ("gripper_width_m",),
        action_names=tuple(f"target_{name}" for name in _JOINTS) + ("target_gripper_width_m",),
        state_dimension=8, action_dimension=8,
        gripper_semantics="absolute joint8; configure action_dim=8 and proprio_dim=8",
        consumer_settings={"action_dim": 8, "proprio_dim": 8, "action_horizon": 32,
                           "num_video_frames": 33, "action_video_freq_ratio": 4},
    ),
}


def adapt_franka_joint8(
    policy_state: np.ndarray,
    policy_action: np.ndarray,
    profile_id: TrainingProfileId,
    *,
    maximum_gripper_width_m: float = 0.08,
) -> tuple[np.ndarray, np.ndarray]:
    """Adapt canonical 16-D state and 8-D physical action without mutating raw data."""
    state = np.asarray(policy_state, dtype=np.float32).reshape(-1)
    action = np.asarray(policy_action, dtype=np.float32).reshape(-1)
    if state.shape != (16,) or action.shape != (8,):
        raise ValueError("canonical Franka policy state/action must have shapes (16,) and (8,)")
    if not np.isfinite(state).all() or not np.isfinite(action).all():
        raise ValueError("policy state/action must be finite")
    if maximum_gripper_width_m <= 0:
        raise ValueError("maximum_gripper_width_m must be positive")
    adapted_state = state.copy() if profile_id == "physical_joint8" else state[:8].copy()
    adapted_action = action.copy()
    if profile_id == "openpi_franka_joint8":
        adapted_state[7] = 1.0 - np.clip(adapted_state[7] / maximum_gripper_width_m, 0.0, 1.0)
        adapted_action[7] = 1.0 - np.clip(adapted_action[7] / maximum_gripper_width_m, 0.0, 1.0)
    elif profile_id not in TRAINING_PROFILES:
        raise ValueError(f"unknown training profile: {profile_id}")
    return adapted_state.astype(np.float32), adapted_action.astype(np.float32)


def adapt_dual_franka_joint16(
    policy_state: np.ndarray,
    policy_action: np.ndarray,
    profile_id: DualTrainingProfileId,
    *,
    maximum_gripper_width_m: float = 0.08,
) -> tuple[np.ndarray, np.ndarray]:
    """Adapt canonical dual 32-D state and 16-D physical action without mutating raw data.

    The single-arm ``adapt_franka_joint8`` refuses these shapes on purpose; dual
    call sites must come here so the two contracts cannot be silently mixed.
    """
    state = np.asarray(policy_state, dtype=np.float32).reshape(-1)
    action = np.asarray(policy_action, dtype=np.float32).reshape(-1)
    if state.shape != (32,) or action.shape != (16,):
        raise ValueError("canonical dual Franka policy state/action must have shapes (32,) and (16,)")
    if not np.isfinite(state).all() or not np.isfinite(action).all():
        raise ValueError("policy state/action must be finite")
    if maximum_gripper_width_m <= 0:
        raise ValueError("maximum_gripper_width_m must be positive")
    if profile_id != "physical_dual_joint16":
        raise ValueError(f"unknown dual training profile: {profile_id}")
    return state.copy(), action.copy()
