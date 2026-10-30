"""Resolve session visual configuration; batches resolve each attempt in the planner."""
import json
from robot_data_contracts.camera_lighting import sample

def resolve_camera_lighting(raw):
    return sample(json.loads(raw) if isinstance(raw, str) else raw)
