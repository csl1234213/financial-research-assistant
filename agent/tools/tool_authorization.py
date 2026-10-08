"""Optional authorization hook for direct ``ToolEngine`` callers.

The hook is intentionally opt-in so existing ToolEngine construction and
execution semantics remain unchanged.  The local MCP adapter has its own
deny-by-default allowlist; this extension lets non-MCP callers add the same
kind of final execution check when needed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeAlias

from .tool_context import ToolContext


@dataclass(frozen=True, slots=True)
class ToolAuthorizationDecision:
    """A policy decision returned by an optional ToolEngine hook."""

    allowed: bool
    reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


ToolAuthorizationHook: TypeAlias = Callable[[str, ToolContext], bool | ToolAuthorizationDecision]


def evaluate_authorization(
    hook: ToolAuthorizationHook,
    tool_name: str,
    context: ToolContext,
) -> ToolAuthorizationDecision:
    """Evaluate a hook and fail closed if it raises or returns an invalid value."""

    try:
        result = hook(tool_name, context)
    except Exception:
        return ToolAuthorizationDecision(allowed=False, reason="authorization hook failed")
    if isinstance(result, bool):
        return ToolAuthorizationDecision(allowed=result)
    if isinstance(result, ToolAuthorizationDecision):
        return result
    return ToolAuthorizationDecision(allowed=False, reason="authorization hook returned an invalid decision")
