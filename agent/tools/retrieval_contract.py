"""Typed, tenant-scoped contract for the retrieval tool.

The tool layer deliberately does not import a vector store or a retriever.  A
trusted server-side composition root supplies an adapter instead.  This keeps
tool requests from turning a user-provided parameter into an executable
callable or an unscoped data access path.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeAlias, runtime_checkable

MAX_QUERY_LENGTH = 8_000
MAX_TOP_K = 20
DEFAULT_TOP_K = 5
RETRIEVAL_ADAPTER_PARAMETER = "retrieval_adapter"

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
EvidenceInput: TypeAlias = "RetrievalEvidence | Mapping[str, Any] | object"


class RetrievalContractError(ValueError):
    """Raised when a retrieval request or adapter result violates the contract."""


@dataclass(frozen=True, slots=True)
class RetrievalRequest:
    """The only request shape made available to a trusted retrieval adapter."""

    query: str
    tenant_id: int
    top_k: int = DEFAULT_TOP_K
    company: str | None = None
    document_ids: tuple[str, ...] = ()
    filters: Mapping[str, JsonValue] = field(default_factory=dict)
    include_public: bool = False

    @classmethod
    def from_context(cls, context: Any) -> "RetrievalRequest":
        """Build a request from a server-created :class:`ToolContext`.

        ``tenant_id`` must be set on the typed context, not inferred from an
        untrusted parameters mapping.  If a caller also provides it in
        ``parameters`` it must agree, which catches accidental scope mixing.
        """

        parameters = getattr(context, "parameters", None)
        if not isinstance(parameters, Mapping):
            raise RetrievalContractError("tool context parameters must be a mapping")

        tenant_id = getattr(context, "tenant_id", None)
        _validate_tenant_id(tenant_id)
        if "tenant_id" in parameters and parameters["tenant_id"] != tenant_id:
            raise RetrievalContractError("tenant_id parameter does not match the trusted context scope")

        query = parameters.get("query")
        if not isinstance(query, str) or not query.strip():
            raise RetrievalContractError("query is required")
        query = query.strip()
        if len(query) > MAX_QUERY_LENGTH:
            raise RetrievalContractError(f"query must not exceed {MAX_QUERY_LENGTH} characters")

        top_k = parameters.get("top_k", DEFAULT_TOP_K)
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
            raise RetrievalContractError(f"top_k must be an integer between 1 and {MAX_TOP_K}")

        company = parameters.get("company")
        if company is not None and (not isinstance(company, str) or not company.strip()):
            raise RetrievalContractError("company must be a non-empty string when provided")

        document_ids = _normalise_document_ids(parameters.get("document_ids"))
        filters = _normalise_filters(parameters.get("filters", {}))
        include_public = parameters.get("include_public", False)
        if not isinstance(include_public, bool):
            raise RetrievalContractError("include_public must be a boolean")

        return cls(
            query=query,
            tenant_id=tenant_id,
            top_k=top_k,
            company=company.strip() if company else None,
            document_ids=document_ids,
            filters=filters,
            include_public=include_public,
        )


@dataclass(frozen=True, slots=True)
class RetrievalEvidence:
    """A normalized evidence item returned by a trusted retrieval adapter."""

    content: str
    source_filename: str
    similarity_score: float | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    page: int | str | None = None
    company: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: EvidenceInput) -> "RetrievalEvidence":
        """Normalize a mapping or evidence-like trusted adapter result."""

        if isinstance(value, cls):
            return value

        if isinstance(value, Mapping):
            data: Mapping[str, Any] = value
        else:
            data = {
                "content": getattr(value, "content", None),
                "source": getattr(value, "source", None),
                "score": getattr(value, "score", None),
                "confidence": getattr(value, "confidence", None),
                "document_id": getattr(value, "document_id", None),
                "chunk_id": getattr(value, "chunk_id", None),
                "page": getattr(value, "page", None),
                "company": getattr(value, "company", None),
                "metadata": getattr(value, "metadata", None),
            }

        metadata = data.get("metadata", {})
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, Mapping):
            raise RetrievalContractError("retrieval evidence metadata must be a mapping")

        content = data.get("content", data.get("snippet", data.get("text")))
        if not isinstance(content, str) or not content.strip():
            raise RetrievalContractError("retrieval evidence requires non-empty content")

        source = data.get("source_filename", data.get("source", metadata.get("source")))
        if not isinstance(source, str) or not source.strip():
            raise RetrievalContractError("retrieval evidence requires a source filename")

        score = data.get("similarity_score")
        if score is None:
            score = data.get("score")
        if score is None:
            score = data.get("confidence")
        if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))):
            raise RetrievalContractError("retrieval evidence score must be numeric when provided")

        page = data.get("page", metadata.get("page"))
        if page is not None and (isinstance(page, bool) or not isinstance(page, (int, str))):
            raise RetrievalContractError("retrieval evidence page must be an integer or string when provided")

        return cls(
            content=content.strip(),
            source_filename=source.strip(),
            similarity_score=float(score) if score is not None else None,
            document_id=_optional_string(data.get("document_id", metadata.get("document_id")), "document_id"),
            chunk_id=_optional_string(data.get("chunk_id", metadata.get("chunk_id")), "chunk_id"),
            page=page,
            company=_optional_string(data.get("company", metadata.get("company")), "company"),
            metadata=_json_mapping(metadata),
        )

    def as_dict(self, *, rank: int) -> dict[str, JsonValue]:
        return {
            "rank": rank,
            "content": self.content,
            "source_filename": self.source_filename,
            "similarity_score": self.similarity_score,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "page": self.page,
            "company": self.company,
            "metadata": dict(self.metadata),
        }

    def citation(self, *, rank: int) -> dict[str, JsonValue]:
        citation: dict[str, JsonValue] = {
            "rank": rank,
            "source_filename": self.source_filename,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "page": self.page,
            "similarity_score": self.similarity_score,
        }
        for metadata_key in ("source_locator", "page_label", "content_type", "source_format"):
            value = self.metadata.get(metadata_key)
            if isinstance(value, (str, int, float, bool)):
                citation[metadata_key] = value
        return citation


@runtime_checkable
class RetrievalAdapter(Protocol):
    """Protocol implemented by server-owned retrieval adapters."""

    def retrieve(self, request: RetrievalRequest) -> Iterable[EvidenceInput]: ...


RetrievalCallable: TypeAlias = Callable[[RetrievalRequest], Iterable[EvidenceInput]]


class TrustedRetrievalAdapter:
    """Explicit trust boundary around a server-injected retrieval dependency.

    A raw callable can be wrapped only by trusted application composition code
    (for example, the runtime wiring).  Tool contexts accept this wrapper, not
    arbitrary callable values supplied through request parameters.
    """

    def __init__(
        self,
        retriever: RetrievalAdapter | RetrievalCallable,
        *,
        name: str = "trusted_retriever",
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("trusted retrieval adapter name must be a non-empty string")
        if callable(retriever):
            self._retrieve: RetrievalCallable = retriever
        elif isinstance(retriever, RetrievalAdapter):
            self._retrieve = retriever.retrieve
        else:
            raise TypeError("retriever must be a callable or implement retrieve(request)")
        self.name = name.strip()

    def retrieve(self, request: RetrievalRequest) -> Iterable[EvidenceInput]:
        return self._retrieve(request)


def trusted_retrieval_adapter(
    retriever: RetrievalAdapter | RetrievalCallable,
    *,
    name: str = "trusted_retriever",
) -> TrustedRetrievalAdapter:
    """Build the explicit adapter required for context-based execution."""

    return TrustedRetrievalAdapter(retriever, name=name)


def adapter_from_context(context: Any) -> TrustedRetrievalAdapter | None:
    """Return only an explicitly wrapped, server-injected adapter."""

    parameters = getattr(context, "parameters", {})
    if not isinstance(parameters, Mapping):
        return None
    adapter = parameters.get(RETRIEVAL_ADAPTER_PARAMETER)
    return adapter if isinstance(adapter, TrustedRetrievalAdapter) else None


def normalise_evidence(values: Iterable[EvidenceInput]) -> list[RetrievalEvidence]:
    """Convert adapter results into JSON-safe evidence records."""

    if isinstance(values, (str, bytes, Mapping)):
        raise RetrievalContractError("retrieval adapter must return an iterable of evidence records")
    try:
        return [RetrievalEvidence.from_value(item) for item in values]
    except TypeError as exc:
        raise RetrievalContractError("retrieval adapter must return an iterable of evidence records") from exc


def _validate_tenant_id(tenant_id: Any) -> None:
    if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id < 0:
        raise RetrievalContractError("a non-negative tenant_id is required on the trusted tool context")


def _normalise_document_ids(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values: Sequence[Any] = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = value
    else:
        raise RetrievalContractError("document_ids must be a string or a sequence of strings")

    normalized: list[str] = []
    for document_id in values:
        if not isinstance(document_id, str) or not document_id.strip():
            raise RetrievalContractError("document_ids must contain non-empty strings")
        normalized.append(document_id.strip())
    return tuple(normalized)


def _normalise_filters(value: Any) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise RetrievalContractError("filters must be a mapping")
    return _json_mapping(value)


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RetrievalContractError(f"{field_name} must be a non-empty string when provided")
    return value.strip()


def _json_mapping(value: Mapping[Any, Any]) -> dict[str, JsonValue]:
    normalized: dict[str, JsonValue] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise RetrievalContractError("metadata and filter keys must be strings")
        normalized[key] = _json_value(item)
    return normalized


def _json_value(value: Any) -> JsonValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return _json_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_json_value(item) for item in value]
    raise RetrievalContractError("metadata and filters must contain JSON-compatible values")
