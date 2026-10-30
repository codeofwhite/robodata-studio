import json

import numpy as np

from robot_data_contracts import (
    AugmentationLineageV1,
    EpisodeWriter,
    EvaluatorResultV1,
    SceneProvenanceV1,
    SoftwareProvenanceV1,
    open_canonical_episode,
)
from robot_data_contracts.profiles.franka import FRANKA_JOINT8_ACTION, franka_feature_specs
from robot_data_studio.exporters.common import preflight_canonical_episodes, write_directory_provenance
from robot_data_studio.exporters.robomimic import _hdf5_attribute_value


def _episode(root, engine_id: str, *, fps: int = 10, cameras: tuple[str, ...] = ()):
    calibration = {
        name: {"intrinsics": [1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0],
               "extrinsics": {"eye_world_m": [1.0, 1.0, 1.0]}}
        for name in cameras
    }
    writer = EpisodeWriter(
        root,
        fps=fps,
        robot_id="franka_panda",
        control_source="keyboard",
        features=franka_feature_specs(),
        action_profile=FRANKA_JOINT8_ACTION,
        camera_names=cameras,
        camera_calibration=calibration,
        scene=SceneProvenanceV1(scene_id="rigid_pick_place", seed=0),
        software=SoftwareProvenanceV1(
            python_version="test", platform="test", engine_id=engine_id,
            engine_version="test-version", worker_id=f"{engine_id}-worker",
        ),
        lineage=AugmentationLineageV1(generation_method="teleoperation"),
    )
    writer.start("pick and place")
    writer.add_frame(
        images={name: np.zeros((4, 4, 3), np.uint8) for name in cameras},
        values={
            "native_state": np.zeros(18, np.float32),
            "policy_state": np.zeros(16, np.float32),
            "operator_action": np.zeros(7, np.float32),
            "requested_action": np.zeros(8, np.float32),
            "safe_action": np.zeros(8, np.float32),
            "applied_action": np.zeros(8, np.float32),
        },
        simulation_time_s=0.0,
    )
    path = writer.finish(
        operator_success=True,
        evaluator=EvaluatorResultV1(
            evaluator_id="test", evaluator_version="1", available=True, success=True,
        ),
    )
    return open_canonical_episode(path)


def test_directory_provenance_preserves_engine_per_episode(tmp_path):
    genesis = _episode(tmp_path / "genesis", "genesis")
    isaac = _episode(tmp_path / "isaac", "isaac_sim")
    output = tmp_path / "export"

    destination = write_directory_provenance(output, [genesis, isaac])
    rows = [json.loads(line) for line in destination.read_text().splitlines()]

    assert [row["engine_id"] for row in rows] == ["genesis", "isaac_sim"]
    assert [row["output_episode_index"] for row in rows] == [0, 1]
    assert rows[0]["source_episode_uuid"] == genesis.manifest.episode_uuid
    assert rows[1]["worker_id"] == "isaac_sim-worker"
    assert rows[1]["operator_success"] is True
    assert rows[1]["automatic_success"] is True
    assert rows[1]["evaluator_id"] == "test"


def test_robomimic_provenance_attributes_encode_nullable_values():
    assert _hdf5_attribute_value(None) == "null"
    assert _hdf5_attribute_value({"success": False}) == '{"success": false}'
    assert _hdf5_attribute_value([1, 2]) == "[1, 2]"
    assert _hdf5_attribute_value(False) is False
    assert _hdf5_attribute_value("roboverse_sapien3") == "roboverse_sapien3"


def test_preflight_allows_contract_compatible_mixed_simulators(tmp_path):
    genesis = _episode(tmp_path / "genesis", "genesis")
    isaac = _episode(tmp_path / "isaac", "isaac_sim")

    report = preflight_canonical_episodes(
        [genesis.path, isaac.path], format_name="robomimic", profile="physical_joint8"
    )

    assert report["compatible"] is True
    assert report["engine_counts"] == {"genesis": 1, "isaac_sim": 1}
    assert report["provenance_complete"] is True
    assert report["warnings"]


def test_preflight_rejects_mismatched_fps_with_episode_ids(tmp_path):
    genesis = _episode(tmp_path / "genesis", "genesis", fps=10)
    isaac = _episode(tmp_path / "isaac", "isaac_sim", fps=20)

    try:
        preflight_canonical_episodes(
            [genesis.path, isaac.path], format_name="robomimic", profile="physical_joint8"
        )
    except ValueError as error:
        message = str(error)
    else:
        raise AssertionError("mismatched FPS must fail preflight")

    assert "fps mismatch" in message
    assert genesis.manifest.episode_uuid in message
    assert isaac.manifest.episode_uuid in message


def test_openpi_preflight_requires_base_and_wrist_and_reports_consumed_views(tmp_path, monkeypatch):
    monkeypatch.setattr(
        EpisodeWriter,
        "_write_rgb",
        lambda _self, path, _image: path.write_bytes(b"test-jpeg"),
    )
    missing_wrist = _episode(tmp_path / "missing", "isaac_sim", cameras=("base", "top"))

    try:
        preflight_canonical_episodes(
            [missing_wrist.path],
            format_name="openpi_lerobot_v21",
            profile="openpi_franka_joint8",
        )
    except ValueError as error:
        assert "wrist" in str(error)
    else:
        raise AssertionError("OpenPI preflight must reject a missing wrist camera")

    ready = _episode(
        tmp_path / "ready", "isaac_sim", cameras=("base", "top", "side", "wrist")
    )
    report = preflight_canonical_episodes(
        [ready.path],
        format_name="openpi_lerobot_v21",
        profile="openpi_franka_joint8",
    )

    assert report["consumer_camera_names"] == ["base", "wrist"]
    assert any("QA-only" in warning for warning in report["warnings"])
