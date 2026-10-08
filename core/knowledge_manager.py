from config import PDF_DIR
from core.knowledge_models import KnowledgeSource, KnowledgeStatistics
from document_loader import get_company


def get_documents():
    """
    返回知识库所有 PDF 文件
    """
    if not PDF_DIR.exists():
        return []

    return sorted([pdf.name for pdf in PDF_DIR.glob("*.pdf")])


def get_document_count():
    """
    返回 PDF 数量
    """
    return len(get_documents())


def refresh_registry():
    """
    当前版本直接刷新文件列表
    后续可扩展 JSON Registry
    """
    return get_documents()


def get_company_list():
    companies = set()

    for pdf in PDF_DIR.glob("*.pdf"):
        company = get_company(pdf.name)

        companies.add(company)

    return sorted(companies)


def get_sources():
    sources = []

    for pdf in PDF_DIR.glob("*.pdf"):
        stem = pdf.stem

        parts = stem.split("_")

        company = get_company(pdf.name)

        period = "_".join(parts[1:]) if len(parts) > 1 else "Unknown"

        document_id = stem.lower().replace(" ", "_").replace("-", "_")

        sources.append(
            KnowledgeSource(
                document_id=document_id,
                company=company,
                report_type="Financial Report",
                period=period,
                filename=pdf.name,
            )
        )

    return sources


def get_statistics(chunks):
    companies = len(get_company_list())

    reports = len(get_sources())

    return KnowledgeStatistics(
        companies=companies,
        reports=reports,
        chunks=len(chunks),
    )
