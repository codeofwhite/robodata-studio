import numpy as np

from robot_data_contracts import (
    AugmentationLineageV1, EpisodeWriter, EvaluatorResultV1, SceneProvenanceV1,
    SoftwareProvenanceV1, inspect_episode,
)
from robot_data_contracts.profiles.franka import FRANKA_JOINT8_ACTION, franka_feature_specs


def test_generic_writer_and_inspector_preserve_unavailable_automatic_outcome(tmp_path):
    writer = EpisodeWriter(
        tmp_path,
        fps=20,
        robot_id="franka_panda",
        control_source="gello",
        features=franka_feature_specs(), action_profile=FRANKA_JOINT8_ACTION,
        camera_names=(), camera_calibration={},
        scene=SceneProvenanceV1(scene_id="franka_empty", seed=0),
        software=SoftwareProvenanceV1(python_version="test", platform="test", engine_id="isaac_sim", engine_version="test", worker_id="test"),
        lineage=AugmentationLineageV1(generation_method="teleoperation"),
    )
    writer.start("move safely")
    writer.add_frame(
        images={}, values={
            "native_state": np.zeros(18, np.float32), "policy_state": np.zeros(16, np.float32),
            "operator_action": np.zeros(7, np.float32), "requested_action": np.zeros(8, np.float32),
            "safe_action": np.zeros(8, np.float32), "applied_action": np.zeros(8, np.float32),
        }, simulation_time_s=0.0, control_source_timestamp_ns=10,
    )
    episode_path = writer.finish(operator_success=True, evaluator=EvaluatorResultV1(
        evaluator_id="none", evaluator_version="1", available=False, unavailable_reason="empty scene"))

    descriptor = inspect_episode(episode_path / "manifest.json", engine_id="isaac_sim")

    assert descriptor.num_frames == 1
    assert descriptor.operator_success is True
    assert descriptor.auto_success is None
    assert descriptor.manifest["evaluator"]["available"] is False
