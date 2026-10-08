# ============================================================
# Workflow Models
# ============================================================
# Core data models for the Workflow Layer.
# Workflow 就是多个 WorkflowStep 的组合。
#
# 预留字段：
#   depends_on  — 步骤依赖（未来支持 DAG / 并行执行图）
#   metadata    — 扩展元数据（人工审批、工具参数等）
# ============================================================

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class WorkflowStep:
    step_id: str

    name: str

    description: str

    required: bool = True

    depends_on: List[str] = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)
