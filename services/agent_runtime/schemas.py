from typing import Any

from pydantic import BaseModel, Field


class AgentChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    thread_id: str = "default"


class AgentChatResponse(BaseModel):
    answer: str
    thread_id: str
    tools_used: list[str] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    research_plan: list[dict[str, Any]] = Field(default_factory=list)
    quality_score: float = 0.0
    critique: dict[str, Any] = Field(default_factory=dict)
    revision_count: int = 0
    history: list[dict[str, Any]] = Field(default_factory=list)
