"""
knowledge_models.py

Data models for the Financial Research Assistant.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Chunk:
    """
    A single semantic chunk stored in the knowledge base.
    """

    chunk_id: int
    document_id: str

    company: str
    report_type: str
    period: str

    source: str
    page: Optional[int]

    text: str


@dataclass
class KnowledgeSource:
    """
    Represents one uploaded financial report.
    """

    document_id: str

    company: str

    report_type: str

    period: str

    filename: str


@dataclass
class KnowledgeStatistics:
    companies: int

    reports: int

    chunks: int
