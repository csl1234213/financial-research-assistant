"""Create verifiable PostgreSQL, SQLite, and local Chroma backups.

PostgreSQL can be dumped either with host-installed ``pg_dump`` or through the
canonical Docker Compose ``postgres`` service. Every completed artifact gets a
sidecar JSON manifest containing its size and SHA-256 checksum.
"""

from __future__ import annotations

import argparse
import gzip
import logging
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

if __package__:
    from .backup_common import (
        PostgresTarget,
        atomic_artifact_paths,
        parse_postgres_url,
        publish_artifact,
        utc_now,
        utc_timestamp,
        write_manifest,
    )
else:
    from backup_common import (  # type: ignore[no-redef]
        PostgresTarget,
        atomic_artifact_paths,
        parse_postgres_url,
        publish_artifact,
        utc_now,
        utc_timestamp,
        write_manifest,
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("backup")

SUPPORTED_POSTGRES_FORMATS = {"custom", "plain"}
BACKUP_ARTIFACT_SUFFIXES = (".dump", ".sql", ".sql.gz", ".db", ".db.gz", ".tar.gz")


class BackupCommandError(RuntimeError):
    """Raised when an external backup command fails."""


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


def _postgres_dump_command(
    target: PostgresTarget,
    *,
    dump_format: str,
    compose_service: str | None,
    compose_file: str | Path,
) -> list[str]:
    if dump_format not in SUPPORTED_POSTGRES_FORMATS:
        raise ValueError(f"Unsupported PostgreSQL dump format: {dump_format}")

    if compose_service:
        command = [
            *_compose_prefix(compose_file),
            "exec",
            "-T",
            compose_service,
            "pg_dump",
            "-U",
            target.user,
            "-d",
            target.database,
        ]
    else:
        command = [
            "pg_dump",
            "-h",
            target.host,
            "-p",
            str(target.port),
            "-U",
            target.user,
            "-d",
            target.database,
        ]

    return [
        *command,
        f"--format={dump_format}",
        "--no-owner",
        "--no-acl",
    ]


def _run_postgres_dump(
    command: list[str],
    temporary_path: Path,
    *,
    password: str,
    gzip_output: bool,
) -> None:
    environment = os.environ.copy()
    if password and command[0] != "docker":
        environment["PGPASSWORD"] = password

    output_factory = gzip.open if gzip_output else Path.open
    open_kwargs = {"mode": "wb"}
    try:
        with output_factory(temporary_path, **open_kwargs) as output:
            process = subprocess.run(
                command,
                env=environment,
                stdout=output,
                stderr=subprocess.PIPE,
                check=False,
            )
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise BackupCommandError(f"Unable to execute PostgreSQL backup command: {exc}") from exc

    if process.returncode != 0:
        temporary_path.unlink(missing_ok=True)
        stderr = process.stderr.decode("utf-8", errors="replace").strip()
        raise BackupCommandError(f"pg_dump failed with exit code {process.returncode}: {stderr}")


def backup_postgresql_target(
    target: PostgresTarget,
    output_dir: str | Path,
    *,
    compress: bool = True,
    dump_format: str = "custom",
    compose_service: str | None = None,
    compose_file: str | Path = "docker-compose.yml",
) -> str:
    """Back up an already parsed PostgreSQL target and create its manifest."""

    if dump_format not in SUPPORTED_POSTGRES_FORMATS:
        raise ValueError(f"Unsupported PostgreSQL dump format: {dump_format}")

    timestamp = utc_timestamp()
    if dump_format == "custom":
        filename = f"backup_{target.database}_{timestamp}.dump"
        gzip_output = False
        artifact_format = "postgresql_custom"
    else:
        filename = f"backup_{target.database}_{timestamp}.sql"
        if compress:
            filename += ".gz"
        gzip_output = compress
        artifact_format = "postgresql_plain_gzip" if compress else "postgresql_plain"

    temporary_path, final_path = atomic_artifact_paths(output_dir, filename)
    command = _postgres_dump_command(
        target,
        dump_format=dump_format,
        compose_service=compose_service,
        compose_file=compose_file,
    )
    _run_postgres_dump(
        command,
        temporary_path,
        password=target.password,
        gzip_output=gzip_output,
    )
    publish_artifact(temporary_path, final_path)

    transport = "docker_compose" if compose_service else "direct"
    try:
        write_manifest(
            final_path,
            backup_type="postgresql",
            artifact_format=artifact_format,
            source={
                **target.public_metadata(),
                "transport": transport,
                "compose_service": compose_service,
            },
            metadata={
                "restore_tool": "pg_restore" if dump_format == "custom" else "psql",
            },
        )
    except Exception:
        final_path.unlink(missing_ok=True)
        raise

    size_mb = final_path.stat().st_size / (1024 * 1024)
    logger.info("PostgreSQL backup created: %s (%.2f MB)", final_path, size_mb)
    return str(final_path)


def backup_postgresql(
    db_url: str,
    output_dir: str,
    compress: bool = True,
    *,
    dump_format: str = "custom",
    compose_service: str | None = None,
    compose_file: str | Path = "docker-compose.yml",
) -> str:
    """Compatibility entry point using a PostgreSQL URL."""

    return backup_postgresql_target(
        parse_postgres_url(db_url),
        output_dir,
        compress=compress,
        dump_format=dump_format,
        compose_service=compose_service,
        compose_file=compose_file,
    )


def backup_sqlite(db_path: str, output_dir: str, compress: bool = True) -> str:
    source_path = Path(db_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {source_path}")

    timestamp = utc_timestamp()
    filename = f"backup_{source_path.stem}_{timestamp}.db"
    if compress:
        filename += ".gz"
    temporary_path, final_path = atomic_artifact_paths(output_dir, filename)

    if compress:
        with source_path.open("rb") as source, gzip.open(temporary_path, "wb") as destination:
            shutil.copyfileobj(source, destination)
    else:
        shutil.copy2(source_path, temporary_path)
    publish_artifact(temporary_path, final_path)

    try:
        write_manifest(
            final_path,
            backup_type="sqlite",
            artifact_format="sqlite_gzip" if compress else "sqlite",
            source={"filename": source_path.name},
        )
    except Exception:
        final_path.unlink(missing_ok=True)
        raise
    logger.info("SQLite backup created: %s", final_path)
    return str(final_path)


def backup_chromadb(chroma_path: str, output_dir: str) -> str:
    """Back up a local persistent Chroma directory.

    Network Chroma deployments backed by a Compose named volume must use
    ``scripts/chroma_volume.py`` so the writer can be stopped first.
    """

    source_path = Path(chroma_path).resolve()
    if not source_path.is_dir():
        raise FileNotFoundError(f"ChromaDB path not found: {source_path}")

    filename = f"backup_chroma_local_{utc_timestamp()}.tar.gz"
    temporary_path, final_path = atomic_artifact_paths(output_dir, filename)
    try:
        with tarfile.open(temporary_path, "w:gz") as archive:
            archive.add(source_path, arcname="chroma")
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    publish_artifact(temporary_path, final_path)

    try:
        write_manifest(
            final_path,
            backup_type="chroma_local",
            artifact_format="tar_gzip",
            source={"directory_name": source_path.name},
        )
    except Exception:
        final_path.unlink(missing_ok=True)
        raise
    logger.info("Local Chroma backup created: %s", final_path)
    return str(final_path)


def cleanup_old_backups(output_dir: str | Path, keep_days: int = 7) -> None:
    """Remove recognized backup artifacts and sidecars as retention units."""

    if keep_days < 1:
        raise ValueError("keep_days must be at least 1")
    directory = Path(output_dir)
    if not directory.is_dir():
        return

    cutoff = utc_now().timestamp() - keep_days * 86400
    removed = 0
    artifacts = [
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.name.startswith("backup_")
        and path.name.endswith(BACKUP_ARTIFACT_SUFFIXES)
        and not path.name.endswith(".manifest.json")
    ]
    for artifact in artifacts:
        if artifact.stat().st_mtime >= cutoff:
            continue
        sidecar = artifact.with_name(f"{artifact.name}.manifest.json")
        if sidecar.is_file():
            sidecar.unlink()
            removed += 1
            logger.info("Removed expired backup manifest: %s", sidecar.name)
        artifact.unlink()
        removed += 1
        logger.info("Removed expired backup artifact: %s", artifact.name)

    for path in directory.iterdir():
        is_orphan_manifest = (
            path.is_file()
            and path.name.startswith("backup_")
            and path.name.endswith(".manifest.json")
            and not path.with_name(path.name.removesuffix(".manifest.json")).exists()
        )
        is_partial_file = (
            path.is_file()
            and path.name.startswith(".backup_")
            and path.name.endswith(".partial")
        )
        if (is_orphan_manifest or is_partial_file) and path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
            logger.info("Removed expired backup file: %s", path.name)

    logger.info("Backup retention cleanup complete: %d files removed", removed)


def _compose_target(args: argparse.Namespace) -> PostgresTarget:
    if args.db_url.startswith(("postgres://", "postgresql://")):
        return parse_postgres_url(args.db_url)
    if args.db_url and not args.compose_service:
        raise ValueError(f"Unsupported database URL scheme: {args.db_url.split(':', 1)[0]!r}")
    if not args.compose_service:
        raise ValueError("Provide --db-url or --compose-service")
    return PostgresTarget(
        host=args.compose_service,
        port=5432,
        user=args.db_user,
        database=args.db_name,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Financial RAG verifiable backup utility")
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL", ""), help="Direct database URL")
    parser.add_argument("--db-name", default=os.getenv("POSTGRES_DB", "financial_rag"))
    parser.add_argument("--db-user", default=os.getenv("POSTGRES_USER", "financial"))
    parser.add_argument(
        "--compose-service",
        help="Run pg_dump in this Compose service instead of requiring a host pg_dump",
    )
    parser.add_argument("--compose-file", default="docker-compose.yml")
    parser.add_argument(
        "--postgres-format",
        choices=sorted(SUPPORTED_POSTGRES_FORMATS),
        default="custom",
        help="Custom format uses pg_restore; plain format uses psql",
    )
    parser.add_argument(
        "--chroma-path",
        default=os.getenv("CHROMA_PATH", "chroma_db"),
        help="Local Chroma directory; use chroma_volume.py for Compose Chroma",
    )
    parser.add_argument("--skip-local-chroma", action="store_true")
    parser.add_argument("--output-dir", default=os.getenv("BACKUP_DIR", "backup"))
    parser.add_argument("--no-compress", action="store_true", help="Disable gzip for plain SQL")
    parser.add_argument("--keep-days", type=int, default=7)
    parser.add_argument("--no-cleanup", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = {"status": "ok", "files": []}

    try:
        if args.compose_service:
            target = _compose_target(args)
            artifact = backup_postgresql_target(
                target,
                args.output_dir,
                compress=not args.no_compress,
                dump_format=args.postgres_format,
                compose_service=args.compose_service,
                compose_file=args.compose_file,
            )
            result["files"].append(artifact)
        elif args.db_url.startswith("sqlite://"):
            sqlite_path = args.db_url.replace("sqlite:///", "", 1)
            if not os.path.isabs(sqlite_path):
                sqlite_path = str(Path.cwd() / sqlite_path)
            result["files"].append(
                backup_sqlite(
                    sqlite_path,
                    args.output_dir,
                    compress=not args.no_compress,
                )
            )
        elif args.db_url:
            target = _compose_target(args)
            artifact = backup_postgresql_target(
                target,
                args.output_dir,
                compress=not args.no_compress,
                dump_format=args.postgres_format,
                compose_service=args.compose_service,
                compose_file=args.compose_file,
            )
            result["files"].append(artifact)

        chroma_path = Path(args.chroma_path)
        if not args.skip_local_chroma and chroma_path.is_dir():
            result["files"].append(backup_chromadb(str(chroma_path), args.output_dir))

        if not result["files"]:
            raise ValueError(
                "No backup source selected; provide --db-url/--compose-service or an existing --chroma-path"
            )

        if not args.no_cleanup:
            cleanup_old_backups(args.output_dir, args.keep_days)
    except (BackupCommandError, FileNotFoundError, OSError, tarfile.TarError, ValueError) as exc:
        logger.error("Backup failed: %s", exc)
        result["status"] = "failed"

    logger.info("Backup complete: %s", result)
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
