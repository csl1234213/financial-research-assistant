# ============================================================
# V7.3.0 — Reliability Framework
# ============================================================
# Benchmark & Freeze — Phase 3 Sprint 2 Step 4
# ============================================================
# Reliability Pipeline:
#   HealthCheck → RateLimiter → Timeout → Retry → CircuitBreaker → Fallback
#
# 全量测试: 1156 passed, 0 failed (51 benchmark + 1105 existing)
# Reliability Benchmark: 51/51 passed
#   - Retry Accuracy:        5/5 passed
#   - Timeout Accuracy:      4/4 passed
#   - Circuit Breaker:       5/5 passed
#   - Health Check:          3/3 passed
#   - Rate Limiter:          4/4 passed
#   - Fallback:              4/4 passed
#   - Pipeline:              5/5 passed
#   - Performance:           6/6 passed
#   - Stability:             4/4 passed
#   - Failure Benchmark:     7/7 passed
#   - Regression:            4/4 passed
# ============================================================

"""Application release version.

``BASE_VERSION`` is the source-controlled product version. Deployments may
override the reported runtime version through ``APP_VERSION`` (for example to
append an immutable build identifier) without creating another code-level
version source.
"""

import os

BASE_VERSION = "8.2.0"
__version__ = os.getenv("APP_VERSION", BASE_VERSION)
