"""Fail-closed validation helper for isolated restore drills.

This command validates artifacts before an operator restores them into an
explicitly isolated environment. It never targets the canonical Compose DB or
named volumes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_backup import main as verify_main


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("backup_dir")
    p.add_argument("--target", required=True)
    args = p.parse_args()
    if args.target in {"financial_postgres_data", "financial_uploads", "financial_chroma_prod", "financial-rag-prod"}:
        raise SystemExit("refusing canonical production target")
    old = sys.argv
    sys.argv = ["verify_backup", args.backup_dir]
    try:
        verify_main()
    finally:
        sys.argv = old
    root = Path(args.backup_dir).resolve()
    meta = json.loads((root / "manifest" / "backup_manifest.json").read_text())
    print(json.dumps({"status": "VALIDATED", "isolated_target": args.target, "backup_id": meta["backup_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
