from dataclasses import dataclass, field
from typing import List


@dataclass
class Evidence:
    """
    Structured evidence extracted from retrieval or tool output.
    """

    content: str

    source: str = ""

    company: str = ""

    confidence: float = 0.0

    metadata: dict = field(default_factory=dict)


@dataclass
class ReasoningResult:
    """
    Structured output produced by Reasoning Engine.

    This is NOT an LLM response.
    It is a structured analysis that Report Builder can consume.
    """

    facts: List[str] = field(default_factory=list)

    risks: List[str] = field(default_factory=list)

    opportunities: List[str] = field(default_factory=list)

    conclusion: str = ""
