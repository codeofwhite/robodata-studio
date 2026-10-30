# Third-party notices

RoboData Studio · by IPPLab provides original project code under [Apache-2.0](LICENSE).
Existing third-party notices and licenses remain applicable. Project-owner authorization
covers their original contributions, not third-party SDKs, models or assets.

## NVIDIA-attributed console source

`teleop/web_console/src/main.ts` retains its original identification:

Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: MIT

The MIT permission terms accompanying that identification are reproduced here:

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

The entry-file MIT identification does not cover the imported
@nvidia/omniverse-webrtc-streaming-library, whose lockfile entry specifies version
5.17.0 and SEE LICENSE IN LICENSE.txt. **No prebuilt console or copy of that library
is distributed in this source snapshot.** Users who build a console locally must
review their own applicable NVIDIA terms. This project does not grant rights to
the library or certify redistribution of a resulting build.

## External SDKs and assets

Isaac Sim / Isaac Lab and third-party robot/scene assets are external dependencies.
No SDK, Panda/FR3 USD, old asset archive, HDRI, texture library, private calibration
or model checkpoint is included. External materials retain their own terms. A
reference URL or an upstream dataset label is not a project license grant.
See [licenses and assets](docs/LICENSES_AND_ASSETS.md).

## Dependencies and snapshot provenance

The frontend and console package locks identify separate dependencies and their
license metadata; Python package declarations identify their runtime dependencies.
No node_modules or external Python environment is vendored. Build tools and runtime
libraries retain their own notices. Review the actual artifacts and applicable
license obligations if distributing built binaries, client bundles or added assets.

The source snapshot derives from robot-data-studio commit
13d3330e3802db5fcfddd02dd3c846a107418047 and gello-remote commit
b751a20e58f373e5415de511573fcff7225061be, followed by the integration and public-boundary
changes described in [validation](docs/VALIDATION.md). The copied control, safety,
protocol and simulator worker implementations retain their existing behavior.
Packaging, default capability exposure, metadata, documentation and selected test
fixtures changed. Public nominal camera profiles omit physical device serials.
The small favicon is newly authored geometric SVG for this project.

The IPPLab attribution does not imply endorsement by NVIDIA, Franka or other
third-party owners. [NOTICE](NOTICE) supplies project and upstream attribution.
