# Validation

Verified on 2026-10-30. This is an initial public source snapshot, not a physical
robot validation or a task-success benchmark.

## Checks on this public snapshot

Host tools: Python 3.12.3, Node 24.18.0 and npm 11.16.0. Existing isolated Python
environments and an existing frontend dependency installation were reused; this
round did not establish a fresh-machine installation of the public snapshot.

| Check | Result |
| --- | --- |
| Frontend production build, `NEXT_PUBLIC_STUDIO_API=http://127.0.0.1:18011/api npm run build` | Passed; large-chunk and routing-classification warnings remain |
| Root TypeScript, `npm exec --no -- tsc --noEmit --incremental false` | Passed; optional Collector console has a separate TypeScript project |
| Selected CPU regression tests | 173 passed in 4.76 s; one TestClient dependency deprecation warning |
| Contracts, teleop and backend wheel builds, `python -B -m build --wheel --no-isolation` | All three passed |
| Wheel license inspection | Each contains root LICENSE, NOTICE and THIRD_PARTY_NOTICES.md with matching bytes and Apache-2.0 metadata |
| Vendor bundle inspection | No prebuilt Collector console in any of the three wheels |

The selected CPU regression command, run from the repository root with the three
source directories on PYTHONPATH, was:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH=backend/src:packages/robot-data-contracts/src:teleop/src \
python -m pytest -p no:cacheprovider -q \
  backend/tests/test_gello_integration.py \
  teleop/tests/test_protocol.py \
  teleop/tests/test_control.py \
  teleop/tests/test_backends.py \
  teleop/tests/test_fake_gello_client.py \
  teleop/tests/test_isaac_bimanual_control.py \
  teleop/tests/test_isaaclab_gello.py \
  teleop/tests/test_openpi_policy.py \
  backend/tests/test_public_core.py \
  backend/tests/test_episode_contract.py \
  backend/tests/test_export_provenance.py \
  packages/robot-data-contracts/tests/test_assets.py \
  packages/robot-data-contracts/tests/test_rendering.py \
  packages/robot-data-contracts/tests/test_scene.py
```

The actual run used temporary database, data, workspace and pytest directories.
Use your own temporary paths through ROBOT_DATA_STUDIO_DB,
ROBOT_DATA_STUDIO_DATA_ROOT and ROBOT_DATA_STUDIO_WORKSPACE_ROOT.

An earlier broader test collection failed because Pillow and OpenCV were absent
from that environment. Its failure log was retained locally. Those optional image
and Genesis tests were not counted as passes; this is not a full-suite result.
The optional NVIDIA-dependent console was not rebuilt in this release check.

## Earlier simulated collection evidence

An internal predecessor completed collection → QA → LeRobot export → CPU readback
with Isaac Sim 6.0.1, Isaac Lab 3.0, Panda/PhysX, keyboard input over WebSocket and
LeRobot 0.6.2 v3 format:

- 100 newly collected frames, four 640 × 480 camera streams; 400 JPEGs decoded.
- Canonical scan: one valid Episode, no invalid Episodes.
- Export before QA acceptance returned HTTP 422; after acceptance it completed.
- Readback recovered all 100 frames with zero action/state discrepancy; all four
  exported videos decoded to 100 frames each.
- SHA-256 checks over 402 source files remained unchanged by export.

The recorded task failed, and that failure was retained. Automated data-integrity
QA acceptance does not mean human review or task success. The simulation span was
9.9 s and capture span 11.716 s; configured 10 Hz is not measured wall-clock rate.

That predecessor included a locally built console and camera metadata subsequently
removed from the public snapshot. The public snapshot has not repeated this GPU
collection. Physical GELLO, real robots, dual-USB operation, hardware calibration,
fresh-machine reproduction and downstream policy training remain unverified here.
