"""Fail-closed allowlist and per-call authorization hook."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, TypeAlias

from .exceptions import ToolAuthorizationDenied, ToolNotAllowed


@dataclass(frozen=True, slots=True)
class ToolAuthorizationRequest:
    """The information available to a policy hook for a single tool call."""

    tool_name: str
    arguments: Mapping[str, Any]
    request_context: Any = None


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """An optional, explainable response from an authorization hook."""

    allowed: bool
    reason: str | None = None


AuthorizationHook: TypeAlias = Callable[[ToolAuthorizationRequest], bool | AuthorizationDecision]


class ToolGovernance:
    """Gates local tool calls through an explicit allowlist and policy hook.

    An empty allowlist is intentional and denies every call.  Supplying an
    allowlist permits only those names; an optional hook can impose additional
    request-specific checks (tenant, user, approval state, and so on).
    """

    def __init__(
        self,
        allowed_tools: Iterable[str] = (),
        *,
        authorization_hook: AuthorizationHook | None = None,
    ) -> None:
        if isinstance(allowed_tools, str):
            raise TypeError("allowed_tools must be an iterable of tool names, not a string")
        names = frozenset(allowed_tools)
        if not all(isinstance(name, str) and name for name in names):
            raise ValueError("allowed tool names must be non-empty strings")
        self._allowed_tools = names
        self._authorization_hook = authorization_hook

    @property
    def allowed_tools(self) -> frozenset[str]:
        return self._allowed_tools

    def is_allowed(self, tool_name: str) -> bool:
        return tool_name in self._allowed_tools

    def ensure_allowed(self, tool_name: str) -> None:
        if not self.is_allowed(tool_name):
            raise ToolNotAllowed(f"Tool '{tool_name}' is not in the allowlist")

    def authorize(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        request_context: Any = None,
    ) -> AuthorizationDecision:
        """Authorize a previously validated call, failing closed on hook errors."""

        self.ensure_allowed(tool_name)
        if self._authorization_hook is None:
            return AuthorizationDecision(allowed=True)

        request = ToolAuthorizationRequest(
            tool_name=tool_name,
            # The policy sees the exact validated values but cannot mutate the
            # mapping that will be handed to the local handler.
            arguments=MappingProxyType(dict(arguments)),
            request_context=request_context,
        )
        try:
            decision = self._authorization_hook(request)
        except Exception as exc:
            raise ToolAuthorizationDenied("authorization hook failed") from exc

        if isinstance(decision, bool):
            decision = AuthorizationDecision(allowed=decision)
        if not isinstance(decision, AuthorizationDecision):
            raise ToolAuthorizationDenied("authorization hook returned an invalid decision")
        if not decision.allowed:
            reason = f": {decision.reason}" if decision.reason else ""
            raise ToolAuthorizationDenied(f"Tool '{tool_name}' was not authorized{reason}")
        return decision
