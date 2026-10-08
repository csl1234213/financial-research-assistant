"""Storage-independent stage identifiers and lease contract."""

from dataclasses import dataclass

STAGES = ("PARSING", "QUALITY_CHECK", "BUILDING_FACTS", "BUILDING_TREE", "INDEXING")


class StageLeaseLost(PermissionError):
    """Completion/read rejected because a worker no longer owns the lease."""


@dataclass(frozen=True)
class StageLease:
    task_id: str
    token: str
    stage: str
    source_sha256: str
    document_id: int
    tenant_id: int
