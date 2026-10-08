"""
App-level configuration (FastAPI, version, title).
"""

import os

from agent.__version__ import BASE_VERSION

APP_TITLE = "Financial Research Copilot API"
APP_DESCRIPTION = "Production API for Financial Research Copilot"
APP_VERSION = os.environ.get("APP_VERSION", BASE_VERSION)

API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8000"))

UI_PORT = int(os.environ.get("UI_PORT", "8501"))
API_BASE = os.environ.get("API_BASE", "http://financial-api:8000")
