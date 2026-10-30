from __future__ import annotations

import importlib.metadata
import platform
import subprocess
import sys
from pathlib import Path

from .episode import SoftwareProvenanceV1


def collect_software_provenance(*, engine_id: str, engine_version: str, worker_id: str,
                                git_roots: dict[str, str | Path] | None = None,
                                packages: tuple[str, ...] = ()) -> SoftwareProvenanceV1:
    revisions: dict[str, str] = {}
    for name, root in (git_roots or {}).items():
        try:
            result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                                    text=True, timeout=2, check=True)
            revisions[name] = result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            revisions[name] = "unknown"
    dependencies: dict[str, str] = {}
    for package in packages:
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = "not-installed-as-distribution"
    return SoftwareProvenanceV1(
        python_version=sys.version.split()[0], platform=platform.platform(), engine_id=engine_id,
        engine_version=engine_version, worker_id=worker_id, git_revisions=revisions,
        dependencies=dependencies,
    )
