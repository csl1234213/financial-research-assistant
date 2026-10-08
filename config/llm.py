"""
LLM Provider Configuration
===========================
All LLM-related settings are read from environment variables here.
Every provider reads from this single source of truth.
"""

import os

# =========================
# LLM — Unified
# =========================

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")
LLM_API_KEY = os.getenv("LLM_API_KEY", os.getenv("DEEPSEEK_API_KEY", ""))
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))
LLM_CONNECT_TIMEOUT = float(os.getenv("LLM_CONNECT_TIMEOUT", "10"))
LLM_READ_TIMEOUT = float(os.getenv("LLM_READ_TIMEOUT", "45"))
LLM_TOTAL_DEADLINE = float(os.getenv("LLM_TOTAL_DEADLINE", "120"))
LLM_STREAM = os.getenv("LLM_STREAM", "false").lower() == "true"
LLM_ROUTING_PROVIDER_ALLOWLIST = tuple(
    provider.strip().casefold()
    for provider in os.getenv("LLM_ROUTING_PROVIDER_ALLOWLIST", "").split(",")
    if provider.strip()
)

# =========================
# DeepSeek
# =========================

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# =========================
# Gemini
# =========================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

# =========================
# OpenAI
# =========================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.5")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

# =========================
# Anthropic
# =========================

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-fable-5")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

# =========================
# Doubao / Volcengine Ark
# =========================

DOUBAO_API_KEY = os.getenv("DOUBAO_API_KEY", "")
DOUBAO_MODEL = os.getenv("DOUBAO_MODEL", "doubao-seed-2-0-pro-260215")
DOUBAO_BASE_URL = os.getenv(
    "DOUBAO_BASE_URL",
    "https://ark.cn-beijing.volces.com/api/v3",
)
