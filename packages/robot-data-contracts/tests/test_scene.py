from robot_data_contracts.scene import ScenePluginDescriptor


def test_scene_plugin_descriptor_round_trip() -> None:
    descriptor = ScenePluginDescriptor.model_validate(
        {
            "contract": "robot_data_scene_plugin",
            "contract_version": 1,
            "plugin_id": "cloth_scenes",
            "engine_id": "genesis",
            "scenes": [
                {
                    "id": "cloth_corner_lift",
                    "label": "Cloth corner lift",
                    "description": "Lift one cloth corner.",
                    "family": "cloth",
                    "parameters": [
                        {
                            "key": "required_hold_frames",
                            "label": "Required hold frames",
                            "unit": "frames",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 5,
                            "step": 1,
                        }
                    ],
                }
            ],
        }
    )
    assert descriptor.scenes[0].parameters[0].default == 5
