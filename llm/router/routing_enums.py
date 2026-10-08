# ============================================================
# Routing Enums
# ============================================================
# Unified enums for all Router components.
# Using Enum avoids string typos like "reasoning" vs "reason".
# ============================================================

from enum import Enum


class TaskType(str, Enum):
    CHAT = "chat"
    SUMMARIZATION = "summarization"
    REASONING = "reasoning"
    DOCUMENT_QA = "document_qa"
    OCR = "ocr"
    IMAGE_ANALYSIS = "image_analysis"
    CODE_GENERATION = "code_generation"


class RoutingPriority(str, Enum):
    COST = "cost"
    SPEED = "speed"
    QUALITY = "quality"
    BALANCED = "balanced"
