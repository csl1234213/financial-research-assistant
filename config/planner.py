# ============================================================
# Planner Configuration
# ============================================================
# Configurable weights for ComplexityAnalyzer and future
# Planner components. Change weights here without touching
# Analyzer code.
# ============================================================


from dataclasses import dataclass


@dataclass
class ComplexityWeights:
    prompt_length: float = 0.10
    company_count: float = 0.20
    year_count: float = 0.10
    task_weight: float = 0.50
    comparison: float = 0.10
