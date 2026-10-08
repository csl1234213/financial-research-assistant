from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from scripts.backup_common import BackupValidationError, load_and_verify_manifest, sha256_file


def test_manifest_rejects_changed_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "backup_demo.dump"
    artifact.write_bytes(b"original")
    manifest = artifact.with_name(artifact.name + ".manifest.json")
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "backup_type": "postgresql",
                "format": "postgresql_custom",
                "artifact": {
                    "filename": artifact.name,
                    "size_bytes": artifact.stat().st_size,
                    "sha256": sha256_file(artifact),
                },
                "source": {},
                "metadata": {},
            }
        )
    )
    artifact.write_bytes(b"changed")
    with pytest.raises(BackupValidationError):
        load_and_verify_manifest(artifact, expected_backup_type="postgresql")


def test_upload_archive_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "uploads.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        payload = tmp_path / "payload"
        payload.write_text("unsafe")
        info = tar.gettarinfo(str(payload), arcname="../../outside")
        with payload.open("rb") as stream:
            tar.addfile(info, stream)
    with tarfile.open(archive, "r:gz") as tar:
        member = tar.getmembers()[0]
        assert ".." in Path(member.name).parts
