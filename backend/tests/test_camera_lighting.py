import json
import pytest
from robot_data_contracts.camera_lighting import CameraLightingRequest, sample
from robot_data_studio.services.camera_lighting import resolve_camera_lighting

def test_defaults_and_session_json():
    default = sample(None)
    assert default['values']['exposure_ev'] == default['values']['fov_offset_deg'] == 0
    assert default['values']['white_balance_k'] is None
    assert resolve_camera_lighting(json.dumps({'values': {'exposure_ev': 1}}))['values']['exposure_ev'] == 1

def test_uniform_sampling_is_pinned_by_seed_and_attempt():
    request = {'mode': 'uniform', 'seed': 73, 'ranges': {'fov_offset_deg': [-3,3], 'white_balance_k': [4000,6000]}}
    first = sample(request, source_index=1, appearance_index=2)
    assert first == sample(request, source_index=1, appearance_index=2)
    assert first != sample(request, source_index=2, appearance_index=2)
    assert -3 <= first['values']['fov_offset_deg'] <= 3
    assert 4000 <= first['values']['white_balance_k'] <= 6000

@pytest.mark.parametrize('candidate', [
    {'values': {'exposure_ev': float('nan')}}, {'values': {'camera_x_m': .31}},
    {'mode': 'uniform', 'ranges': {'unknown': [0,1]}},
    {'mode': 'uniform', 'ranges': {'exposure_ev': [2,1]}},
    {'mode': 'uniform', 'ranges': {'white_balance_k': [1000,6000]}},
    {'ranges': {'exposure_ev': [0,1]}},
])
def test_invalid_parameters_fail_before_launch(candidate):
    with pytest.raises(ValueError): CameraLightingRequest.model_validate(candidate)
