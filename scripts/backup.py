"""Create a unified, checksum-verifiable local backup bundle.

The bundle is intentionally written outside the repository.  PostgreSQL is
dumped with the official pg_dump custom format; uploads and Chroma are read
from named volumes through short-lived read-only containers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPOSE = ROOT / "docker-compose.yml"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], *, cwd: Path | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        detail = result.stderr.decode(errors="replace").strip().splitlines()[-1:] or ["command failed"]
        raise RuntimeError(detail[0])


def _volume_tar(volume: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fra-backup-") as tmp:
        tmp_path = Path(tmp)
        _run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{volume}:/src:ro",
                "-v",
                f"{tmp_path}:/dst",
                "alpine:3.21",
                "tar",
                "-C",
                "/src",
                "-czf",
                "/dst/data.tar.gz",
                ".",
            ]
        )
        shutil.copy2(tmp_path / "data.tar.gz", destination)


def _uploads_manifest(archive: Path, output: Path) -> tuple[int, int, str]:
    entries: list[dict[str, object]] = []
    total = 0
    with tempfile.TemporaryDirectory(prefix="fra-upload-restore-") as tmp:
        root = Path(tmp)
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                target = (root / member.name).resolve()
                if not str(target).startswith(str(root.resolve())):
                    raise RuntimeError("unsafe upload archive path")
            tar.extractall(root)
        for file in sorted(p for p in root.rglob("*") if p.is_file()):
            relative = file.relative_to(root).as_posix()
            size = file.stat().st_size
            total += size
            entries.append({"relative_path": relative, "size": size, "sha256": _sha(file)})
    payload = {"schema_version": 1, "file_count": len(entries), "total_bytes": total, "files": entries}
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(entries), total, _sha(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Financial RAG backup bundle")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--compose-file", default=str(DEFAULT_COMPOSE))
    parser.add_argument("--git-commit", default="unknown")
    args = parser.parse_args()
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    postgres = out / "postgres" / "postgres.dump"
    uploads = out / "uploads" / "uploads.tar.gz"
    chroma = out / "chroma" / "chroma.tar.gz"
    uploads_manifest = out / "manifest" / "uploads_manifest.json"
    manifest = out / "manifest" / "backup_manifest.json"
    started = time.monotonic()
    postgres.parent.mkdir()
    uploads.parent.mkdir()
    chroma.parent.mkdir()
    manifest.parent.mkdir()

    pg_cmd = [
        "docker",
        "exec",
        "financial-postgres",
        "sh",
        "-lc",
        'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl',
    ]
    # Compose expands credentials inside the container; no secret is passed on the command line.
    with postgres.open("wb") as stream:
        result = subprocess.run(pg_cmd, cwd=ROOT, stdout=stream, stderr=subprocess.PIPE, shell=False)
    if result.returncode:
        raise RuntimeError("PostgreSQL pg_dump failed")

    _volume_tar("financial_uploads", uploads)
    file_count, total_bytes, uploads_manifest_sha = _uploads_manifest(uploads, uploads_manifest)
    _volume_tar("financial_chroma_prod", chroma)

    payload = {
        "schema_version": 1,
        "backup_id": out.name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "application_version": os.getenv("APP_VERSION", "8.1.0"),
        "git_commit": args.git_commit,
        "postgres_backup_filename": postgres.name,
        "postgres_backup_sha256": _sha(postgres),
        "uploads_file_count": file_count,
        "uploads_total_bytes": total_bytes,
        "uploads_manifest_sha256": uploads_manifest_sha,
        "chroma_backup_mode": "consistent_named_volume_snapshot",
        "chroma_artifact": chroma.name,
        "chroma_sha256": _sha(chroma),
        "artifacts": {
            "postgres": str(postgres.relative_to(out)),
            "uploads": str(uploads.relative_to(out)),
            "chroma": str(chroma.relative_to(out)),
        },
        "duration_seconds": round(time.monotonic() - started, 3),
    }
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PASS",
                "backup_id": out.name,
                "file_count": file_count,
                "total_bytes": total_bytes,
                "duration_seconds": payload["duration_seconds"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
