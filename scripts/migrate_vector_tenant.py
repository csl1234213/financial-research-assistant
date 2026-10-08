import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import chromadb  # noqa: E402

from config.security import DEFAULT_MIGRATION_TENANT  # noqa: E402


def scan_collections(client: chromadb.PersistentClient):
    collections = client.list_collections()
    total_chunks = 0
    missing_tenant = 0
    collection_stats = []

    for c in collections:
        count = c.count()
        if count == 0:
            continue
        total_chunks += count

        existing = c.get(include=["metadatas"])
        missing = 0
        for meta in existing["metadatas"]:
            if meta is None or "tenant_id" not in meta:
                missing += 1

        missing_tenant += missing
        collection_stats.append({
            "name": c.name,
            "total": count,
            "missing_tenant_id": missing,
        })

    return {
        "total_chunks": total_chunks,
        "missing_tenant_id": missing_tenant,
        "collections": collection_stats,
    }


def migrate_collection(
    collection,
    tenant_id: str = DEFAULT_MIGRATION_TENANT,
):
    data = collection.get(include=["metadatas"])
    migrated = 0

    for i, meta in enumerate(data["metadatas"]):
        if meta is None:
            meta = {}
        if "tenant_id" not in meta:
            meta["tenant_id"] = tenant_id
            collection.update(
                ids=[data["ids"][i]],
                metadatas=[meta],
            )
            migrated += 1

    return migrated


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Migrate vector chunks to add tenant_id")
    parser.add_argument(
        "--persist-dir",
        default="./chroma_db",
        help="ChromaDB persist directory (default: ./chroma_db)",
    )
    parser.add_argument(
        "--tenant-id",
        default=DEFAULT_MIGRATION_TENANT,
        help=f"Default tenant_id for unassigned chunks (default: {DEFAULT_MIGRATION_TENANT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan only, do not apply changes",
    )
    args = parser.parse_args()

    client = chromadb.PersistentClient(path=args.persist_dir)

    print("=" * 60)
    print("  VECTOR MIGRATION REPORT")
    print("=" * 60)

    stats = scan_collections(client)

    print("\n  Before Migration:")
    print(f"  - Total chunks:      {stats['total_chunks']}")
    print(f"  - Missing tenant_id: {stats['missing_tenant_id']}")
    print()

    if stats["collections"]:
        for col in stats["collections"]:
            print(f"    Collection: {col['name']}")
            print(f"      Total:            {col['total']}")
            print(f"      Missing tenant_id: {col['missing_tenant_id']}")

    if args.dry_run:
        print("\n  [DRY RUN] No changes applied.")
        return

    collections = client.list_collections()
    total_migrated = 0

    print("\n  After Migration:")
    for c in collections:
        if c.count() == 0:
            continue
        migrated = migrate_collection(c, tenant_id=args.tenant_id)
        total_migrated += migrated
        if migrated > 0:
            print(f"    Collection '{c.name}': {migrated} chunks migrated")

    print(f"\n  - Total migrated:    {total_migrated}")
    print(f"  - Tenant ID:         {args.tenant_id}")
    print("=" * 60)


if __name__ == "__main__":
    main()
