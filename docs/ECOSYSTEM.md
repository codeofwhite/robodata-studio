# Tools by IPPLab

The shared identity is **by IPPLab**. These names describe responsibilities; the
roadmap is not a list of already released packages.

| Tool | Scope | Status |
| --- | --- | --- |
| RoboData Studio | Collection sessions, QA, index, export orchestration | Initial public source snapshot |
| SceneKit | Scene/asset descriptions, configuration, provenance | Proposed series name; separate release not created |
| DataAugment | Provenance-tracked derivatives and augmentation jobs | Proposed series name; independent validation/release needed |
| GELLO Remote | Teleoperation input and safe worker execution | Bundled in teleop/ |
| Robot Data Contracts | Canonical records and shared interfaces | Bundled in packages/robot-data-contracts/ |

The lab workflow is scene configuration → collection → QA → optional augmentation →
export → consumer validation. Only verified stages should be advertised as supported.
Augmented data remains a derivative with parent identity and transformation provenance;
it does not overwrite raw Episodes. Scenes should be selected by versioned descriptions,
not personal workspace paths. Shared contracts provide the boundary between tools.

A future repository split should follow a useful installation/release boundary and
keep compatible imports, records and CLI entrypoints. This release does not rename
Python modules or automatically migrate the older projects and deployments.
