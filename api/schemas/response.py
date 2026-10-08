from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class _ExtensibleResponseModel(BaseModel):
    """Typed public fields while preserving compatible runtime metadata."""

    model_config = ConfigDict(extra="allow")


class Citation(_ExtensibleResponseModel):
    rank: int
    source: str
    chunk_id: str
    similarity: Optional[float]
    preview: str


class Reasoning(_ExtensibleResponseModel):
    intent: str
    companies: List[str]
    research_mode: str
    evidence_count: int


class Routing(_ExtensibleResponseModel):
    provider: str


class Execution(_ExtensibleResponseModel):
    strategy: str


class Workflow(_ExtensibleResponseModel):
    type: str
    status: str


class ChatResponse(BaseModel):
    report: str
    citations: List[Citation]
    reasoning: Reasoning
    plan: Dict[str, Any]
    execution_time: float
    routing: Optional[Routing] = None
    planning: Optional[Dict[str, Any]] = None
    execution: Optional[Execution] = None
    workflow: Optional[Workflow] = None
    usage: Optional[Dict[str, Any]] = None
