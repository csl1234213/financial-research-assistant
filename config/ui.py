"""
UI configuration — Streamlit, API base URL, upload, page settings.
All values are env-driven with sensible defaults.
"""

import os

# =========================
# Environment
# =========================

APP_ENV = os.getenv("APP_ENV", "development")

# =========================
# Streamlit
# =========================

STREAMLIT_HOST = os.getenv("STREAMLIT_HOST", "0.0.0.0")
STREAMLIT_PORT = int(os.getenv("STREAMLIT_PORT", "8501"))

# =========================
# Backend API
# =========================

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
# Docker Compose 中会覆盖: http://financial-api:8000

# =========================
# Upload
# =========================

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")

# =========================
# UI
# =========================

PAGE_TITLE = os.getenv("PAGE_TITLE", "Financial Research Copilot")
PAGE_LAYOUT = os.getenv("PAGE_LAYOUT", "wide")
