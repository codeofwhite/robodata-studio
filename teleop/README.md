# GELLO Remote · bundled with RoboData Studio by IPPLab

The gello-remote 0.1.0 distribution provides input ownership, watchdog/safety filtering,
mock backends and isolated simulation workers. It was imported from commit
b751a20e58f373e5415de511573fcff7225061be. Original control/safety/protocol and simulator
worker implementations are unchanged by this public snapshot. It does not supply a
validated real-robot controller.

Install from the complete suite checkout in your selected Python environment:

```bash
python -m pip install ./packages/robot-data-contracts ./teleop
```

The shared robot-data-contracts 0.2.0 source lives only in
[packages/robot-data-contracts](../packages/robot-data-contracts). Imports remain
`gello_remote` and `robot_data_contracts`; the worker does not import Studio services.
SDKs and assets are separate dependencies. The Isaac transport extra is
`./teleop[isaaclab]`, to be installed with the simulator's own Python after checking
its environment. Genesis/cloth/policy integrations remain optional, not reference
paths validated by this release.

## Optional browser console

The public tree and verification wheels do not include a prebuilt NVIDIA console.
The worker reports an explicit not-built error at its HTTP root until a local
console build exists. Its control WebSocket and recording logic remain available.
Follow the [installation guide](../docs/INSTALLATION.md) for the local console build,
external registry/terms and GELLO_WEB_CONSOLE_ROOT. A build performed by an operator
does not make the vendor-containing result approved for public redistribution.

Runtime web resources for the separate Genesis/cloth examples are included as
source resources, but their presence is not proof of simulation or hardware support.
The public HTTP tests use clearly synthetic HTML/JS fixtures, not a vendor build.

See [validation](../docs/VALIDATION.md), [architecture](../docs/ARCHITECTURE.md),
[NOTICE](../NOTICE) and [third-party notices](../THIRD_PARTY_NOTICES.md). Original
contributions follow the project Apache-2.0 grant; file-level third-party terms remain.
