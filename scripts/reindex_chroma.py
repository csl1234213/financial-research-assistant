"""Rebuild derived Chroma vectors from an isolated uploads directory."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from document_loader import get_company, get_quarter, load_pdf_chunks
from embedding import embed_passages, embedding_rows_to_lists, load_embedding_model
from retrieval.periods import extract_metrics, extract_periods
from storage.chroma_store import ChromaEmbeddingStore
from storage.vector_models import VectorDocument


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-index PDFs into an isolated Chroma service")
    parser.add_argument("uploads_dir")
    parser.add_argument("--tenant-id", type=int, default=0)
    args = parser.parse_args()
    root = Path(args.uploads_dir).resolve()
    if not root.is_dir():
        raise SystemExit("uploads directory does not exist")
    pdfs = sorted(root.rglob("*.pdf"))
    model = load_embedding_model()
    store = ChromaEmbeddingStore()
    store.create_collection("financial_reports")
    total = 0
    for pdf in pdfs:
        chunks = load_pdf_chunks(
            str(pdf),
            chunk_size=int(os.getenv("CHUNK_SIZE", "1000")),
            overlap=int(os.getenv("CHUNK_OVERLAP", "200")),
            ocr_enabled=False,
            ocr_languages=os.getenv("OCR_LANGUAGES", "eng+chi_sim"),
            ocr_dpi=int(os.getenv("OCR_DPI", "300")),
            ocr_min_text_chars=int(os.getenv("OCR_MIN_TEXT_CHARS", "80")),
        )
        embeddings = embedding_rows_to_lists(embed_passages(model, [chunk.text for chunk in chunks]))
        documents = [
            VectorDocument(
                document_id=pdf.stem,
                chunk_id=f"{pdf.stem}_{index}",
                company=get_company(pdf.name),
                content=chunk.text,
                embedding=embedding,
                metadata={
                    "source": pdf.name,
                    "tenant_id": args.tenant_id,
                    "page": chunk.page,
                    "collection": "financial_reports",
                    "quarter": get_quarter(pdf.name),
                    "periods": "|".join(extract_periods(chunk.text)),
                    "metrics": "|".join(extract_metrics(chunk.text)),
                    "table_context": chunk.table_context or "",
                    "source_authority": "public_filing" if args.tenant_id == 0 else "tenant_upload",
                },
            )
            for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True))
        ]
        store.add_documents(documents)
        total += len(documents)
    print(f"REINDEX_PDFS={len(pdfs)} REINDEX_CHUNKS={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
