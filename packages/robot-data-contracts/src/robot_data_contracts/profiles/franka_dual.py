"""Dual-Franka physical profile: left arm block then right arm block.

Dimensions are derived from the audited single-arm profile so the two cannot
drift: native 18x2=36, policy state 16x2=32, policy action 8x2=16.
Every dual name is the single-arm name under a ``left/`` or ``right/`` prefix.
"""

from __future__ import annotations

import numpy as np

from ..features import ActionProfileV1, FeatureRole, FeatureSpecV1
from .franka import (
    NATIVE_STATE_NAMES,
    POLICY_STATE_NAMES,
    FRANKA_JOINT8_ACTION,
    policy_action_from_native,
    policy_state_from_native,
)

ARM_ORDER = ("left", "right")
DUAL_ROBOT_ID = "franka_panda_dual"


def _prefixed(prefix: str, names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"{prefix}/{name}" for name in names)


def _both_arms(names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(part for arm in ARM_ORDER for part in _prefixed(arm, names))


DUAL_NATIVE_STATE_NAMES = _both_arms(NATIVE_STATE_NAMES)
DUAL_POLICY_STATE_NAMES = _both_arms(POLICY_STATE_NAMES)
DUAL_POLICY_ACTION_NAMES = _both_arms(FRANKA_JOINT8_ACTION.names)
DUAL_ACTION_UNITS = FRANKA_JOINT8_ACTION.units * len(ARM_ORDER)

DUAL_NATIVE_STATE_SHAPE = (len(DUAL_NATIVE_STATE_NAMES),)
DUAL_POLICY_STATE_SHAPE = (len(DUAL_POLICY_STATE_NAMES),)
DUAL_POLICY_ACTION_SHAPE = (len(DUAL_POLICY_ACTION_NAMES),)

DUAL_JOINT8_ACTION = ActionProfileV1(
    id="dual_franka_joint16_physical",
    representation="absolute_joint_position",
    dimension=len(DUAL_POLICY_ACTION_NAMES),
    names=DUAL_POLICY_ACTION_NAMES,
    units=DUAL_ACTION_UNITS,
    gripper_semantics=(
        "two parallel-jaw openings, left then right; 0 m closed, 0.08 m open"
    ),
)


def dual_policy_state_from_native(value: np.ndarray) -> np.ndarray:
    state = np.asarray(value, dtype=np.float32).reshape(-1)
    expected = 2 * len(NATIVE_STATE_NAMES)
    if state.shape != (expected,) or not np.isfinite(state).all():
        raise ValueError(f"dual Franka native state must contain {expected} finite values")
    half = len(NATIVE_STATE_NAMES)
    return np.concatenate(
        [policy_state_from_native(state[:half]), policy_state_from_native(state[half:])]
    ).astype(np.float32)


def dual_policy_action_from_native(value: np.ndarray) -> np.ndarray:
    action = np.asarray(value, dtype=np.float32).reshape(-1)
    expected = 2 * (len(FRANKA_JOINT8_ACTION.names) + 1)
    if action.shape != (expected,) or not np.isfinite(action).all():
        raise ValueError(f"dual Franka native action must contain {expected} finite values")
    half = len(FRANKA_JOINT8_ACTION.names) + 1
    return np.concatenate(
        [policy_action_from_native(action[:half]), policy_action_from_native(action[half:])]
    ).astype(np.float32)


def dual_franka_feature_specs(
    operator_names: tuple[str, ...] = tuple(f"operator_{i}" for i in range(14)),
) -> tuple[FeatureSpecV1, ...]:
    return (
        FeatureSpecV1(
            key="native_state", role=FeatureRole.NATIVE_STATE, dtype="float32",
            shape=DUAL_NATIVE_STATE_SHAPE, names=DUAL_NATIVE_STATE_NAMES,
        ),
        FeatureSpecV1(
            key="policy_state", role=FeatureRole.POLICY_STATE, dtype="float32",
            shape=DUAL_POLICY_STATE_SHAPE, names=DUAL_POLICY_STATE_NAMES,
        ),
        FeatureSpecV1(
            key="operator_action", role=FeatureRole.OPERATOR_ACTION, dtype="float32",
            shape=(len(operator_names),), names=operator_names,
        ),
        FeatureSpecV1(
            key="requested_action", role=FeatureRole.REQUESTED_ACTION, dtype="float32",
            shape=DUAL_POLICY_ACTION_SHAPE, names=DUAL_POLICY_ACTION_NAMES, units=DUAL_ACTION_UNITS,
        ),
        FeatureSpecV1(
            key="safe_action", role=FeatureRole.SAFE_ACTION, dtype="float32",
            shape=DUAL_POLICY_ACTION_SHAPE, names=DUAL_POLICY_ACTION_NAMES, units=DUAL_ACTION_UNITS,
        ),
        FeatureSpecV1(
            key="applied_action", role=FeatureRole.APPLIED_ACTION, dtype="float32",
            shape=DUAL_POLICY_ACTION_SHAPE, names=DUAL_POLICY_ACTION_NAMES, units=DUAL_ACTION_UNITS,
        ),
    )
