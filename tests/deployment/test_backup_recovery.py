from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from scripts import backup_common, backup_db, chroma_volume, restore_db


def _artifact_with_manifest(
    tmp_path: Path,
    *,
    name: str = "backup_financial_rag_20260726_000000.dump",
    backup_type: str = "postgresql",
    artifact_format: str = "postgresql_custom",
    source: dict[str, object] | None = None,
) -> Path:
    artifact = tmp_path / name
    artifact.write_bytes(b"verified-backup-content")
    backup_common.write_manifest(
        artifact,
        backup_type=backup_type,
        artifact_format=artifact_format,
        source=source or {"database": "financial_rag"},
    )
    return artifact


def test_manifest_round_trip_verifies_size_and_sha256(tmp_path: Path):
    artifact = _artifact_with_manifest(tmp_path)

    manifest = backup_common.load_and_verify_manifest(
        artifact,
        expected_backup_type="postgresql",
    )

    assert manifest["schema_version"] == 1
    assert manifest["artifact"]["filename"] == artifact.name
    assert manifest["artifact"]["size_bytes"] == artifact.stat().st_size
    assert len(manifest["artifact"]["sha256"]) == 64


def test_manifest_rejects_tampered_artifact(tmp_path: Path):
    artifact = _artifact_with_manifest(tmp_path)
    artifact.write_bytes(b"tampered")

    with pytest.raises(backup_common.BackupValidationError, match="does not match"):
        backup_common.load_and_verify_manifest(
            artifact,
            expected_backup_type="postgresql",
        )


def test_postgres_url_parser_redacts_password():
    target = backup_common.parse_postgres_url(
        "postgresql://financial:super%20secret@db.internal:5433/financial_rag"
    )

    assert target.password == "super secret"
    assert target.database == "financial_rag"
    assert "super secret" not in repr(target)
    assert "password" not in target.public_metadata()


def test_postgres_compose_backup_creates_custom_dump_and_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    observed_command: list[str] = []

    def fake_run(command, *, env, stdout, stderr, check):
        del env, stderr, check
        observed_command.extend(command)
        stdout.write(b"PGDMP-isolated-fixture")
        return subprocess.CompletedProcess(command, 0, stderr=b"")

    monkeypatch.setattr(backup_db.subprocess, "run", fake_run)

    artifact = Path(
        backup_db.backup_postgresql(
            "postgresql://financial:do-not-record@postgres:5432/financial_rag",
            str(tmp_path),
            compose_service="postgres",
            compose_file="docker-compose.yml",
        )
    )

    assert artifact.suffix == ".dump"
    assert "docker" == observed_command[0]
    assert "pg_dump" in observed_command
    assert "--format=custom" in observed_command
    manifest_text = backup_common.manifest_path_for(artifact).read_text(encoding="utf-8")
    assert "do-not-record" not in manifest_text
    assert backup_common.load_and_verify_manifest(artifact)["metadata"]["restore_tool"] == "pg_restore"


def test_failed_postgres_backup_does_not_publish_partial_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_run(command, *, env, stdout, stderr, check):
        del env, stdout, stderr, check
        return subprocess.CompletedProcess(command, 2, stderr=b"simulated pg_dump failure")

    monkeypatch.setattr(backup_db.subprocess, "run", fake_run)

    with pytest.raises(backup_db.BackupCommandError, match="simulated pg_dump failure"):
        backup_db.backup_postgresql(
            "postgresql://financial:secret@localhost/financial_rag",
            str(tmp_path),
        )

    assert list(tmp_path.iterdir()) == []


def test_backup_retention_never_removes_unrelated_files(tmp_path: Path):
    artifact = _artifact_with_manifest(tmp_path)
    unrelated = tmp_path / "backup_operator_notes.txt"
    unrelated.write_text("retain", encoding="utf-8")
    old_timestamp = 1
    os.utime(artifact, (old_timestamp, old_timestamp))
    os.utime(backup_common.manifest_path_for(artifact), (old_timestamp, old_timestamp))
    os.utime(unrelated, (old_timestamp, old_timestamp))

    backup_db.cleanup_old_backups(tmp_path, keep_days=1)

    assert not artifact.exists()
    assert not backup_common.manifest_path_for(artifact).exists()
    assert unrelated.read_text(encoding="utf-8") == "retain"


def test_postgres_restore_dry_run_validates_without_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    artifact = _artifact_with_manifest(tmp_path)
    target = backup_common.PostgresTarget(
        host="postgres",
        port=5432,
        user="financial",
        database="financial_rag",
    )

    def unexpected_run(*args, **kwargs):
        raise AssertionError(f"dry-run invoked subprocess: {args!r} {kwargs!r}")

    monkeypatch.setattr(restore_db.subprocess, "run", unexpected_run)
    plan = restore_db.restore_postgresql(
        artifact,
        target,
        confirm_target="financial_rag",
        compose_service="postgres",
        dry_run=True,
    )

    assert plan["checksum_verified"] is True
    assert plan["tool"] == "pg_restore"
    assert plan["target_database"] == "financial_rag"


def test_postgres_restore_requires_exact_target_confirmation(tmp_path: Path):
    artifact = _artifact_with_manifest(tmp_path)
    target = backup_common.PostgresTarget(
        host="postgres",
        port=5432,
        user="financial",
        database="financial_rag",
    )

    with pytest.raises(ValueError, match="does not match"):
        restore_db.restore_postgresql(
            artifact,
            target,
            confirm_target="another_database",
            compose_service="postgres",
            dry_run=True,
        )


def test_postgres_restore_rejects_tamper_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    artifact = _artifact_with_manifest(tmp_path)
    artifact.write_bytes(b"corrupt")
    target = backup_common.PostgresTarget(
        host="localhost",
        port=5432,
        user="financial",
        database="financial_rag",
    )

    def unexpected_run(*args, **kwargs):
        raise AssertionError(f"tampered restore invoked subprocess: {args!r} {kwargs!r}")

    monkeypatch.setattr(restore_db.subprocess, "run", unexpected_run)
    with pytest.raises(backup_common.BackupValidationError):
        restore_db.restore_postgresql(
            artifact,
            target,
            confirm_target="financial_rag",
        )


def _chroma_tar_with_manifest(tmp_path: Path, member_name: str = "index/data.bin") -> Path:
    artifact = tmp_path / "backup_chroma_volume_20260726_000000.tar.gz"
    content = b"chroma-test-data"
    tar_info = tarfile.TarInfo(member_name)
    tar_info.size = len(content)
    with tarfile.open(artifact, "w:gz") as archive:
        archive.addfile(tar_info, io.BytesIO(content))
    backup_common.write_manifest(
        artifact,
        backup_type="chroma_volume",
        artifact_format="tar_gzip",
        source={"volume_name": chroma_volume.CANONICAL_VOLUME_NAME},
    )
    return artifact


def test_chroma_backup_runs_restricted_compose_helper_and_writes_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    observed_commands: list[list[str]] = []

    def fake_run(command, *, environment=None):
        observed_commands.append(command)
        if command[:3] == ["docker", "volume", "inspect"]:
            return subprocess.CompletedProcess(command, 0, stdout=b"[]", stderr=b"")
        if "ps" in command:
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

        assert "chroma-volume-backup" in command
        assert environment is not None
        archive_name = command[-1].split("/backup/", maxsplit=1)[1].split(" ", maxsplit=1)[0]
        archive_path = Path(environment["BACKUP_DIR"]) / archive_name
        content = b"offline-volume-fixture"
        tar_info = tarfile.TarInfo("index/data.bin")
        tar_info.size = len(content)
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.addfile(tar_info, io.BytesIO(content))
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(chroma_volume, "_run_command", fake_run)

    artifact = Path(chroma_volume.backup_chroma_volume(tmp_path))

    manifest = backup_common.load_and_verify_manifest(
        artifact,
        expected_backup_type="chroma_volume",
    )
    assert manifest["source"]["volume_name"] == chroma_volume.CANONICAL_VOLUME_NAME
    assert any("chroma-volume-backup" in command for command in observed_commands)


def test_chroma_restore_dry_run_validates_archive_and_stopped_writers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    artifact = _chroma_tar_with_manifest(tmp_path)
    monkeypatch.setattr(chroma_volume, "running_services", lambda compose_file: set())
    monkeypatch.setattr(
        chroma_volume,
        "running_volume_containers",
        lambda volume_name: set(),
    )

    plan = chroma_volume.restore_chroma_volume(
        artifact,
        confirm_volume=chroma_volume.CANONICAL_VOLUME_NAME,
        dry_run=True,
    )

    assert plan["checksum_verified"] is True
    assert plan["archive_validated"] is True
    assert plan["writers_stopped"] is True


def test_chroma_restore_refuses_running_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    artifact = _chroma_tar_with_manifest(tmp_path)
    monkeypatch.setattr(chroma_volume, "running_services", lambda compose_file: {"backend"})

    with pytest.raises(chroma_volume.VolumeOperationError, match="backend"):
        chroma_volume.restore_chroma_volume(
            artifact,
            confirm_volume=chroma_volume.CANONICAL_VOLUME_NAME,
            dry_run=True,
        )


def test_chroma_restore_refuses_external_container_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    artifact = _chroma_tar_with_manifest(tmp_path)
    monkeypatch.setattr(chroma_volume, "running_services", lambda compose_file: set())
    monkeypatch.setattr(
        chroma_volume,
        "running_volume_containers",
        lambda volume_name: {"unmanaged-chroma-writer"},
    )

    with pytest.raises(chroma_volume.VolumeOperationError, match="unmanaged-chroma-writer"):
        chroma_volume.restore_chroma_volume(
            artifact,
            confirm_volume=chroma_volume.CANONICAL_VOLUME_NAME,
            dry_run=True,
        )


def test_chroma_restore_rejects_path_traversal_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    artifact = _chroma_tar_with_manifest(tmp_path, member_name="../escape")
    monkeypatch.setattr(chroma_volume, "running_services", lambda compose_file: set())
    monkeypatch.setattr(
        chroma_volume,
        "running_volume_containers",
        lambda volume_name: set(),
    )

    with pytest.raises(backup_common.BackupValidationError, match="Unsafe archive member"):
        chroma_volume.restore_chroma_volume(
            artifact,
            confirm_volume=chroma_volume.CANONICAL_VOLUME_NAME,
            dry_run=True,
        )


def test_maintenance_compose_mounts_backup_read_only_for_restore():
    maintenance = (
        Path(__file__).resolve().parents[2] / "scripts" / "docker-compose.maintenance.yml"
    ).read_text(encoding="utf-8")

    assert "chroma-volume-backup:" in maintenance
    assert "chroma-volume-restore:" in maintenance
    assert "source: chroma_data" in maintenance
    assert "network_mode: none" in maintenance
    restore_section = maintenance.split("chroma-volume-restore:", maxsplit=1)[1]
    assert "target: /backup\n        read_only: true" in restore_section


def test_manifest_is_json_for_external_auditors(tmp_path: Path):
    artifact = _artifact_with_manifest(tmp_path)

    parsed = json.loads(
        backup_common.manifest_path_for(artifact).read_text(encoding="utf-8")
    )

    assert parsed["backup_type"] == "postgresql"
