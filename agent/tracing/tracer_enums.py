# ============================================================
# Tracer Type Enums
# ============================================================
# 表示 Tracer 的实现类型（由谁记录），
# 与 TraceType（追踪什么）是不同关注点。
#
# TracerType → 由谁记录
# TraceType  → 追踪什么
# ============================================================

from enum import Enum


class TracerType(str, Enum):
    CONSOLE = "console"
    MEMORY = "memory"
    FILE = "file"
