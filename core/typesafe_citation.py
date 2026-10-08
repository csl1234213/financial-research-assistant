"""Typed, provider-free citation judgments for the production answer path.

This module follows the TypeSafe shape without making a network call: the
workflow receives a small typed judgment and owns the policy decision.  Exact
quote integrity, scope checks, and numeric normalization remain deterministic
rules; ambiguous qualitative overlap is reported as ``REVIEW`` instead of
being presented as proof.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from agent.planning.entity_extractor import extract_companies
from core.fact_ledger import canonical_company, periods_equivalent
from core.financial_grounding import (
    canonical_metrics,
    extract_normalized_numbers,
    numbers_equivalent,
)
from retrieval.periods import extract_periods


class CitationRelation(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    SAYS_NOTHING = "SAYS_NOTHING"
    FABRICATED = "FABRICATED"


class CitationAction(str, Enum):
    ACCEPT = "ACCEPT"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


@dataclass(frozen=True)
class CitationJudgment:
    """A reusable typed decision; no generated explanation is required."""

    relation: CitationRelation
    action: CitationAction
    confidence: float
    reason: str


def _normalize_quote(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _meaningful_tokens(value: str) -> set[str]:
    words = {
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", str(value or ""))
    }
    words.difference_update({"the", "and", "for", "from", "was", "were", "with", "this", "that"})
    # Keep short CJK bigrams so Chinese claims do not become an always-review
    # branch merely because they do not contain ASCII words.
    for run in re.findall(r"[\u3400-\u9fff]{2,}", str(value or "")):
        words.update(run[index:index + 2] for index in range(len(run) - 1))
    return words


def _scope_matches(claim: str, source: str, metadata: Mapping[str, object] | None) -> CitationJudgment | None:
    claim_companies = {canonical_company(item) for item in extract_companies(claim)}
    source_company = canonical_company(str((metadata or {}).get("company", "")))
    if not source_company:
        source_companies = {canonical_company(item) for item in extract_companies(source)}
    else:
        source_companies = {source_company}
    if claim_companies and source_companies and claim_companies.isdisjoint(source_companies):
        return CitationJudgment(
            CitationRelation.CONTRADICTS, CitationAction.REJECT, 0.99,
            "company scope mismatch",
        )

    claim_periods = extract_periods(claim)
    source_periods = set(extract_periods(source))
    for key in ("quarter", "period", "periods", "fact_period", "table_column_period", "evidence_row_period"):
        source_periods.update(extract_periods(str((metadata or {}).get(key, ""))))
    if claim_periods and source_periods and not any(
        periods_equivalent(claim_period, source_period)
        for claim_period in claim_periods
        for source_period in source_periods
    ):
        return CitationJudgment(
            CitationRelation.CONTRADICTS, CitationAction.REJECT, 0.98,
            "period scope mismatch",
        )

    claim_metrics = set(canonical_metrics(claim))
    source_metrics = set(canonical_metrics(source))
    if claim_metrics and source_metrics and claim_metrics.isdisjoint(source_metrics):
        return CitationJudgment(
            CitationRelation.SAYS_NOTHING, CitationAction.REVIEW, 0.75,
            "financial metric mismatch",
        )
    return None


def judge_citation(
    claim: str,
    source: str,
    *,
    metadata: Mapping[str, object] | None = None,
    exact_quote: str | None = None,
) -> CitationJudgment:
    """Return a deterministic citation relation and policy action.

    ``exact_quote`` is optional because the current provider contract carries
    source chunks rather than user-supplied quoted spans.  When supplied, a
    missing quote is explicitly marked fabricated, never silently accepted.
    """

    normalized_source = _normalize_quote(source)
    if exact_quote and _normalize_quote(exact_quote) not in normalized_source:
        return CitationJudgment(
            CitationRelation.FABRICATED, CitationAction.REJECT, 0.99,
            "exact quote is absent from source",
        )
    scoped = _scope_matches(claim, source, metadata)
    if scoped is not None:
        return scoped

    claim_numbers = extract_normalized_numbers(claim)
    source_numbers = extract_normalized_numbers(source)
    if claim_numbers:
        if all(any(numbers_equivalent(claim_number, source_number) for source_number in source_numbers)
               for claim_number in claim_numbers):
            return CitationJudgment(
                CitationRelation.SUPPORTS, CitationAction.ACCEPT, 0.99,
                "all numeric claims normalize to source values",
            )
        # Structured table rows may carry an unlabeled, column-scoped number
        # (for example ``22,496`` under a ``$ in millions`` header).  The
        # production fact ledger owns that scale/column interpretation, so a
        # generic typed precheck must defer instead of falsely rejecting it.
        # Explicit currency/unit-bearing source values are safe to reject.
        if re.search(r"[$€£]|\b(?:thousand|million|billion|bn|usd|eur)\b|%", source, re.I):
            return CitationJudgment(
                CitationRelation.CONTRADICTS, CitationAction.REJECT, 0.97,
                "at least one numeric claim is absent or unequal in source",
            )
        return CitationJudgment(
            CitationRelation.SAYS_NOTHING, CitationAction.REVIEW, 0.45,
            "numeric scale or table column requires the production fact ledger",
        )

    overlap = _meaningful_tokens(claim) & _meaningful_tokens(source)
    if len(overlap) >= 2 or (len(overlap) == 1 and len(_meaningful_tokens(claim)) == 1):
        return CitationJudgment(
            CitationRelation.SUPPORTS, CitationAction.ACCEPT, 0.85,
            "qualitative claim has bounded lexical support",
        )
    return CitationJudgment(
        CitationRelation.SAYS_NOTHING, CitationAction.REVIEW, 0.35,
        "qualitative overlap is too weak for an automatic support decision",
    )


def rejectable(judgment: CitationJudgment) -> bool:
    """Whether code must remove the citation from an answer claim."""

    return judgment.action is CitationAction.REJECT
