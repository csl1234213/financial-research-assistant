"""Shared primitives for verifiable backup artifacts.

The module is intentionally dependency-free so operators can run the backup
and restore scripts with the Python standard library available on the host.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlparse

MANIFEST_SCHEMA_VERSION = 1
SHA256_CHUNK_SIZE = 1024 * 1024


class BackupValidationError(ValueError):
    """Raised when an artifact or its manifest cannot be trusted."""


@dataclass(frozen=True)
class PostgresTarget:
    """A parsed PostgreSQL connection target.

    ``password`` is kept out of representations and backup manifests.
    """

    host: str
    port: int
    user: str
    database: str
    password: str = ""

    def __repr__(self) -> str:
        return (
            "PostgresTarget("
            f"host={self.host!r}, port={self.port!r}, user={self.user!r}, "
            f"database={self.database!r}, password=<redacted>)"
        )

    def public_metadata(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "database": self.database,
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_timestamp() -> str:
    return utc_now().strftime("%Y%m%d_%H%M%S_%f")


def parse_postgres_url(db_url: str) -> PostgresTarget:
    parsed = urlparse(db_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("Database URL must use the postgres or postgresql scheme")

    database = unquote(parsed.path.lstrip("/"))
    if not database:
        raise ValueError("Database URL must include a database name")
    if not parsed.hostname:
        raise ValueError("Database URL must include a host")

    return PostgresTarget(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=unquote(parsed.username or "postgres"),
        database=database,
        password=unquote(parsed.password or ""),
    )


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(SHA256_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_path_for(artifact_path: str | Path) -> Path:
    artifact = Path(artifact_path)
    return artifact.with_name(f"{artifact.name}.manifest.json")


def write_manifest(
    artifact_path: str | Path,
    *,
    backup_type: str,
    artifact_format: str,
    source: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
) -> Path:
    artifact = Path(artifact_path).resolve()
    if not artifact.is_file():
        raise FileNotFoundError(f"Backup artifact does not exist: {artifact}")

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": utc_now().isoformat(),
        "backup_type": backup_type,
        "format": artifact_format,
        "artifact": {
            "filename": artifact.name,
            "size_bytes": artifact.stat().st_size,
            "sha256": sha256_file(artifact),
        },
        "source": dict(source),
        "metadata": dict(metadata or {}),
    }

    manifest_path = manifest_path_for(artifact)
    temporary_path = manifest_path.with_name(f".{manifest_path.name}.partial")
    temporary_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, manifest_path)
    return manifest_path


def load_and_verify_manifest(
    artifact_path: str | Path,
    *,
    expected_backup_type: str | None = None,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    artifact = Path(artifact_path).resolve()
    if not artifact.is_file():
        raise BackupValidationError(f"Backup artifact does not exist: {artifact}")

    resolved_manifest = (
        Path(manifest_path).resolve()
        if manifest_path is not None
        else manifest_path_for(artifact).resolve()
    )
    if not resolved_manifest.is_file():
        raise BackupValidationError(f"Backup manifest does not exist: {resolved_manifest}")

    try:
        raw_manifest = json.loads(resolved_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupValidationError(f"Backup manifest is not valid JSON: {exc}") from exc

    if not isinstance(raw_manifest, dict):
        raise BackupValidationError("Backup manifest root must be an object")
    if raw_manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise BackupValidationError(
            f"Unsupported backup manifest schema: {raw_manifest.get('schema_version')!r}"
        )
    if expected_backup_type and raw_manifest.get("backup_type") != expected_backup_type:
        raise BackupValidationError(
            "Backup type mismatch: "
            f"expected {expected_backup_type!r}, got {raw_manifest.get('backup_type')!r}"
        )

    artifact_metadata = raw_manifest.get("artifact")
    if not isinstance(artifact_metadata, dict):
        raise BackupValidationError("Backup manifest artifact metadata is missing")
    if artifact_metadata.get("filename") != artifact.name:
        raise BackupValidationError("Backup manifest filename does not match the artifact")
    if artifact_metadata.get("size_bytes") != artifact.stat().st_size:
        raise BackupValidationError("Backup artifact size does not match the manifest")

    expected_sha256 = artifact_metadata.get("sha256")
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise BackupValidationError("Backup manifest SHA-256 is invalid")
    actual_sha256 = sha256_file(artifact)
    if not hmac.compare_digest(actual_sha256, expected_sha256.lower()):
        raise BackupValidationError("Backup artifact SHA-256 does not match the manifest")

    return raw_manifest


def atomic_artifact_paths(output_dir: str | Path, filename: str) -> tuple[Path, Path]:
    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    final_path = directory / filename
    temporary_path = directory / f".{filename}.partial"
    if final_path.exists() or manifest_path_for(final_path).exists():
        raise FileExistsError(f"Refusing to overwrite an existing backup: {final_path}")
    if temporary_path.exists():
        temporary_path.unlink()
    return temporary_path, final_path


def publish_artifact(temporary_path: str | Path, final_path: str | Path) -> Path:
    temporary = Path(temporary_path)
    final = Path(final_path)
    if not temporary.is_file():
        raise FileNotFoundError(f"Temporary backup artifact was not created: {temporary}")
    if final.exists():
        raise FileExistsError(f"Refusing to overwrite an existing backup: {final}")
    os.replace(temporary, final)
    return final
