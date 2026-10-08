"""
Single entry point for the API server.

Usage:
    uvicorn api.main:app --host 0.0.0.0 --port 8000

This is the ONLY entry point for production.
Never use `api.app:app` or `api.server:app` directly.
"""

from api.app import app

__all__ = ["app"]
