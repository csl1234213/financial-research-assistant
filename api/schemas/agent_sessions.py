"""Typed public contracts for authenticated Agent session lifecycle APIs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, JsonValue


class AgentSessionMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    metadata: dict[str, JsonValue]
    created_at: datetime


class AgentSessionSummaryResponse(BaseModel):
    thread_id: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class AgentSessionListResponse(BaseModel):
    items: list[AgentSessionSummaryResponse]
    total: int
    limit: int
    offset: int


class AgentSessionDetailResponse(BaseModel):
    session: AgentSessionSummaryResponse
    messages: list[AgentSessionMessageResponse]
    total_messages: int
    limit: int
    offset: int


class AgentSessionExportResponse(BaseModel):
    format_version: Literal["1.0"] = "1.0"
    exported_at: datetime
    session: AgentSessionSummaryResponse
    messages: list[AgentSessionMessageResponse]
    total_messages: int
    limit: int
    offset: int


class AgentSessionDeleteResponse(BaseModel):
    deleted: Literal[True] = True
    thread_id: str
    messages_deleted: int
    checkpoints_archived: int
    runtime_checkpoints_deleted: bool
    cache_keys_deleted: int
