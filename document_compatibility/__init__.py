"""Offline document compatibility gates; no production storage or provider calls."""

from .models import DocumentState, FailureClass

__all__ = ["DocumentState", "FailureClass", "audit_document", "inspect_pdf"]


def __getattr__(name):
    # Artifact schema imports must not initialize PDF parsing/retrieval helpers.
    # Preserve the public parser exports when callers actually request them.
    if name in {"audit_document", "inspect_pdf"}:
        from . import engine

        return getattr(engine, name)
    raise AttributeError(name)
