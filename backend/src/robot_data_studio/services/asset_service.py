from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from uuid import uuid4

from robot_data_contracts.asset import AssetArtifact, AssetDraft, AssetVersion, ID_PATTERN
from ..config import settings


class AssetConflict(ValueError):
    pass


class AssetNotFound(ValueError):
    pass


class AssetIntegrityError(ValueError):
    pass


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


@lru_cache(maxsize=4096)
def _digest(path: str, identity: tuple) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_digest(path: Path) -> str:
    stat = path.stat()
    return _digest(str(path), (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))


VIDEO_SUFFIXES = (".mp4", ".webm")


def is_video_artifact(role: str, path: str) -> bool:
    """True for artifacts a browser can play, i.e. media rather than a record of one.

    Roles are authored per artifact -- ``video``, ``video_front``, ``video_overview_4x``
    and so on -- so match the family instead of one exact name, which is what let the
    serving route and the cloth catalog disagree about the same records. The suffix
    check keeps ``video_provenance``, which is JSON, out of the video.
    """
    return PurePosixPath(path).suffix.lower() in VIDEO_SUFFIXES and (
        role == "video" or role.startswith("video_")
    )


class AssetRegistry:
    def __init__(self, root: Path | None = None, sources_file: Path | None = None):
        self.root = Path(root or settings.asset_root).resolve()
        self.sources_file = Path(sources_file or settings.asset_sources_file)

    def sources(self) -> dict:
        value = json.loads(self.sources_file.read_text())
        if value.get("schema_version") != 1 or not isinstance(value.get("sources"), dict):
            raise AssetIntegrityError("invalid asset source configuration")
        return value["sources"]

    def artifact_path(self, artifact: AssetArtifact) -> Path:
        source = self.sources().get(artifact.source_id)
        if not source:
            raise ValueError("unknown artifact source: " + artifact.source_id)
        root = Path(source["root"]).resolve()
        path = (root / artifact.path).resolve()
        if path == root or root not in path.parents:
            raise ValueError("artifact escapes its registered source root")
        if not path.is_file():
            raise AssetNotFound("artifact unavailable: " + artifact.source_id + "/" + artifact.path)
        return path

    def inspect_artifact(self, artifact: AssetArtifact) -> AssetArtifact:
        path = self.artifact_path(artifact)
        sha = file_digest(path)
        size = path.stat().st_size
        if artifact.sha256 is not None and artifact.sha256 != sha:
            raise AssetIntegrityError("artifact hash mismatch: " + artifact.path)
        if artifact.size_bytes is not None and artifact.size_bytes != size:
            raise AssetIntegrityError("artifact size mismatch: " + artifact.path)
        return artifact.model_copy(update={"sha256": sha, "size_bytes": size})

    @contextmanager
    def locked(self):
        import fcntl
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / ".lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _directory(self, asset_id: str) -> Path:
        if not re.fullmatch(ID_PATTERN, asset_id):
            raise ValueError("invalid asset ID")
        directory = self.root / asset_id
        if directory.resolve().parent != self.root:
            raise ValueError("unsafe registry directory")
        return directory

    def versions(self, asset_id: str) -> list[AssetVersion]:
        records = []
        for path in sorted(self._directory(asset_id).glob("v*.json")):
            record = AssetVersion.model_validate_json(path.read_bytes())
            if record.asset_id != asset_id or path.name != f"v{record.version:06d}.json":
                raise AssetIntegrityError("record identity mismatch: " + str(path))
            if fingerprint(AssetDraft.model_validate(record.model_dump(include=set(AssetDraft.model_fields))).model_dump(mode="json")) != record.content_sha256:
                raise AssetIntegrityError("record content was modified: " + str(path))
            records.append(record)
        return sorted(records, key=lambda r: r.version)

    def get(self, asset_id: str, version: int | None = None) -> AssetVersion:
        records = self.versions(asset_id)
        for record in reversed(records):
            if version is None or record.version == version:
                return record
        raise AssetNotFound(f"asset revision not found: {asset_id}@{version or 'latest'}")

    def all(self) -> list[AssetVersion]:
        records = []
        if self.root.exists():
            for directory in sorted(self.root.iterdir()):
                if directory.is_dir() and re.fullmatch(ID_PATTERN, directory.name):
                    records.extend(self.versions(directory.name))
        return records

    def publish(self, draft: AssetDraft, expected_version: int = 0, idempotent: bool = False) -> tuple[AssetVersion, bool]:
        # Checking and committing under one lock makes both version numbering and
        # reference resolution deterministic across concurrent publishers.
        with self.locked():
            artifacts = [self.inspect_artifact(a) for a in draft.artifacts]
            draft = AssetDraft.model_validate(draft.model_copy(update={"artifacts": artifacts}).model_dump())
            for ref in draft.references:
                self.get(ref.asset_id, ref.version)
            body = draft.model_dump(mode="json")
            sha = fingerprint(body)
            history = self.versions(draft.asset_id)
            latest = history[-1] if history else None
            if idempotent:
                for existing in reversed(history):
                    if existing.content_sha256 == sha:
                        return existing, False
            actual = latest.version if latest else 0
            if actual != expected_version:
                raise AssetConflict(f"revision conflict: expected {expected_version}, current {actual}")
            if latest and latest.kind != draft.kind:
                raise AssetConflict("asset kind cannot change")
            record = AssetVersion(**body, version=actual + 1, created_at=datetime.now(timezone.utc).isoformat(), content_sha256=sha)
            directory = self._directory(draft.asset_id)
            directory.mkdir(exist_ok=True)
            target = directory / f"v{record.version:06d}.json"
            temporary = directory / (".pending-" + uuid4().hex)
            try:
                with temporary.open("x", encoding="utf-8") as stream:
                    stream.write(record.model_dump_json(indent=2) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary, target)  # Exclusive creation; never overwrite a revision.
            finally:
                if temporary.exists():
                    temporary.unlink()
            return record, True

    def integrity(self, record: AssetVersion, records: dict | None = None, seen: set | None = None) -> dict:
        seen = set() if seen is None else seen
        key = (record.asset_id, record.version)
        if key in seen:
            return {"status": "stale", "issues": ["cyclic dependency"]}
        seen = seen | {key}
        issues = []
        for artifact in record.artifacts:
            try:
                self.inspect_artifact(artifact)
            except (OSError, ValueError) as error:
                issues.append(str(error))
        for ref in record.references:
            try:
                target = records.get((ref.asset_id, ref.version)) if records is not None else self.get(ref.asset_id, ref.version)
                if target is None:
                    raise AssetNotFound(f"missing reference {ref.asset_id}@v{ref.version}")
                result = self.integrity(target, records, seen)
                if result["status"] != "current":
                    issues.append(f"dependency {ref.asset_id}@v{ref.version}: " + "; ".join(result["issues"]))
            except (OSError, ValueError) as error:
                issues.append(str(error))
        return {"status": "stale" if issues else "current", "issues": list(dict.fromkeys(issues))}

    def catalog(self, q="", kind="", engine="", outcome="", integrity="", offset=0, limit=100) -> dict:
        records = self.all()
        lookup = {(r.asset_id, r.version): r for r in records}
        latest = {}
        for record in records:
            latest[record.asset_id] = record
        items = []
        wanted_kinds = {value for value in kind.split(",") if value}
        for record in latest.values():
            if wanted_kinds and record.kind not in wanted_kinds:
                continue
            if engine and engine not in record.engines:
                continue
            if outcome and record.data.get("outcome", "") != outcome:
                continue
            haystack = " ".join([record.asset_id, record.name, record.description, *record.tags, *record.engines]).casefold()
            if q and q.casefold() not in haystack:
                continue
            status = self.integrity(record, lookup)
            if integrity and status["status"] != integrity:
                continue
            body = record.model_dump(mode="json")
            body["integrity"] = status
            items.append(body)
        items.sort(key=lambda x: (x["kind"], x["asset_id"]))
        counts = {kind: sum(r.kind == kind for r in latest.values()) for kind in ("scene", "material", "model", "config", "validation")}
        return {"items": items[offset:offset + limit], "total": len(items), "offset": offset, "limit": limit, "counts": counts, "revision_count": len(records)}

    def detail(self, asset_id: str, version: int | None = None) -> dict:
        record = self.get(asset_id, version)
        records = self.all()
        lookup = {(r.asset_id, r.version): r for r in records}
        incoming = [r for r in records if any(x.asset_id == record.asset_id and x.version == record.version for x in r.references)]
        return {"record": record.model_dump(mode="json"), "integrity": self.integrity(record, lookup),
                "versions": [{"version": r.version, "created_at": r.created_at, "change_note": r.change_note, "content_sha256": r.content_sha256} for r in self.versions(asset_id)],
                "referenced_by": [{"asset_id": r.asset_id, "version": r.version, "kind": r.kind, "name": r.name, "outcome": r.data.get("outcome")} for r in incoming]}
