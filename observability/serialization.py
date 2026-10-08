"""Safe, deterministic JSON serialization for observability payloads.

Tracing must never turn an application success into a logging failure.  This
module deliberately handles the common value types emitted by the runtime and
redacts credential-shaped fields before they are written to a log or trace.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping
from uuid import UUID

REDACTED_VALUE = "[REDACTED]"
_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "password",
        "refresh_token",
        "secret",
        "token",
    }
)


def to_json_safe(value: Any, *, _seen: set[int] | None = None) -> Any:
    """Return a JSON-compatible representation without raising on rich values.

    Unknown objects are represented by their type rather than ``repr(value)``.
    That keeps telemetry resilient while avoiding accidental disclosure from a
    custom object's representation.
    """

    if _seen is None:
        _seen = set()

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else "<non-finite-float>"
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, Enum):
        return to_json_safe(value.value, _seen=_seen)

    identity = id(value)
    if identity in _seen:
        return "<cycle>"

    if isinstance(value, Mapping):
        _seen.add(identity)
        try:
            return {
                str(key): (
                    REDACTED_VALUE
                    if str(key).lower() in _SENSITIVE_FIELD_NAMES
                    else to_json_safe(item, _seen=_seen)
                )
                for key, item in value.items()
            }
        finally:
            _seen.discard(identity)

    if isinstance(value, (list, tuple, set, frozenset)):
        _seen.add(identity)
        try:
            items = [to_json_safe(item, _seen=_seen) for item in value]
            if isinstance(value, (set, frozenset)):
                return sorted(items, key=lambda item: repr(item))
            return items
        finally:
            _seen.discard(identity)

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        _seen.add(identity)
        try:
            return {
                field.name: (
                    REDACTED_VALUE
                    if field.name.lower() in _SENSITIVE_FIELD_NAMES
                    else to_json_safe(getattr(value, field.name), _seen=_seen)
                )
                for field in dataclasses.fields(value)
            }
        finally:
            _seen.discard(identity)

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        _seen.add(identity)
        try:
            return to_json_safe(model_dump(), _seen=_seen)
        except Exception:  # pragma: no cover - third-party model behavior
            return f"<unsupported:{type(value).__name__}>"
        finally:
            _seen.discard(identity)

    return f"<unsupported:{type(value).__name__}>"
