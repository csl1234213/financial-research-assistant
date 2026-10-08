"""Verify a unified backup bundle without connecting to production services."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("backup_dir")
    args = p.parse_args()
    root = Path(args.backup_dir).resolve()
    manifest = json.loads((root / "manifest" / "backup_manifest.json").read_text())
    for rel, expected in [
        (manifest["artifacts"]["postgres"], manifest["postgres_backup_sha256"]),
        (manifest["artifacts"]["uploads"], None),
        (manifest["artifacts"]["chroma"], manifest["chroma_sha256"]),
    ]:
        path = root / rel
        if not path.is_file():
            raise SystemExit(f"missing artifact: {rel}")
        if expected and sha(path) != expected:
            raise SystemExit(f"checksum mismatch: {rel}")
    upload_manifest = json.loads((root / "manifest" / "uploads_manifest.json").read_text())
    with tarfile.open(root / manifest["artifacts"]["uploads"], "r:gz") as tar:
        names = {m.name for m in tar.getmembers() if m.isfile()}
    if upload_manifest["file_count"] != len(names):
        raise SystemExit("upload manifest count mismatch")
    with tarfile.open(root / manifest["artifacts"]["chroma"], "r:gz") as tar:
        if not tar.getmembers():
            raise SystemExit("empty chroma artifact")
    print(json.dumps({"status": "PASS", "backup_id": manifest["backup_id"], "uploads": upload_manifest["file_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
