# Licenses and external assets

Original project code that the contributors are authorized to license is provided
under [Apache-2.0](../LICENSE); see [NOTICE](../NOTICE) and
[third-party notices](../THIRD_PARTY_NOTICES.md). Existing upstream notices are retained.

## What is distributed

This source snapshot contains project source, nominal JSON profiles, independent
console integration source, a newly authored geometric SVG favicon, dependency
locks, and public documentation. It does not ship a prebuilt NVIDIA console, SDKs,
robot USD binaries, scene/texture archives, recorded data, calibration serials,
internal audit reports or historical scene screenshots.

The optional console downloads a separate NVIDIA library when the operator elects
to install/build it. Its source-file MIT header does not license that library. The
[NVIDIA Web SDK licensing page](https://docs-prod.omniverse.nvidia.com/ov-web-sdk/latest/common/NVIDIA_Omniverse_License_Agreement.html)
and [Isaac Sim WebRTC client terms](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/common/license-isaac-sim-webrtc-streaming-client.html)
cover distinct products/conditions; this project does not assert that a particular
redistribution grant applies to its npm dependency. Local builds are not approved
public distribution artifacts merely because they compile.

## Asset-source findings (no asset binaries included)

| Reference | Identified upstream statement | What remains the operator's responsibility |
| --- | --- | --- |
| ambientCG Marble006 | [CC0-1.0 asset policy](https://docs.ambientcg.com/license/) | Preserve source identity and verify acquired files |
| Poly Haven photo_studio_01 | [CC0 asset policy](https://polyhaven.com/license) | Keep asset identity separate from API/service terms |
| DexGarmentLab assets used by the predecessor Panda check | [Publisher declares Apache-2.0](https://huggingface.co/datasets/wayrise/DexGarmentLab/blob/main/README.md) | Match the actual archive/revision and any per-asset notices before repackaging |
| LeHome Challenge assets associated with earlier FR3 deployment | [Publisher declares Apache-2.0](https://huggingface.co/datasets/lehome/asset_challenge) | Match specific local files to the relevant upstream archive/revision; this snapshot supplies none |
| Isaac runtime and supplied content | [Additional software/materials terms](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/common/license-isaac-sim-additional.html) | Install independently under applicable terms; do not apply this project's Apache license to SDK content |

The current reference collector needs a compatible Panda USD supplied by the operator.
Scene files and SDK assets are not made freely redistributable by having been used
in a successful software test. Added assets, model weights and generated products
must carry their own provenance and applicable terms.
