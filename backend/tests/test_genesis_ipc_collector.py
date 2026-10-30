"""Collector protocol boundary checks without launching either simulator."""
import importlib.util
from pathlib import Path
import threading
import numpy as np
import pytest

MODULE = Path(__file__).resolve().parents[2] / 'expert_demos/curobo_cloth_v1/teleop/collector.py'
spec = importlib.util.spec_from_file_location('ipc_collector', MODULE)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

class Renderer:
    def poll(self):
        return None


def test_capture_requires_step_and_reset_identity(tmp_path):
    np.savez(tmp_path / 'capture.npz', step=12, reset_id=0, rgb=np.zeros((4, 4, 3), np.uint8), capture_timestamp_ns=123)
    with pytest.raises(TimeoutError):
        collector.capture_frame(tmp_path, {'step':12, 'reset_id':1}, Renderer(), threading.Event(), timeout=.01)
    rgb, stamp = collector.capture_frame(tmp_path, {'step':12, 'reset_id':0}, Renderer(), threading.Event())
    assert rgb.shape == (4, 4, 3) and stamp == 123


def test_renderer_exit_stops_recording_wait(tmp_path):
    class Exited:
        def poll(self):
            return 1
    with pytest.raises(RuntimeError, match='renderer exited'):
        collector.capture_frame(tmp_path, {'step':0, 'reset_id':0}, Exited(), threading.Event())


def test_operator_success_does_not_set_automatic_success():
    class Writer:
        is_recording = True
        frame_count = 3
        def finish(self, **kwargs):
            self.result = kwargs
            self.is_recording = False
            return '/episode_000001'
    c = collector.Collector('localhost', 1, '/unused', 10, .004, 25, 640, 480)
    c.writer = Writer()
    c.recording_command('success')
    assert c.writer.result['operator_success'] is True
    assert c.writer.result['auto_success'] is None
    assert c.saved == ['/episode_000001']


def test_rigid_episode_has_object_pose_without_cloth_arrays():
    class Writer:
        is_recording = True
        frame_count = 1
        def add_frame(self, **kwargs):
            self.frame = kwargs
    c = collector.Collector('localhost', 1, '/unused', 10, .004, 25, 640, 480, rigid_only=True)
    c.writer = Writer()
    c.add_frame(image=np.zeros((4,4,3),np.uint8),
        state={'qpos':[0]*9, 'qvel':[0]*9,'time':0.,'step':0,'reset_id':0,
               'hand':[0]*3,'hand_quat':[1,0,0,0],'object_pose':[0,0,1,1,0,0,0]},
        action=np.zeros(9),requested=np.zeros(9),safe=np.zeros(9),operator=np.zeros(7),
        sequence=0,source_ns=1,receive_ns=1,capture_ns=2,velocity=None)
    assert c.message['scene_id'] == 'genesis_ipc_rigid_single'
    assert c.writer.frame['object_pose'].shape == (7,)
    assert 'cloth_particles' not in c.writer.frame
