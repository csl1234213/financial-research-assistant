"""Idempotent public demo knowledge bootstrap.

Private tenant data must not suppress initialization of the intentionally
public demo corpus. The bootstrap checks the exact PDF sources shipped with
the application instead of treating any Chroma record as proof that demo
knowledge is ready.
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

CHROMA_DIR = os.environ.get("CHROMA_PATH", str(PROJECT_ROOT / "chroma_db"))
DEMO_PDF_DIR = Path(os.environ.get("DEMO_PDF_DIR", PROJECT_ROOT / "pdfs"))
PUBLIC_TENANT_ID = 0
EmbeddingProfile = tuple[str, str, str, str]


def _expected_demo_sources() -> set[str]:
    if not DEMO_PDF_DIR.is_dir():
        return set()
    return {path.name for path in DEMO_PDF_DIR.glob("*.pdf") if path.is_file()}


def _indexed_public_sources() -> set[str]:
    try:
        from storage.chroma_store import ChromaEmbeddingStore

        store = ChromaEmbeddingStore(persist_directory=CHROMA_DIR)
        rows = store.lexical_corpus(tenant_id=PUBLIC_TENANT_ID)
        return {
            str(row.metadata.get("source"))
            for row in rows
            if row.metadata.get("source")
        }
    except Exception:
        return set()


def _current_embedding_profile() -> EmbeddingProfile:
    from config import EMBEDDING_MODEL, EMBEDDING_MODEL_REVISION
    from document_loader import CHUNKER_VERSION, PARSER_VERSION

    return (
        EMBEDDING_MODEL,
        EMBEDDING_MODEL_REVISION or "unversioned",
        PARSER_VERSION,
        CHUNKER_VERSION,
    )


def _indexed_public_profiles() -> set[EmbeddingProfile]:
    try:
        from storage.chroma_store import ChromaEmbeddingStore

        store = ChromaEmbeddingStore(persist_directory=CHROMA_DIR)
        rows = store.lexical_corpus(tenant_id=PUBLIC_TENANT_ID)
        return {
            (
                str(row.metadata.get("embedding_model", "")),
                str(row.metadata.get("embedding_revision", "")),
                str(row.metadata.get("parser_version", "")),
                str(row.metadata.get("chunker_version", "")),
            )
            for row in rows
        }
    except Exception:
        return set()


def bootstrap() -> None:
    expected_sources = _expected_demo_sources()
    indexed_sources = _indexed_public_sources()
    indexed_profiles = _indexed_public_profiles()
    current_profile = _current_embedding_profile()

    if not expected_sources and not indexed_sources:
        print("[Bootstrap] No demo PDFs found; skipping public knowledge initialization.")
        return

    sources_match = expected_sources == indexed_sources
    profile_matches = (
        not expected_sources
        or indexed_profiles == {current_profile}
    )
    if sources_match and profile_matches:
        print("[Bootstrap] Public demo knowledge is current; skipping initialization.")
        return

    missing_sources = sorted(expected_sources - indexed_sources)
    stale_sources = sorted(indexed_sources - expected_sources)
    reasons: list[str] = []
    if missing_sources:
        reasons.append(f"missing sources: {', '.join(missing_sources)}")
    if stale_sources:
        reasons.append(f"stale sources: {', '.join(stale_sources)}")
    if not profile_matches:
        reasons.append("embedding/parser profile changed")
    print(
        "[Bootstrap] Initializing public demo knowledge; " + "; ".join(reasons)
    )
    from core.core_engine import refresh_knowledge_base

    refresh_knowledge_base()

    indexed_sources = _indexed_public_sources()
    indexed_profiles = _indexed_public_profiles()
    still_missing = expected_sources - indexed_sources
    still_stale = indexed_sources - expected_sources
    if still_missing or still_stale:
        raise RuntimeError(
            "Public demo knowledge bootstrap source mismatch; "
            f"missing={sorted(still_missing)}, stale={sorted(still_stale)}"
        )
    if expected_sources and indexed_profiles != {current_profile}:
        raise RuntimeError(
            "Public demo knowledge bootstrap retained an outdated "
            "embedding/parser profile"
        )

    print(
        "[Bootstrap] Done; "
        f"{len(indexed_sources)} public document sources are available."
    )


if __name__ == "__main__":
    bootstrap()
