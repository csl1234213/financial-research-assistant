"""Shared transaction primitives, independent of experimental persistence."""

from datetime import timezone


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def require_aware(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")


def serialize_sqlite(session):
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    elif dialect != "postgresql":
        raise ValueError("UNSUPPORTED_TRANSACTION_DIALECT")
