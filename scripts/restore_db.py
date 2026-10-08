"""Checksum-gated PostgreSQL restore utility.

The restore target and confirmation phrase are always explicit. No database
command is executed until the artifact manifest, size, and SHA-256 checksum
have been validated.
"""

from __future__ import annotations

import argparse
import gzip
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO

if __package__:
    from .backup_common import (
        BackupValidationError,
        PostgresTarget,
        load_and_verify_manifest,
        parse_postgres_url,
    )
else:
    from backup_common import (  # type: ignore[no-redef]
        BackupValidationError,
        PostgresTarget,
        load_and_verify_manifest,
        parse_postgres_url,
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("restore")

POSTGRES_CUSTOM_FORMAT = "postgresql_custom"
POSTGRES_PLAIN_FORMATS = {"postgresql_plain", "postgresql_plain_gzip"}


class RestoreCommandError(RuntimeError):
    """Raised when a database restore process fails."""


def _compose_prefix(compose_file: str | Path) -> list[str]:
    compose_path = Path(compose_file).resolve()
    return [
        "docker",
        "compose",
        "--project-directory",
        str(compose_path.parent),
        "-f",
        str(compose_path),
    ]


def _restore_command(
    target: PostgresTarget,
    *,
    artifact_format: str,
    clean: bool,
    compose_service: str | None,
    compose_file: str | Path,
) -> list[str]:
    if artifact_format == POSTGRES_CUSTOM_FORMAT:
        executable = "pg_restore"
        arguments = [
            "-U",
            target.user,
            "-d",
            target.database,
            "--no-owner",
            "--no-acl",
            "--exit-on-error",
            "--single-transaction",
        ]
        if clean:
            arguments.extend(["--clean", "--if-exists"])
    elif artifact_format in POSTGRES_PLAIN_FORMATS:
        if clean:
            raise ValueError("--clean is supported only for PostgreSQL custom dumps")
        executable = "psql"
        arguments = [
            "-U",
            target.user,
            "-d",
            target.database,
            "-X",
            "--set=ON_ERROR_STOP=1",
            "--single-transaction",
        ]
    else:
        raise BackupValidationError(f"Unsupported PostgreSQL artifact format: {artifact_format!r}")

    if compose_service:
        return [
            *_compose_prefix(compose_file),
            "exec",
            "-T",
            compose_service,
            executable,
            *arguments,
        ]

    return [
        executable,
        "-h",
        target.host,
        "-p",
        str(target.port),
        *arguments,
    ]


def _artifact_stream(artifact: Path, artifact_format: str) -> BinaryIO:
    if artifact_format == "postgresql_plain_gzip":
        return gzip.open(artifact, "rb")
    return artifact.open("rb")


def restore_postgresql(
    artifact_path: str | Path,
    target: PostgresTarget,
    *,
    confirm_target: str,
    manifest_path: str | Path | None = None,
    clean: bool = False,
    compose_service: str | None = None,
    compose_file: str | Path = "docker-compose.yml",
    dry_run: bool = False,
) -> dict[str, object]:
    """Validate and restore a PostgreSQL backup.

    ``confirm_target`` must exactly equal the parsed target database name.
    """

    if confirm_target != target.database:
        raise ValueError(
            "Restore confirmation does not match the target database: "
            f"expected {target.database!r}"
        )

    artifact = Path(artifact_path).resolve()
    manifest = load_and_verify_manifest(
        artifact,
        expected_backup_type="postgresql",
        manifest_path=manifest_path,
    )
    artifact_format = manifest.get("format")
    if not isinstance(artifact_format, str):
        raise BackupValidationError("Backup manifest format is missing")

    command = _restore_command(
        target,
        artifact_format=artifact_format,
        clean=clean,
        compose_service=compose_service,
        compose_file=compose_file,
    )
    plan = {
        "artifact": str(artifact),
        "target_database": target.database,
        "target_host": compose_service or target.host,
        "tool": "pg_restore" if artifact_format == POSTGRES_CUSTOM_FORMAT else "psql",
        "clean": clean,
        "checksum_verified": True,
        "dry_run": dry_run,
    }
    if dry_run:
        logger.info("Restore preflight passed; no database command executed: %s", plan)
        return plan

    environment = os.environ.copy()
    if target.password and not compose_service:
        environment["PGPASSWORD"] = target.password

    try:
        with _artifact_stream(artifact, artifact_format) as source:
            process = subprocess.run(
                command,
                env=environment,
                stdin=source,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
    except OSError as exc:
        raise RestoreCommandError(f"Unable to execute PostgreSQL restore command: {exc}") from exc

    if process.returncode != 0:
        stderr = process.stderr.decode("utf-8", errors="replace").strip()
        raise RestoreCommandError(
            f"{plan['tool']} failed with exit code {process.returncode}: {stderr}"
        )

    logger.info(
        "PostgreSQL restore completed for target database %s using %s",
        target.database,
        plan["tool"],
    )
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Checksum-gated PostgreSQL restore")
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--manifest", help="Override the default <artifact>.manifest.json path")
    parser.add_argument(
        "--db-url",
        help="Explicit direct target URL; omitted only when --compose-service is used",
    )
    parser.add_argument("--db-name", default=os.getenv("POSTGRES_DB", "financial_rag"))
    parser.add_argument("--db-user", default=os.getenv("POSTGRES_USER", "financial"))
    parser.add_argument("--compose-service", help="Run restore inside this Compose service")
    parser.add_argument("--compose-file", default="docker-compose.yml")
    parser.add_argument(
        "--confirm-target",
        required=True,
        help="Must exactly match the target database name",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Drop matching objects before custom-format restore",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify checksum and print the restore plan without touching PostgreSQL",
    )
    return parser


def _target_from_args(args: argparse.Namespace) -> PostgresTarget:
    if args.db_url:
        return parse_postgres_url(args.db_url)
    if not args.compose_service:
        raise ValueError("Provide --db-url or --compose-service")
    return PostgresTarget(
        host=args.compose_service,
        port=5432,
        user=args.db_user,
        database=args.db_name,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        target = _target_from_args(args)
        restore_postgresql(
            args.artifact,
            target,
            confirm_target=args.confirm_target,
            manifest_path=args.manifest,
            clean=args.clean,
            compose_service=args.compose_service,
            compose_file=args.compose_file,
            dry_run=args.dry_run,
        )
    except (BackupValidationError, RestoreCommandError, OSError, ValueError) as exc:
        logger.error("Restore refused or failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
