from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class VectorDocument:
    document_id: str
    chunk_id: str
    company: str
    content: str
    embedding: List[float]
    metadata: Dict = field(default_factory=dict)


@dataclass
class SearchResult:
    document_id: str
    chunk_id: str
    score: float
    content: str
    metadata: Dict = field(default_factory=dict)
