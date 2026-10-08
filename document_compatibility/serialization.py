"""Strict typed restoration of persisted compatibility audit artifacts."""

from dataclasses import fields, is_dataclass
from enum import Enum
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints

from document_compatibility.models import CompatibilityReport, TableCellGeometry


def _restore(kind, value):
    origin, args = get_origin(kind), get_args(kind)
    if origin in (Union, UnionType):
        if value is None and type(None) in args:
            return None
        for candidate in args:
            if candidate is type(None):
                continue
            try:
                return _restore(candidate, value)
            except (ValueError, TypeError):
                continue
        raise ValueError("AUDIT_UNION_TYPE_MISMATCH")
    if is_dataclass(kind):
        if (kind is TableCellGeometry and isinstance(value, dict)
                and set(value) == {"row", "column", "text", "bbox", "row_span", "column_span"}):
            # Pre-v4 persisted cells never contained a native-region proof.
            # Restore them conservatively; absence cannot grant trust.
            value = {**value, "source_ids": [], "source_binding_proven": False}
        if not isinstance(value, dict) or set(value) != {field.name for field in fields(kind)}:
            raise ValueError("AUDIT_SCHEMA_MISMATCH")
        hints = get_type_hints(kind)
        return kind(**{key: _restore(hints[key], item) for key, item in value.items()})
    if origin is tuple:
        if not isinstance(value, list):
            raise ValueError("AUDIT_TUPLE_REQUIRED")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_restore(args[0], item) for item in value)
        if len(value) != len(args):
            raise ValueError("AUDIT_TUPLE_LENGTH")
        return tuple(_restore(item_type, item) for item_type, item in zip(args, value))
    if origin is dict:
        if not isinstance(value, dict):
            raise ValueError("AUDIT_DICT_REQUIRED")
        return {_restore(args[0], key): _restore(args[1], item) for key, item in value.items()}
    if isinstance(kind, type) and issubclass(kind, Enum):
        return kind(value)
    if kind is float and type(value) in (int, float):
        return float(value)
    if type(value) is not kind:
        raise ValueError("AUDIT_VALUE_TYPE_MISMATCH")
    return value


def compatibility_report_from_dict(payload):
    return _restore(CompatibilityReport, payload)
