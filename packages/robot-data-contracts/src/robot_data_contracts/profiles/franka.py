from __future__ import annotations

import numpy as np

from ..features import ActionProfileV1, FeatureRole, FeatureSpecV1

JOINT_NAMES = tuple(f"panda_joint{i}" for i in range(1, 8))
POLICY_STATE_NAMES = tuple(f"joint_position/{name}_rad" for name in JOINT_NAMES) + ("gripper_width_m",) + tuple(
    f"joint_velocity/{name}_rad_s" for name in JOINT_NAMES
) + ("gripper_width_velocity_m_s",)
POLICY_ACTION_NAMES = tuple(f"target_joint_position/{name}_rad" for name in JOINT_NAMES) + ("target_gripper_width_m",)
NATIVE_STATE_NAMES = tuple(f"joint_position/{name}_rad" for name in JOINT_NAMES) + (
    "joint_position/panda_finger_joint1_m", "joint_position/panda_finger_joint2_m",
) + tuple(f"joint_velocity/{name}_rad_s" for name in JOINT_NAMES) + (
    "joint_velocity/panda_finger_joint1_m_s", "joint_velocity/panda_finger_joint2_m_s",
)
NATIVE_ACTION_NAMES = tuple(f"target_joint_position/{name}_rad" for name in JOINT_NAMES) + (
    "target_joint_position/panda_finger_joint1_m", "target_joint_position/panda_finger_joint2_m",
)

FRANKA_JOINT8_ACTION = ActionProfileV1(
    id="franka_joint8_physical", representation="absolute_joint_position", dimension=8,
    names=POLICY_ACTION_NAMES, units=("rad",) * 7 + ("m",),
    gripper_semantics="total parallel-jaw opening; 0 m closed, 0.08 m open",
)


def policy_state_from_native(value: np.ndarray) -> np.ndarray:
    state = np.asarray(value, dtype=np.float32).reshape(-1)
    if state.shape != (18,) or not np.isfinite(state).all():
        raise ValueError("Franka native state must contain 18 finite values")
    return np.concatenate([state[:7], [state[7] + state[8]], state[9:16], [state[16] + state[17]]]).astype(np.float32)


def policy_action_from_native(value: np.ndarray) -> np.ndarray:
    action = np.asarray(value, dtype=np.float32).reshape(-1)
    if action.shape != (9,) or not np.isfinite(action).all():
        raise ValueError("Franka native action must contain 9 finite values")
    return np.concatenate([action[:7], [action[7] + action[8]]]).astype(np.float32)


def franka_feature_specs(operator_names: tuple[str, ...] = tuple(f"operator_{i}" for i in range(7))) -> tuple[FeatureSpecV1, ...]:
    action_units = ("rad",) * 7 + ("m",)
    return (
        FeatureSpecV1(key="native_state", role=FeatureRole.NATIVE_STATE, dtype="float32", shape=(18,), names=NATIVE_STATE_NAMES),
        FeatureSpecV1(key="policy_state", role=FeatureRole.POLICY_STATE, dtype="float32", shape=(16,), names=POLICY_STATE_NAMES),
        FeatureSpecV1(key="operator_action", role=FeatureRole.OPERATOR_ACTION, dtype="float32", shape=(len(operator_names),), names=operator_names),
        FeatureSpecV1(key="requested_action", role=FeatureRole.REQUESTED_ACTION, dtype="float32", shape=(8,), names=POLICY_ACTION_NAMES, units=action_units),
        FeatureSpecV1(key="safe_action", role=FeatureRole.SAFE_ACTION, dtype="float32", shape=(8,), names=POLICY_ACTION_NAMES, units=action_units),
        FeatureSpecV1(key="applied_action", role=FeatureRole.APPLIED_ACTION, dtype="float32", shape=(8,), names=POLICY_ACTION_NAMES, units=action_units),
    )
