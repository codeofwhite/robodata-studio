# RoboData Studio · by IPPLab

[English](README.md) | [简体中文](README.zh-CN.md)

A simulation-first workspace for collecting robot demonstrations, reviewing their
quality, and exporting accepted Episodes to learning datasets.

**Record → validate → QA → export → read back.** Original Episodes stay unchanged;
QA decisions live in the index and training formats are rebuildable derivatives.

This is an initial public source snapshot with a new Git history. The reference
collector is Isaac Panda `rigid_cube_lift` with PhysX and Keyboard/GELLO input.
Physical GELLO, real-robot operation and task success are not validated claims.

## What is included

| Component | Location | Responsibility |
| --- | --- | --- |
| Studio UI | `app/`, `components/` | Sessions, review and export workflow |
| Studio API | `backend/` | SQLite index, QA, isolated workers and export jobs |
| Shared contracts | `packages/robot-data-contracts/` | Canonical Episode v1, reader, writer and validation |
| GELLO Remote | `teleop/` | Input protocol, safety filters, simulation workers and console source |

The three Python packages retain their existing import names. API, simulator and
LeRobot environments remain separate. Optional cloth/generation/asset integrations
remain disabled by default; their source presence is not a support commitment.

## Quick start: UI and API

Requires Python 3.12+ and Node.js 22.13+. Use the complete checkout so backend wheel
builds can include the adjacent configuration files. From the repository root:

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install ./packages/robot-data-contracts ./teleop './backend[dev]'
# Review the template first; keep any existing local configuration.
test -f .env || cp .env.example .env
set -a
source .env
set +a
backend/.venv/bin/python -m uvicorn robot_data_studio.main:app --host 127.0.0.1 --port 8010
```

In another terminal, from the same repository:

```bash
npm ci --no-audit --no-fund
npm run build
npm run start -- --hostname 127.0.0.1 --port 3000
```

Open `http://127.0.0.1:3000`; API documentation is at `http://127.0.0.1:8010/docs`.
For development use `npm run dev -- --host 127.0.0.1`. Set `NEXT_PUBLIC_STUDIO_API`
before the frontend build if the API address differs. Local builds do not require
Sites/Cloudflare accounts or hosting metadata.

The UI/API can run without a simulator. Recording requires a separately installed,
compatible SDK, robot asset, explicitly selected GPU and worker environment. See
[installation](docs/INSTALLATION.md) before launching collection.

## Collector console and external dependencies

**The prebuilt NVIDIA-containing WebRTC console is not distributed in this snapshot.**
The worker WebSocket protocol and recording logic are present. Opening the Collector
root page before a local console build returns `Web console is not built`.

The console source is in `teleop/web_console/`. Review NVIDIA's applicable terms,
then build it locally in your own environment as described in the installation guide.
No simulator SDK, robot USD, historical deployment bundle, checkpoint, calibration
serial, recorded dataset, or internal experiment directory is included.

## Validation and limits

See [validation](docs/VALIDATION.md) for checks on this exact public snapshot and a
separate summary of the predecessor's 100-frame Isaac collection → QA → LeRobot
readback. The latter used agent-generated Keyboard messages and saved a failed
cube-lift trajectory. Data integrity passing does not mean task success or hardware
validation. A console HTTP fixture is not an actual SDK build or stream test.

## IPPLab tool series

RoboData Studio is the first entry in a set of tools **by IPPLab**. SceneKit (scenes)
and DataAugment (augmentation) are roadmap names, not claims of released projects.
GELLO Remote and contracts stay bundled until an independent release is useful.
See [the ecosystem roadmap](docs/ECOSYSTEM.md) and [architecture](docs/ARCHITECTURE.md).

## License and attribution

Original code the contributors are authorized to license is provided under
[Apache-2.0](LICENSE). [NOTICE](NOTICE) and [third-party notices](THIRD_PARTY_NOTICES.md)
identify exceptions and attributions. SDKs and external assets retain their own terms;
public availability alone is not a redistribution grant. See [asset boundaries](docs/LICENSES_AND_ASSETS.md).
