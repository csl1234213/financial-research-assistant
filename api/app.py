"""Compatibility module for the unchanged default production API."""
from api.app_factory import DEFAULT_CORS_ORIGINS, create_app, get_cors_origins, get_positive_int_setting

__all__ = ["app", "create_app", "get_cors_origins", "get_positive_int_setting", "DEFAULT_CORS_ORIGINS"]

app = create_app()
