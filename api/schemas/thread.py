"""Shared validation for client-visible Agent thread identifiers."""

MAX_THREAD_ID_LENGTH = 256


def validate_thread_id(value: str | None) -> str | None:
    if value is not None and (
        not value.strip() or value != value.strip()
    ):
        raise ValueError(
            "thread_id must not be blank or have surrounding whitespace"
        )
    return value
