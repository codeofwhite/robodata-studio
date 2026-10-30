# Architecture

![RoboData Studio system architecture by IPPLab](assets/architecture.svg)

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

## Interface and data flow

The Studio UI calls the API over HTTP. The API owns the SQLite index and worker
lifecycle; launch and status operations do not move the control loop into the API.
Keyboard/GELLO clients send input through the worker's WebSocket protocol. The
worker applies ownership, watchdog and safety checks, interacts with the simulator
runtime, and records observations, applied actions and camera images.

The dashed contracts edge denotes a schema dependency rather than a running
service. Writer/reader code defines the on-disk Episode format. The API scans that
format into the index and maintains QA decisions separately. An explicitly
selected, QA-accepted Episode set is converted in the export environment; the
result retains provenance back to canonical records. The architecture figure
summarizes these boundaries and does not enumerate every API or library call.

## Collection and dataset lifecycle

![Collection to consumer readback workflow](assets/workflow.svg)

A valid Episode may contain an unsuccessful task attempt. Structural validity,
QA acceptance and task outcome answer different questions and remain separate.
Exports are derivatives; raw Episodes remain the source of truth.

Editable [architecture](assets/specs/architecture.json) and
[workflow](assets/specs/workflow.json) specifications are included with the
[visual provenance and reproduction instructions](assets/README.md).
