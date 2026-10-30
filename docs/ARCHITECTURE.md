# Architecture

RoboData Studio · by IPPLab uses separate processes and environments:

| Layer | Owns | Boundary |
| --- | --- | --- |
| UI | Session/review/export controls | HTTP calls to the configured API |
| API | Index, QA decisions, jobs, worker identity and resource locks | Does not implement the simulator control loop |
| Teleop worker | Input ownership, watchdog, safe commands, recording | Does not import Studio business services |
| Contracts | Versioned schemas, writer, reader and validator | No simulator SDK or database dependency |
| Export environment | Training-format conversion | Explicit interpreter; no automatic model job after export |

The default adapter exposes only Isaac Panda rigid_cube_lift, Keyboard/GELLO and
PhysX. Other integration source remains experimental and requires explicit flags,
external dependencies and its own validation.

Canonical robot_data_episode v1 is the original record: manifest, trajectory arrays
and camera images. Observation t is captured before action t is submitted. Operator
outcome, evaluator outcome and QA acceptance are separate. Scanning indexes an
Episode as pending; only accepted Episodes may be exported. Export profiles state
the action/gripper semantics and retain source provenance.

Backend wheels install migrations, camera profiles and renderer profiles under the
Python environment's share/robot-data-studio directory. Source imports use repository
resources. Missing required SQL fails before opening the database. Building wheels
requires the complete checkout; standalone backend-directory, sdist, pip --target
and cross-platform builds have not been certified.

The optional console build is independent of worker control/recording. HTTP returns
an explicit not-built error until a local build exists; the WebSocket protocol can
be used independently. See [installation](INSTALLATION.md).
