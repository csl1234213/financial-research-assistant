# ============================================================
# Planning Task Enums
# ============================================================
# Unified enums for task classification and complexity.
# All Planner components use these enums to avoid string
# typos and ensure consistent semantics across the system.
# ============================================================

from enum import Enum


class TaskType(str, Enum):
    CHAT = "chat"

    DOCUMENT_QA = "document_qa"

    RESEARCH = "research"

    FINANCIAL_ANALYSIS = "financial_analysis"

    COMPARISON = "comparison"

    SUMMARIZATION = "summarization"

    OCR = "ocr"

    IMAGE_ANALYSIS = "image_analysis"

    CODE_GENERATION = "code_generation"

    UNKNOWN = "unknown"


class ComplexityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
