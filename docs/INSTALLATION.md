# Installation and collection configuration

Start with the UI/API instructions in [README](../README.md). Tested host versions
and exact scope are in [VALIDATION](VALIDATION.md). Use separate Python environments
for the API, Isaac Lab worker and LeRobot export. No installation command below
installs the simulator or supplies robot assets.

## API and frontend

Use Python 3.12+, Node 22.13+ and the complete repository checkout. Read .env.example
before creating a local .env. Source it from the repository root; never commit .env.
The frontend API address is a build-time setting. The default API CORS origins are
localhost:3000 and 127.0.0.1:3000; use the documented ports for the local workflow.

A simulator may appear in the UI while unavailable. That advertises an adapter,
not a working SDK. A session can be created without starting a worker.

## Isaac worker

Install a compatible Isaac Sim / Isaac Lab runtime separately under its own terms.
Set the launcher, interpreter prefix and Panda USD path in your local configuration.
The predecessor ran with Isaac Sim 6.0.1 and Isaac Lab 3.0; this is not a guarantee
that every newer SDK build is compatible. The public collector was not rerun on a
GPU after removing the prebuilt console and private camera identifiers.

Install this checkout's contracts and teleop[isaaclab] with the simulator's Python:

```bash
"${ROBOT_DATA_STUDIO_ISAACLAB_CONDA_PREFIX}/bin/python" -m pip install \
  "${STUDIO_ROOT}/packages/robot-data-contracts" "${STUDIO_ROOT}/teleop[isaaclab]"
```

Choose GPU/device explicitly, inspect its ownership and memory before launch, and
use a separate data directory. Public camera profiles are nominal and have no
physical calibration serials. Supply your own calibration rather than treating
these example extrinsics/intrinsics as measured hardware parameters.

## Optional Collector console

The browser console depends on @nvidia/omniverse-webrtc-streaming-library. The public
repository contains its integration source and package lock, not the prebuilt SDK
bundle. Review the NVIDIA terms applicable to your use and installation; this
project does not grant a license to that library.

After making that determination, the existing console build commands are:

```bash
cd teleop/web_console
npm ci --no-audit --no-fund
npm run build
```

The scoped registry is configured in this directory's .npmrc. Vite writes the local
build into teleop/src/gello_remote/web/console, which is Git-ignored. The worker reads
that directory by default, or use GELLO_WEB_CONSOLE_ROOT for a separately built
console. Until then, GET / on the Collector returns a clear not-built error.
Rebuild/reinstall your worker package after a local console build if you use an
installed worker rather than its source. Do not publish a resulting vendor-containing
wheel without separately checking its applicable distribution terms.

Web Serial uses devices attached to the computer running the browser. Permission,
calibration, watchdog behavior and physical dual-USB operation need hardware testing;
no such test is implied by the source/CPU checks. Do not bypass existing safety logic.

## LeRobot export

Prepare a compatible LeRobot interpreter separately and set
ROBOT_DATA_STUDIO_LEROBOT_PYTHON. The predecessor's data check used LeRobot 0.6.2,
v3 format and CPU PyAV decoding. Export requires explicit Episode selection and QA
acceptance; it does not automatically launch a model or training workload.
Raw recordings, SDKs, USD files and optional model checkpoints are user-managed.
