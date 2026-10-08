"""Closed-grammar factual paraphrase verification, not general narrative entailment."""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.answer_synthesis_contracts import (
    AnswerPlan,
    AnswerType,
    SynthesisInput,
    VerificationFailure,
    VerificationResult,
)
from core.answer_synthesis_renderer import RestrictedAnswerRenderer, RestrictedOutputVerifier, company_display_name
from core.financial_metric_registry import FINANCIAL_METRIC_REGISTRY


@dataclass(frozen=True)
class ExtractedFactClaim:
    claim_id: str
    evidence_id: str
    text: str
    grammar_rule: str


def factual_sentence_variants(source: SynthesisInput, plan: AnswerPlan) -> tuple[tuple[str, ...], ...]:
    """Explicit grammatical variations of locked fields, never an open semantic classifier."""
    baseline = RestrictedAnswerRenderer().render(source, plan)
    original_lines = baseline.text.split("\n\n")
    variants = []
    scopes = {
        "CONSOLIDATED": ("合并报表", "consolidated statements"),
        "PARENT_COMPANY": ("母公司报表", "parent-company statements"),
    }
    for index, claim in enumerate(plan.claims):
        row = claim.observation
        period = row["period"]
        definition = FINANCIAL_METRIC_REGISTRY.get(row["metric"])
        rank = baseline.citation_evidence_ids.index(claim.evidence_ids[0]) + 1
        money = baseline.presentations[index].text
        company = company_display_name(source, claim)
        if source.locale == "zh-CN":
            date_phrase = (
                "截至" + period["period_end"]
                if period["period_type"] == "INSTANT"
                else period["period_start"] + "至" + period["period_end"] + "期间"
            )
            scope = scopes[row["scope"]][0]
            alternatives = tuple(
                f"{date_phrase}，{company}{scope}的{alias}为{money} [{rank}]。"
                for alias in definition.aliases_zh
            )
        else:
            date_phrase = (
                "As of " + period["period_end"]
                if period["period_type"] == "INSTANT"
                else "For " + period["period_start"] + " to " + period["period_end"]
            )
            scope = scopes[row["scope"]][1]
            alternatives = tuple(
                f"{date_phrase}, {alias} of {company} ({scope}) was {money} [{rank}]."
                for alias in definition.aliases_en
            )
        variants.append((original_lines[index], *alternatives))
    return tuple(variants)


class ControlledFactDraftVerifier:
    """Every character must belong to a registered, source-locked factual sentence.

    A matched claim inherits its audited observation only after the entire
    sentence matches. Unconsumed prose never acquires a fabricated evidence ID.
    """

    def extract(self, source: SynthesisInput, plan: AnswerPlan, draft: str) -> tuple[ExtractedFactClaim, ...]:
        if not isinstance(draft, str) or not draft.strip() or len(draft) > 65536:
            raise ValueError("invalid draft size")
        patterns = factual_sentence_variants(source, plan)
        sentences = tuple(line.strip() for line in draft.splitlines() if line.strip())
        if len(sentences) != len(plan.claims):
            raise ValueError("unconsumed or missing factual sentences")
        extracted = []
        for sentence in sentences:
            matching = [index for index, options in enumerate(patterns) if sentence in options]
            if len(matching) != 1:
                raise ValueError("unknown or ambiguous factual sentence")
            claim = plan.claims[matching[0]]
            extracted.append(
                ExtractedFactClaim(claim.claim_id, claim.evidence_ids[0], sentence, "locked_fact_sentence.v1")
            )
        if len({item.claim_id for item in extracted}) != len(plan.claims):
            raise ValueError("duplicate claim or omitted evidence")
        if source.answer_type == AnswerType.TREND and tuple(item.claim_id for item in extracted) != tuple(
            item.claim_id for item in plan.claims
        ):
            raise ValueError("trend period order changed")
        return tuple(extracted)

    def verify(self, source: SynthesisInput, plan: AnswerPlan, draft: str) -> VerificationResult:
        try:
            baseline = RestrictedAnswerRenderer().render(source, plan)
        except ValueError:
            return VerificationResult((VerificationFailure.UNSUPPORTED_CLAIM,))
        # observation/citation/provenance gates are still mandatory before grammar checking.
        checked = RestrictedOutputVerifier().verify(source, plan, baseline)
        if not checked.passed:
            return checked
        try:
            extracted = self.extract(source, plan, draft)
        except ValueError:
            failures = [VerificationFailure.UNSUPPORTED_CLAIM]
            if isinstance(draft, str):
                ranks = re.findall(r"\[(\d+)\]", draft)
                if not ranks:
                    failures.append(VerificationFailure.CITATION_MISSING)
                elif any(
                    len(rank) > 6 or int(rank) not in range(1, len(baseline.citation_evidence_ids) + 1)
                    for rank in ranks
                ):
                    failures.append(VerificationFailure.CITATION_WRONG_SOURCE)
                if re.search(r"导致|造成|因为|\bbecause\b|\bcaused\b|\bdriven by\b", draft, re.I):
                    failures.append(VerificationFailure.OVERCLAIMED_CAUSALITY)
            return VerificationResult(tuple(failures))
        return VerificationResult((), tuple(item.claim_id for item in extracted), semantic_review_complete=True)
