"""Offline backup and restore for the canonical Compose Chroma named volume."""

from __future__ import annotations

import argparse
import logging
import os
import re
import shlex
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

if __package__:
    from .backup_common import (
        BackupValidationError,
        atomic_artifact_paths,
        load_and_verify_manifest,
        publish_artifact,
        utc_timestamp,
        write_manifest,
    )
else:
    from backup_common import (  # type: ignore[no-redef]
        BackupValidationError,
        atomic_artifact_paths,
        load_and_verify_manifest,
        publish_artifact,
        utc_timestamp,
        write_manifest,
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("chroma-volume")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"
DEFAULT_MAINTENANCE_FILE = PROJECT_ROOT / "scripts" / "docker-compose.maintenance.yml"
CANONICAL_VOLUME_NAME = "financial_chroma_data"
WRITER_SERVICES = frozenset({"backend", "agent-worker", "chromadb"})
SAFE_ARCHIVE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.tar\.gz$")


class VolumeOperationError(RuntimeError):
    """Raised when Docker refuses or fails a volume operation."""


def _base_compose_command(
    compose_file: str | Path,
    maintenance_file: str | Path | None = None,
) -> list[str]:
    compose_path = Path(compose_file).resolve()
    command = [
        "docker",
        "compose",
        "--project-directory",
        str(compose_path.parent),
        "-f",
        str(compose_path),
    ]
    if maintenance_file is not None:
        command.extend(["-f", str(Path(maintenance_file).resolve()), "--profile", "operations"])
    return command


def _run_command(
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            command,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise VolumeOperationError(f"Unable to execute Docker command: {exc}") from exc


def _require_success(
    process: subprocess.CompletedProcess[bytes],
    operation: str,
) -> None:
    if process.returncode == 0:
        return
    stderr = process.stderr.decode("utf-8", errors="replace").strip()
    raise VolumeOperationError(f"{operation} failed with exit code {process.returncode}: {stderr}")


def running_services(compose_file: str | Path) -> set[str]:
    command = [
        *_base_compose_command(compose_file),
        "ps",
        "--services",
        "--status",
        "running",
    ]
    process = _run_command(command)
    _require_success(process, "Compose service preflight")
    return {
        line.strip()
        for line in process.stdout.decode("utf-8", errors="replace").splitlines()
        if line.strip()
    }


def running_volume_containers(volume_name: str) -> set[str]:
    process = _run_command(
        [
            "docker",
            "ps",
            "--filter",
            f"volume={volume_name}",
            "--format",
            "{{.Names}}",
        ]
    )
    _require_success(process, "Docker volume attachment preflight")
    return {
        line.strip()
        for line in process.stdout.decode("utf-8", errors="replace").splitlines()
        if line.strip()
    }


def require_writers_stopped(
    compose_file: str | Path,
    volume_name: str = CANONICAL_VOLUME_NAME,
) -> None:
    active_writers = sorted(running_services(compose_file) & WRITER_SERVICES)
    if active_writers:
        raise VolumeOperationError(
            "Refusing an inconsistent Chroma volume operation while writers are running: "
            f"{', '.join(active_writers)}. Stop backend, agent-worker, and chromadb first."
        )
    attached_containers = sorted(running_volume_containers(volume_name))
    if attached_containers:
        raise VolumeOperationError(
            "Refusing a Chroma volume operation while the target volume is mounted by "
            f"running containers: {', '.join(attached_containers)}"
        )


def require_existing_volume(volume_name: str = CANONICAL_VOLUME_NAME) -> None:
    process = _run_command(["docker", "volume", "inspect", volume_name])
    _require_success(process, f"Docker volume preflight for {volume_name}")


def _maintenance_environment(backup_dir: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["BACKUP_DIR"] = str(backup_dir)
    return environment


def backup_chroma_volume(
    output_dir: str | Path,
    *,
    compose_file: str | Path = DEFAULT_COMPOSE_FILE,
    maintenance_file: str | Path = DEFAULT_MAINTENANCE_FILE,
    volume_name: str = CANONICAL_VOLUME_NAME,
) -> str:
    """Create an offline tar snapshot through a one-shot Compose container."""

    if volume_name != CANONICAL_VOLUME_NAME:
        raise ValueError(
            f"This Compose topology manages only the canonical volume {CANONICAL_VOLUME_NAME!r}"
        )
    require_writers_stopped(compose_file, volume_name)
    require_existing_volume(volume_name)

    filename = f"backup_chroma_volume_{utc_timestamp()}.tar.gz"
    temporary_path, final_path = atomic_artifact_paths(output_dir, filename)
    container_temporary_name = temporary_path.name
    if not SAFE_ARCHIVE_NAME.fullmatch(final_path.name):
        raise ValueError(f"Unsafe generated archive name: {final_path.name}")

    shell_command = (
        "set -eu; "
        "test -n \"$(ls -A /volume)\"; "
        f"tar -C /volume -czf /backup/{shlex.quote(container_temporary_name)} ."
    )
    command = [
        *_base_compose_command(compose_file, maintenance_file),
        "run",
        "--rm",
        "--no-deps",
        "chroma-volume-backup",
        shell_command,
    ]
    process = _run_command(
        command,
        environment=_maintenance_environment(final_path.parent),
    )
    if process.returncode != 0:
        temporary_path.unlink(missing_ok=True)
        _require_success(process, "Chroma volume backup")

    publish_artifact(temporary_path, final_path)
    try:
        _validate_tar_members(final_path)
        write_manifest(
            final_path,
            backup_type="chroma_volume",
            artifact_format="tar_gzip",
            source={
                "volume_name": volume_name,
                "compose_file": Path(compose_file).name,
                "consistency": "offline",
            },
            metadata={
                "required_stopped_services": sorted(WRITER_SERVICES),
                "restore_utility": "scripts/chroma_volume.py",
            },
        )
    except Exception:
        final_path.unlink(missing_ok=True)
        raise
    logger.info("Chroma volume backup created: %s", final_path)
    return str(final_path)


def _validate_tar_members(artifact: Path) -> None:
    try:
        with tarfile.open(artifact, "r:gz") as archive:
            members = archive.getmembers()
    except (OSError, tarfile.TarError) as exc:
        raise BackupValidationError(f"Chroma artifact is not a valid tar.gz archive: {exc}") from exc

    if not members:
        raise BackupValidationError("Chroma archive is empty")

    for member in members:
        member_path = PurePosixPath(member.name)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise BackupValidationError(f"Unsafe archive member path: {member.name!r}")
        if member.issym() or member.islnk():
            raise BackupValidationError(f"Archive links are not accepted: {member.name!r}")
        if not (member.isfile() or member.isdir()):
            raise BackupValidationError(f"Unsupported archive member type: {member.name!r}")


def restore_chroma_volume(
    artifact_path: str | Path,
    *,
    confirm_volume: str,
    manifest_path: str | Path | None = None,
    compose_file: str | Path = DEFAULT_COMPOSE_FILE,
    maintenance_file: str | Path = DEFAULT_MAINTENANCE_FILE,
    volume_name: str = CANONICAL_VOLUME_NAME,
    dry_run: bool = False,
) -> dict[str, object]:
    """Replace the canonical offline Chroma volume from a verified snapshot."""

    if volume_name != CANONICAL_VOLUME_NAME:
        raise ValueError(
            f"This Compose topology manages only the canonical volume {CANONICAL_VOLUME_NAME!r}"
        )
    if confirm_volume != volume_name:
        raise ValueError(
            f"Restore confirmation must exactly match the target volume {volume_name!r}"
        )

    artifact = Path(artifact_path).resolve()
    manifest = load_and_verify_manifest(
        artifact,
        expected_backup_type="chroma_volume",
        manifest_path=manifest_path,
    )
    source = manifest.get("source")
    if not isinstance(source, dict) or source.get("volume_name") != volume_name:
        raise BackupValidationError("Chroma manifest volume does not match the restore target")
    if manifest.get("format") != "tar_gzip":
        raise BackupValidationError("Chroma manifest format must be tar_gzip")
    if not SAFE_ARCHIVE_NAME.fullmatch(artifact.name):
        raise BackupValidationError(f"Unsafe Chroma archive filename: {artifact.name!r}")
    _validate_tar_members(artifact)
    require_writers_stopped(compose_file, volume_name)

    plan = {
        "artifact": str(artifact),
        "target_volume": volume_name,
        "checksum_verified": True,
        "archive_validated": True,
        "writers_stopped": True,
        "dry_run": dry_run,
    }
    if dry_run:
        logger.info("Chroma restore preflight passed; volume was not modified: %s", plan)
        return plan

    backup_dir = artifact.parent
    archive_name = shlex.quote(artifact.name)
    shell_command = (
        "set -eu; "
        f"tar -tzf /backup/{archive_name} >/dev/null; "
        "rm -rf /volume/* /volume/.[!.]* /volume/..?*; "
        f"tar -C /volume -xzf /backup/{archive_name}"
    )
    command = [
        *_base_compose_command(compose_file, maintenance_file),
        "run",
        "--rm",
        "--no-deps",
        "chroma-volume-restore",
        shell_command,
    ]
    process = _run_command(
        command,
        environment=_maintenance_environment(backup_dir),
    )
    _require_success(process, "Chroma volume restore")
    logger.info("Chroma volume restore completed: %s", volume_name)
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline Chroma Compose-volume operations")
    parser.add_argument("--compose-file", default=str(DEFAULT_COMPOSE_FILE))
    parser.add_argument("--maintenance-file", default=str(DEFAULT_MAINTENANCE_FILE))
    subparsers = parser.add_subparsers(dest="operation", required=True)

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--output-dir", required=True)

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--artifact", required=True)
    restore_parser.add_argument("--manifest")
    restore_parser.add_argument("--confirm-volume", required=True)
    restore_parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.operation == "backup":
            backup_chroma_volume(
                args.output_dir,
                compose_file=args.compose_file,
                maintenance_file=args.maintenance_file,
            )
        else:
            restore_chroma_volume(
                args.artifact,
                confirm_volume=args.confirm_volume,
                manifest_path=args.manifest,
                compose_file=args.compose_file,
                maintenance_file=args.maintenance_file,
                dry_run=args.dry_run,
            )
    except (BackupValidationError, OSError, ValueError, VolumeOperationError) as exc:
        logger.error("Chroma volume operation refused or failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
