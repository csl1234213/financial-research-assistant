"""
Unified config — backward compatible with old config.py imports.
All existing imports like `from config import DEBUG_MODE` still work.
"""

import os
from importlib import import_module
from pathlib import Path

from dotenv import load_dotenv

from agent.__version__ import BASE_VERSION

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


# =========================
# Legacy (from config.py)
# =========================

PDFS_DIR = "pdfs"
DEBUG_MODE = False
DOCUMENT_HINTS = {
    "Tesla": [
        "tesla",
        "robotaxi",
        "cybercab",
        "optimus",
        "fsd",
        "supercharger",
        "megapack",
    ],
    "NVIDIA": [
        "nvidia",
        "blackwell",
        "cuda",
        "dgx",
        "nvlink",
        "ai factory",
        "grace",
        "hopper",
    ],
    "Apple": [
        "apple",
        "apple intelligence",
        "vision pro",
        "iphone",
        "ipad",
        "mac",
        "services",
        "app store",
    ],
}

DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_EMBEDDING_MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"

CACHE_DIR = os.environ.get("CACHE_DIR", "cache")
TOP_K = 4
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
EMBEDDING_MODEL_REVISION = os.environ.get(
    "EMBEDDING_MODEL_REVISION",
    (
        DEFAULT_EMBEDDING_MODEL_REVISION
        if EMBEDDING_MODEL == DEFAULT_EMBEDDING_MODEL
        else ""
    ),
)
EMBEDDING_DEVICE = os.environ.get("EMBEDDING_DEVICE", "")
EMBEDDING_BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE", "32"))
CACHE_VERSION = "1.8"
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "200"))
OCR_ENABLED = _env_bool("OCR_ENABLED", True)
OCR_LANGUAGES = os.environ.get("OCR_LANGUAGES", "eng+chi_sim")
OCR_DPI = int(os.environ.get("OCR_DPI", "300"))
OCR_MIN_TEXT_CHARS = int(os.environ.get("OCR_MIN_TEXT_CHARS", "80"))

# =========================
# New (V7.3 — env-driven)
# =========================

APP_ENV = os.environ.get("APP_ENV", "development")
APP_VERSION = os.environ.get("APP_VERSION", BASE_VERSION)
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

ROOT_DIR = Path(__file__).resolve().parent.parent

CHROMA_PATH = Path(os.environ.get("CHROMA_PATH", ROOT_DIR / "chroma_db"))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", ROOT_DIR / "storage" / "uploads"))
PDF_DIR = Path(os.environ.get("PDF_DIR", ROOT_DIR / "storage" / "pdfs"))

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# Backward compatibility for old env vars
if not os.environ.get("LLM_MODEL") and os.environ.get("DEEPSEEK_MODEL"):
    os.environ["LLM_MODEL"] = os.environ["DEEPSEEK_MODEL"]

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

# =========================
# UI (V7.3 Phase 2.2)
# =========================


# =========================
# LLM (V5 Phase 1 — Provider abstraction)
# =========================
_llm_config = import_module(".llm", __package__)
LLM_PROVIDER = _llm_config.LLM_PROVIDER
LLM_MODEL = _llm_config.LLM_MODEL
LLM_API_KEY = _llm_config.LLM_API_KEY
LLM_BASE_URL = _llm_config.LLM_BASE_URL
LLM_TEMPERATURE = _llm_config.LLM_TEMPERATURE
LLM_MAX_TOKENS = _llm_config.LLM_MAX_TOKENS
LLM_TIMEOUT = _llm_config.LLM_TIMEOUT
LLM_CONNECT_TIMEOUT = _llm_config.LLM_CONNECT_TIMEOUT
LLM_READ_TIMEOUT = _llm_config.LLM_READ_TIMEOUT
LLM_TOTAL_DEADLINE = _llm_config.LLM_TOTAL_DEADLINE
LLM_STREAM = _llm_config.LLM_STREAM
LLM_ROUTING_PROVIDER_ALLOWLIST = _llm_config.LLM_ROUTING_PROVIDER_ALLOWLIST
DEEPSEEK_MODEL = _llm_config.DEEPSEEK_MODEL
DEEPSEEK_BASE_URL = _llm_config.DEEPSEEK_BASE_URL
GEMINI_API_KEY = _llm_config.GEMINI_API_KEY
GEMINI_MODEL = _llm_config.GEMINI_MODEL
OPENAI_API_KEY = _llm_config.OPENAI_API_KEY
OPENAI_MODEL = _llm_config.OPENAI_MODEL
OPENAI_BASE_URL = _llm_config.OPENAI_BASE_URL
ANTHROPIC_API_KEY = _llm_config.ANTHROPIC_API_KEY
ANTHROPIC_MODEL = _llm_config.ANTHROPIC_MODEL
ANTHROPIC_BASE_URL = _llm_config.ANTHROPIC_BASE_URL
DOUBAO_API_KEY = _llm_config.DOUBAO_API_KEY
DOUBAO_MODEL = _llm_config.DOUBAO_MODEL
DOUBAO_BASE_URL = _llm_config.DOUBAO_BASE_URL

_ui_config = import_module(".ui", __package__)
_ui_exports = getattr(
    _ui_config,
    "__all__",
    (name for name in vars(_ui_config) if not name.startswith("_")),
)
for _name in _ui_exports:
    # Root configuration is authoritative for names shared with a specialised
    # module.  UI-only names remain available from ``config`` for backward
    # compatibility, while values such as UPLOAD_DIR keep their canonical
    # Path-based type and project-root default.
    if _name not in globals():
        globals()[_name] = getattr(_ui_config, _name)

__all__ = [
    "PDFS_DIR",
    "DEBUG_MODE",
    "DOCUMENT_HINTS",
    "CACHE_DIR",
    "TOP_K",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_EMBEDDING_MODEL_REVISION",
    "EMBEDDING_MODEL",
    "EMBEDDING_MODEL_REVISION",
    "EMBEDDING_DEVICE",
    "EMBEDDING_BATCH_SIZE",
    "CACHE_VERSION",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "OCR_ENABLED",
    "OCR_LANGUAGES",
    "OCR_DPI",
    "OCR_MIN_TEXT_CHARS",
    "LLM_TEMPERATURE",
    "LLM_MAX_TOKENS",
    "APP_ENV",
    "APP_VERSION",
    "LOG_LEVEL",
    "ROOT_DIR",
    "CHROMA_PATH",
    "UPLOAD_DIR",
    "PDF_DIR",
    "DEEPSEEK_API_KEY",
    "REDIS_HOST",
    "REDIS_PORT",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_TEMPERATURE",
    "LLM_MAX_TOKENS",
    "LLM_TIMEOUT",
    "LLM_CONNECT_TIMEOUT",
    "LLM_READ_TIMEOUT",
    "LLM_TOTAL_DEADLINE",
    "LLM_STREAM",
    "LLM_ROUTING_PROVIDER_ALLOWLIST",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_BASE_URL",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_BASE_URL",
    "DOUBAO_API_KEY",
    "DOUBAO_MODEL",
    "DOUBAO_BASE_URL",
]
