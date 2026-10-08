import os
import re
from dataclasses import replace
from pathlib import Path

from config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBEDDING_MODEL,
    EMBEDDING_MODEL_REVISION,
    OCR_DPI,
    OCR_ENABLED,
    OCR_LANGUAGES,
    OCR_MIN_TEXT_CHARS,
)
from core.financial_facts import FinancialDocumentContext, financial_facts_from_rows
from core.financial_metric_registry import MetricMappingStatus, normalize_financial_table_row
from core.financial_table_rows import (
    VerificationStatus,
    financial_table_rows_from_chunk,
    financial_table_rows_json,
)
from core.persistent_financial_facts import SQLFinancialFactRepository
from core.usage_events import ResourceType, UsageEvent
from document_loader import (
    get_company,
    get_document_company,
    get_document_period,
    get_quarter,
    load_document_chunks,
    load_pdf_chunks,
)
from embedding import (
    embed_passages,
    embedding_rows_to_lists,
    load_embedding_model,
)
from models.document import Document
from models.task import TaskStatus
from retrieval.periods import extract_metrics, extract_periods
from services.usage_service import record_usage
from storage.chroma_store import ChromaEmbeddingStore
from storage.database import SessionLocal
from storage.vector_models import VectorDocument
from tasks.repository import TaskRepository

_CHINESE_ANNUAL_SPAN = re.compile(
    r"(?P<year>20\d{2})\s*年\s*(?P<start>\d{1,2})\s*[—–-]\s*(?P<end>\d{1,2})\s*月"
)


def _explicit_fiscal_calendar(chunks) -> FinancialDocumentContext:
    """Use only a source-printed January–December statement heading.

    A filename or report-date hint cannot prove an income-statement duration.
    Conflicting printed calendars remain unknown instead of being guessed.
    """

    matches: list[tuple[int, int, int, str]] = []
    for chunk in chunks:
        section = str(chunk.section or "")
        heading = f"{section}\n{str(chunk.text or '')[:300]}"
        if not any(name in heading for name in ("利润表", "现金流量表", "所有者权益变动表")):
            continue
        for match in _CHINESE_ANNUAL_SPAN.finditer(str(chunk.text or "")[:600]):
            matches.append((
                int(match.group("year")),
                int(match.group("start")),
                int(match.group("end")),
                f"PDF page {chunk.page}: {match.group(0)}",
            ))
    if (
        not matches
        or len({(year, start, end) for year, start, end, _ in matches}) != 1
        or matches[0][1:3] != (1, 12)
    ):
        return FinancialDocumentContext()
    year, _, _, source = matches[0]
    return FinancialDocumentContext(
        fiscal_year_start=f"{year}-01-01",
        fiscal_year_end=f"{year}-12-31",
        fiscal_calendar_source=source,
    )


def _persist_verified_financial_facts(
    db,
    *,
    rows,
    document_id: int,
    tenant_id: int,
    company: str,
    filename: str,
    fiscal_context: FinancialDocumentContext | None = None,
) -> dict[str, object]:
    """Persist only parser-verified, registry-mapped rows for this document.

    The PDF/Chroma path still keeps PARTIAL and UNMAPPED table rows for
    diagnostics and retrieval. Only the strict P1.5 fact eligibility gate can
    create SQL facts; metadata hints or raw text never promote a row's trust.
    """

    rebound_rows = tuple(
        dict.fromkeys(
            replace(
                row,
                document_id=str(document_id),
                company=company or row.company,
                source=filename,
            )
            for row in rows
        )
    )
    verified_rows = tuple(
        row for row in rebound_rows if row.verification_status == VerificationStatus.VERIFIED
    )
    mapped_rows = tuple(
        row
        for row in verified_rows
        if normalize_financial_table_row(row).mapping_status
        in {MetricMappingStatus.EXACT, MetricMappingStatus.SUPPORTED}
    )
    facts = financial_facts_from_rows(
        rebound_rows,
        context=fiscal_context or FinancialDocumentContext(),
    )
    rejected = len(mapped_rows) - len(facts)
    counters = {
        "rows_seen": len(rebound_rows),
        "rows_verified": len(verified_rows),
        "rows_mapped": len(mapped_rows),
        "facts_rejected": rejected,
    }
    if not facts:
        return {
            **counters,
            "status": "NO_ELIGIBLE_FACTS",
            "facts_inserted": 0,
            "facts_unchanged": 0,
            "final_row_count": 0,
            "run_id": None,
        }

    result = SQLFinancialFactRepository(db, tenant_id=tenant_id).save_batch(
        facts,
        document_id=str(document_id),
        **counters,
    )
    return {
        **counters,
        "status": result.status,
        "facts_inserted": result.facts_inserted,
        "facts_unchanged": result.facts_unchanged,
        "final_row_count": result.final_row_count,
        "run_id": result.run_id,
    }


def _set_document_status(
    db,
    *,
    document_id: int | None,
    tenant_id: int,
    status: str,
    company: str | None = None,
    period: str | None = None,
    indexed_chunk_count: int | None = None,
) -> bool:
    """Update a document only when it belongs to the task's tenant."""
    if document_id is None:
        return True

    document = db.get(Document, document_id)
    if document is None or document.tenant_id != tenant_id:
        return False

    document.status = status
    if company is not None:
        document.company = company
    if period is not None:
        document.period = period
    if indexed_chunk_count is not None:
        document.indexed_chunk_count = indexed_chunk_count
    db.commit()
    return True


def process_document_task(task_public_id: str):
    db = SessionLocal()
    repo = TaskRepository(db)
    document_id: int | None = None
    tenant_id: int | None = None
    try:
        task = repo.get_task(task_public_id)
        if task is None:
            return

        tenant_id = task.tenant_id
        if tenant_id is None:
            repo.update_task(
                task_public_id,
                status=TaskStatus.FAILED,
                error_message="tenant_id is required for document processing",
            )
            return

        payload = task.payload
        file_path = payload.get("file_path")
        document_id = payload.get("document_id")
        content_sha256 = payload.get("content_sha256")

        if document_id is not None and not _set_document_status(
            db,
            document_id=document_id,
            tenant_id=tenant_id,
            status="processing",
        ):
            repo.update_task(
                task_public_id,
                status=TaskStatus.FAILED,
                error_message="Document does not belong to this tenant",
            )
            return

        if not file_path or not os.path.exists(file_path):
            repo.update_task(
                task_public_id,
                status=TaskStatus.FAILED,
                error_message=f"File not found: {file_path}",
            )
            _set_document_status(
                db,
                document_id=document_id,
                tenant_id=tenant_id,
                status="failed",
            )
            return

        if os.path.getsize(file_path) == 0:
            message = "PDF file is empty" if Path(file_path).suffix.casefold() == ".pdf" else "Document file is empty"
            raise ValueError(message)

        repo.update_task(task_public_id, progress=10)

        filename = os.path.basename(file_path)
        filename_company_hint = get_company(filename)
        filename_period_hint = get_quarter(filename)
        doc_id = (
            f"tenant_{tenant_id}_document_{document_id}"
            if document_id is not None
            else Path(filename).stem.lower()
            .replace(" ", "_")
            .replace("-", "_")
        )

        if Path(filename).suffix.casefold() == ".pdf":
            chunks = load_pdf_chunks(
                file_path,
                chunk_size=CHUNK_SIZE,
                overlap=CHUNK_OVERLAP,
                ocr_enabled=OCR_ENABLED,
                ocr_languages=OCR_LANGUAGES,
                ocr_dpi=OCR_DPI,
                ocr_min_text_chars=OCR_MIN_TEXT_CHARS,
                document_id=doc_id,
            )
        else:
            chunks = load_document_chunks(
                file_path,
                chunk_size=CHUNK_SIZE,
                overlap=CHUNK_OVERLAP,
            )
        if not chunks:
            message = (
                "PDF produced no indexable chunks"
                if Path(filename).suffix.casefold() == ".pdf"
                else "Document produced no indexable chunks"
            )
            raise ValueError(message)

        # Filing scope must be supported by opening document content. A name
        # or Q-number in the upload filename is kept only as diagnostic metadata.
        company = get_document_company(chunks, filename_hint=filename_company_hint)
        quarter = get_document_period(chunks)
        fiscal_context = _explicit_fiscal_calendar(chunks)
        # Discovered filings carry authoritative issuer/period metadata that
        # may not be recoverable from the parsed document body. Preserve it
        # through indexing so tenant/company retrieval filters remain aligned
        # with the discovery result and knowledge UI.
        if payload.get("source_type") in {"sec_edgar", "cninfo"}:
            discovered_company = payload.get("source_company")
            discovered_period = payload.get("source_report_date") or payload.get("source_filing_date")
            if isinstance(discovered_company, str) and discovered_company.strip():
                company = discovered_company.strip()
            if isinstance(discovered_period, str) and discovered_period.strip():
                quarter = discovered_period.strip()

        repo.update_task(task_public_id, progress=30)

        chunk_embeddings = embedding_rows_to_lists(
            embed_passages(
                load_embedding_model(),
                [chunk.text for chunk in chunks],
            )
        )
        if len(chunk_embeddings) != len(chunks):
            raise ValueError("Embedding model returned an unexpected vector count")

        repo.update_task(task_public_id, progress=50)

        store = ChromaEmbeddingStore()
        store.create_collection("financial_reports")

        chunk_identity = (
            content_sha256
            if isinstance(content_sha256, str) and content_sha256
            else doc_id
        )
        docs = []
        # Keep parser-native rows separately from the retrieval fallback rows.
        # Heuristic rows are useful search metadata, but are never promoted to
        # structured financial facts.
        verified_fact_candidates = []
        for chunk, embedding in zip(
            chunks,
            chunk_embeddings,
            strict=True,
        ):
            metadata = {
                "source": filename,
                "quarter": quarter,
                "filename_company_hint": filename_company_hint,
                "filename_period_hint": filename_period_hint,
                "periods": "|".join(extract_periods(chunk.text)),
                "metrics": "|".join(extract_metrics(chunk.text)),
                "collection": "financial_reports",
                "tenant_id": tenant_id,
                "section": chunk.section,
                "ocr_used": chunk.ocr_used,
                "parser_version": chunk.parser_version,
                "chunker_version": chunk.chunker_version,
                "table_context": chunk.table_context or "",
                "source_locator": chunk.source_locator or "",
                "page_label": chunk.source_locator or "",
                "content_type": chunk.content_type,
                "source_format": chunk.source_format,
                "source_authority": "tenant_upload",
                "embedding_model": EMBEDDING_MODEL,
                "embedding_revision": EMBEDDING_MODEL_REVISION or "unversioned",
            }
            native_financial_rows = tuple(chunk.financial_table_rows)
            verified_fact_candidates.extend(native_financial_rows)
            financial_rows = tuple(
                replace(
                    row,
                    document_id=doc_id,
                    company=company,
                    source=filename,
                )
                for row in native_financial_rows
            ) or financial_table_rows_from_chunk(
                content=chunk.text,
                content_type=chunk.content_type,
                document_id=doc_id,
                company=company,
                section=chunk.section,
                table_context=chunk.table_context or "",
                page=chunk.page,
                source=filename,
                source_locator=chunk.source_locator or "",
            )
            if financial_rows:
                # Chroma metadata accepts scalar values; serialize the typed
                # candidates without flattening away period, scope, or audit
                # status. P1.5 will consume only VERIFIED rows as facts.
                metadata["financial_table_rows_json"] = financial_table_rows_json(
                    financial_rows
                )
                if fiscal_context.fiscal_calendar_source:
                    metadata["fiscal_year_start"] = fiscal_context.fiscal_year_start
                    metadata["fiscal_year_end"] = fiscal_context.fiscal_year_end
                    metadata["fiscal_calendar_source"] = fiscal_context.fiscal_calendar_source
            if chunk.page > 0:
                metadata["page"] = chunk.page
            if isinstance(content_sha256, str) and content_sha256:
                metadata["content_sha256"] = content_sha256
            docs.append(
                VectorDocument(
                    document_id=doc_id,
                    chunk_id=(
                        f"tenant_{tenant_id}_{chunk_identity}_"
                        f"{chunk.chunk_index}"
                    ),
                    company=company,
                    content=chunk.text,
                    embedding=embedding,
                    metadata=metadata,
                )
            )

        repo.update_task(task_public_id, progress=80)

        # Replace this tenant-scoped document before writing. A retry after a
        # partial Chroma write cannot retain old trailing chunks when parser
        # or chunk boundaries changed.
        store.delete_document(doc_id, tenant_id=tenant_id)
        store.add_documents(docs)

        financial_fact_result: dict[str, object]
        if document_id is None:
            financial_fact_result = {
                "status": "SKIPPED_NO_RELATIONAL_DOCUMENT",
                "facts_inserted": 0,
            }
        elif not isinstance(content_sha256, str) or len(content_sha256) != 64:
            # P1.6 uses the content digest as immutable document-version
            # identity. Do not substitute filename, task id, or parser output.
            financial_fact_result = {
                "status": "SKIPPED_NO_CONTENT_SHA256",
                "facts_inserted": 0,
            }
        else:
            financial_fact_result = _persist_verified_financial_facts(
                db,
                rows=verified_fact_candidates,
                document_id=document_id,
                tenant_id=tenant_id,
                company=company,
                filename=filename,
                fiscal_context=fiscal_context,
            )

        repo.update_task(
            task_public_id,
            status=TaskStatus.SUCCESS,
            progress=100,
            result={
                "chunks": len(chunks),
                "company": company,
                "document_id": document_id,
                "financial_fact_ingestion": financial_fact_result,
            },
        )
        _set_document_status(
            db,
            document_id=document_id,
            tenant_id=tenant_id,
            status="indexed",
            company=company,
            period=quarter,
            indexed_chunk_count=len(chunks),
        )

        record_usage(
            tenant_id=tenant_id,
            event_type=UsageEvent.DOCUMENT_PROCESS,
            resource_type=ResourceType.DOCUMENT,
            quantity=1,
            metadata={
                "task_id": task_public_id,
                "document_id": document_id,
            },
            db=db,
        )

        record_usage(
            tenant_id=tenant_id,
            event_type=UsageEvent.EMBEDDING_GENERATION,
            resource_type=ResourceType.EMBEDDING,
            quantity=len(chunks),
            metadata={
                "task_id": task_public_id,
                "chunks": len(chunks),
                "document_id": document_id,
            },
            db=db,
        )

        record_usage(
            tenant_id=tenant_id,
            event_type=UsageEvent.VECTOR_INSERT,
            resource_type=ResourceType.VECTOR,
            quantity=len(chunks),
            metadata={
                "task_id": task_public_id,
                "chunks": len(chunks),
                "document_id": document_id,
            },
            db=db,
        )

    except Exception as e:
        repo.update_task(
            task_public_id,
            status=TaskStatus.FAILED,
            error_message=str(e),
        )
        if tenant_id is not None:
            _set_document_status(
                db,
                document_id=document_id,
                tenant_id=tenant_id,
                status="failed",
            )
    finally:
        db.close()
