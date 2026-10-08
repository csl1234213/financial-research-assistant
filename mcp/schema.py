"""A small, dependency-free JSON-Schema-like validator for tool arguments.

Supported keywords are ``type``, ``properties``, ``required``,
``additionalProperties``, ``items``, ``enum``, ``const``, numeric and length
bounds, ``pattern``, and the ``allOf`` / ``anyOf`` / ``oneOf`` combinators.
Unsupported references fail closed instead of being silently ignored.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from numbers import Number
from typing import Any

from .exceptions import SchemaDefinitionError, SchemaValidationError

_SUPPORTED_TYPES = {"array", "boolean", "integer", "null", "number", "object", "string"}


def validate_arguments(arguments: Mapping[str, Any], schema: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a shallow copy of JSON-object tool arguments.

    Tool inputs are always objects.  This deliberately avoids coercion: a
    string ``"3"`` is not accepted for an integer property, for example.
    """

    if not isinstance(arguments, Mapping):
        raise SchemaValidationError("arguments must be an object")
    if not isinstance(schema, Mapping):
        raise SchemaDefinitionError("input schema must be an object")

    schema_copy = dict(schema)
    if "type" not in schema_copy:
        # MCP tool input schemas are object-shaped even when callers omit the
        # redundant top-level type.
        schema_copy["type"] = "object"
    _validate(dict(arguments), schema_copy, path="$")
    return dict(arguments)


def _validate(value: Any, schema: Mapping[str, Any], *, path: str) -> None:
    if "$ref" in schema:
        raise SchemaDefinitionError(f"{path}: $ref is not supported by the local validator")

    _validate_combinators(value, schema, path)

    expected_type = schema.get("type")
    if expected_type is not None:
        if not isinstance(expected_type, str) or expected_type not in _SUPPORTED_TYPES:
            raise SchemaDefinitionError(f"{path}: unsupported schema type {expected_type!r}")
        if not _matches_type(value, expected_type):
            raise SchemaValidationError(f"{path}: expected {expected_type}")

    if "const" in schema and value != schema["const"]:
        raise SchemaValidationError(f"{path}: must equal the configured constant")

    if "enum" in schema:
        allowed_values = schema["enum"]
        if not _is_non_string_sequence(allowed_values):
            raise SchemaDefinitionError(f"{path}: enum must be an array")
        if value not in allowed_values:
            raise SchemaValidationError(f"{path}: value is not in the allowed enum")

    if isinstance(value, Mapping):
        _validate_object(value, schema, path)
    elif isinstance(value, list):
        _validate_array(value, schema, path)
    elif isinstance(value, str):
        _validate_string(value, schema, path)
    elif _is_number(value):
        _validate_number(value, schema, path)


def _validate_combinators(value: Any, schema: Mapping[str, Any], path: str) -> None:
    for key in ("allOf", "anyOf", "oneOf"):
        if key not in schema:
            continue
        alternatives = schema[key]
        if not _is_non_string_sequence(alternatives) or not alternatives:
            raise SchemaDefinitionError(f"{path}: {key} must be a non-empty array of schemas")
        if not all(isinstance(item, Mapping) for item in alternatives):
            raise SchemaDefinitionError(f"{path}: {key} entries must be objects")

        if key == "allOf":
            for item in alternatives:
                _validate(value, item, path=path)
            continue

        matches = 0
        for item in alternatives:
            try:
                _validate(value, item, path=path)
            except SchemaValidationError:
                continue
            matches += 1

        if key == "anyOf" and matches == 0:
            raise SchemaValidationError(f"{path}: does not match any allowed schema")
        if key == "oneOf" and matches != 1:
            raise SchemaValidationError(f"{path}: must match exactly one allowed schema")


def _validate_object(value: Mapping[str, Any], schema: Mapping[str, Any], path: str) -> None:
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise SchemaDefinitionError(f"{path}: properties must be an object")
    required = schema.get("required", [])
    if not _is_non_string_sequence(required) or not all(isinstance(name, str) for name in required):
        raise SchemaDefinitionError(f"{path}: required must be an array of property names")

    for name in required:
        if name not in value:
            raise SchemaValidationError(f"{_property_path(path, name)}: is required")

    for name, item in value.items():
        item_path = _property_path(path, str(name))
        if name in properties:
            child_schema = properties[name]
            if not isinstance(child_schema, Mapping):
                raise SchemaDefinitionError(f"{item_path}: property schema must be an object")
            _validate(item, child_schema, path=item_path)
            continue

        additional = schema.get("additionalProperties", True)
        if additional is False:
            raise SchemaValidationError(f"{item_path}: unexpected property")
        if additional is True:
            continue
        if not isinstance(additional, Mapping):
            raise SchemaDefinitionError(f"{path}: additionalProperties must be a boolean or schema")
        _validate(item, additional, path=item_path)


def _validate_array(value: list[Any], schema: Mapping[str, Any], path: str) -> None:
    _validate_bound(len(value), schema, "minItems", "maxItems", path)
    if "items" not in schema:
        return
    item_schema = schema["items"]
    if not isinstance(item_schema, Mapping):
        raise SchemaDefinitionError(f"{path}: items must be an object")
    for index, item in enumerate(value):
        _validate(item, item_schema, path=f"{path}[{index}]")


def _validate_string(value: str, schema: Mapping[str, Any], path: str) -> None:
    _validate_bound(len(value), schema, "minLength", "maxLength", path)
    if "pattern" not in schema:
        return
    pattern = schema["pattern"]
    if not isinstance(pattern, str):
        raise SchemaDefinitionError(f"{path}: pattern must be a string")
    try:
        matches = re.search(pattern, value)
    except re.error as exc:
        raise SchemaDefinitionError(f"{path}: invalid pattern") from exc
    if matches is None:
        raise SchemaValidationError(f"{path}: does not match the required pattern")


def _validate_number(value: Number, schema: Mapping[str, Any], path: str) -> None:
    _validate_bound(value, schema, "minimum", "maximum", path)


def _validate_bound(value: Number, schema: Mapping[str, Any], lower_key: str, upper_key: str, path: str) -> None:
    if lower_key in schema:
        lower = schema[lower_key]
        if not _is_number(lower):
            raise SchemaDefinitionError(f"{path}: {lower_key} must be numeric")
        if value < lower:
            raise SchemaValidationError(f"{path}: must be at least {lower}")
    if upper_key in schema:
        upper = schema[upper_key]
        if not _is_number(upper):
            raise SchemaDefinitionError(f"{path}: {upper_key} must be numeric")
        if value > upper:
            raise SchemaValidationError(f"{path}: must be at most {upper}")


def _matches_type(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, Mapping)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return _is_number(value)
    if expected_type == "null":
        return value is None
    return False  # pragma: no cover - guarded by _SUPPORTED_TYPES


def _is_number(value: Any) -> bool:
    return isinstance(value, Number) and not isinstance(value, bool)


def _is_non_string_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _property_path(path: str, name: str) -> str:
    if name.isidentifier():
        return f"{path}.{name}"
    return f"{path}[{name!r}]"
