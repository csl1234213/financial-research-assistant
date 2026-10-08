# ============================================================
# Memory Result
# ============================================================
# Unified output of the Memory Layer.
# 描述一次 Memory 操作（store / retrieve）的结果。
#
# 不包含 Provider（模型选择是 Routing 的职责）。
# 不包含 Runtime 逻辑。
# 保留 summary 字段用于 Memory Compression。
# ============================================================

from dataclasses import dataclass, field
from typing import List, Optional

from .memory_models import MemoryRecord


@dataclass
class MemoryResult:
    records: List[MemoryRecord] = field(default_factory=list)

    retrieved_count: int = 0

    summary: Optional[str] = None

    confidence: float = 1.0

    reason: str = ""
