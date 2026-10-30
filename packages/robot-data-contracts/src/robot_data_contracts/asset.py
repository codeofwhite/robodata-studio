"""Immutable asset revisions, shared without importing a simulator."""
from __future__ import annotations

import json
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

AssetKind = Literal["scene", "material", "model", "config", "validation"]
PREFIXES = {"scene": "SCN", "material": "MAT", "model": "MDL", "config": "CFG", "validation": "VAL"}
ID_PATTERN = r"^(SCN|MAT|MDL|CFG|VAL)-[a-z0-9][a-z0-9_-]{0,119}$"


class AssetReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(pattern=ID_PATTERN)
    version: int = Field(ge=1)
    role: str = Field(min_length=1, max_length=64)


class AssetArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    path: str = Field(min_length=1, max_length=1024)
    role: str = Field(default="source", min_length=1, max_length=64)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    size_bytes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def safe_relative_path(self):
        if self.path.startswith(("/", "\\")) or "\\" in self.path or ":" in self.path:
            raise ValueError("artifact path must be a source-relative POSIX path")
        if any(part in ("", ".", "..") for part in self.path.split("/")):
            raise ValueError("artifact path contains an unsafe component")
        return self


class AssetDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(pattern=ID_PATTERN)
    kind: AssetKind
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=12000)
    tags: list[str] = Field(default_factory=list, max_length=40)
    engines: list[str] = Field(default_factory=list, max_length=20)
    data: dict[str, Any] = Field(default_factory=dict)
    references: list[AssetReference] = Field(default_factory=list, max_length=100)
    artifacts: list[AssetArtifact] = Field(default_factory=list, max_length=100)
    change_note: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_semantics(self):
        if not self.asset_id.startswith(PREFIXES[self.kind] + "-"):
            raise ValueError("asset ID prefix does not match kind")
        if not self.name.strip() or not self.change_note.strip():
            raise ValueError("name and change note cannot be blank")
        json.dumps(self.data, allow_nan=False)
        refs = [(r.asset_id, r.version, r.role) for r in self.references]
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate asset references")
        if self.kind == "validation":
            if self.data.get("outcome") not in {"passed", "failed", "unavailable"}:
                raise ValueError("validation requires a passed/failed/unavailable outcome")
            if not self.references or not self.artifacts:
                raise ValueError("validation requires exact-version targets and evidence artifacts")
            for key in ("engine_id", "evaluator_version", "scope"):
                if not isinstance(self.data.get(key), str) or not self.data[key].strip():
                    raise ValueError(f"validation requires {key}")
            if not isinstance(self.data.get("metrics"), dict):
                raise ValueError("validation requires a metrics object")
            if not isinstance(self.data.get("failed_gates"), list):
                raise ValueError("validation requires a failed_gates list")
        return self


class AssetVersion(AssetDraft):
    contract: Literal["robot_data_asset"] = "robot_data_asset"
    contract_version: Literal[1] = 1
    version: int = Field(ge=1)
    created_at: str
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def require_fingerprints(self):
        if any(a.sha256 is None or a.size_bytes is None for a in self.artifacts):
            raise ValueError("published artifacts require hashes and sizes")
        return self
