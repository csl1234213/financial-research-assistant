"""Canary promotion requires complete corpus results and preserved financial baselines."""

from __future__ import annotations

from dataclasses import dataclass

from .engine import compare_policies
from .models import CompatibilityReport, DocumentState


@dataclass(frozen=True)
class CorpusFixture:
    fixture_id: str
    format_families: tuple[str, ...]
    capabilities_tested: tuple[str, ...]
    failure_classes_tested: tuple[str, ...]
    expected_quality_status: str
    critical_expected_content: tuple[str, ...]


@dataclass(frozen=True)
class PromotionDecision:
    promote: bool
    state: DocumentState
    reasons: tuple[str, ...]
    regressions: tuple[str, ...]


class FinancialDocumentCompatibilityCorpus:
    def __init__(self, fixtures: tuple[CorpusFixture, ...]):
        if not fixtures or len({f.fixture_id for f in fixtures}) != len(fixtures):
            raise ValueError("corpus requires unique fixture identities")
        self.fixtures = fixtures

    def evaluate(self, reports: dict[str, CompatibilityReport]) -> tuple[str, ...]:
        errors = []
        expected = {f.fixture_id for f in self.fixtures}
        if set(reports) != expected:
            errors.append("INCOMPLETE_CORPUS")
        for fixture in self.fixtures:
            report = reports.get(fixture.fixture_id)
            if report is None:
                continue
            if report.state != fixture.expected_quality_status:
                errors.append(f"{fixture.fixture_id}:quality_status")
            detected = {f.failure_class for f in (*report.failures_before, *report.failures)}
            if not set(fixture.failure_classes_tested) <= detected:
                errors.append(f"{fixture.fixture_id}:failure_detection")
            if report.state == DocumentState.READY:
                text = "\n".join(b.text + b.table_header for b in report.blocks)
                if not all(value in text for value in fixture.critical_expected_content):
                    errors.append(f"{fixture.fixture_id}:critical_content")
        return tuple(errors)


def promotion_decision(
    report: CompatibilityReport,
    corpus: FinancialDocumentCompatibilityCorpus,
    old_reports: dict[str, CompatibilityReport],
    new_reports: dict[str, CompatibilityReport],
    *,
    verified_rows_before: int,
    verified_rows_after: int,
    facts_before: int,
    facts_after: int,
    route_regressions: int | None,
) -> PromotionDecision:
    reasons = list(corpus.evaluate(new_reports))
    regressions = []
    if set(old_reports) != set(new_reports):
        reasons.append("INCOMPLETE_POLICY_COMPARISON")
    for fixture_id in old_reports.keys() & new_reports.keys():
        comparison = compare_policies(old_reports[fixture_id], new_reports[fixture_id])
        regressions.extend(f"{fixture_id}:{item}" for item in comparison["regressions"])
    if verified_rows_after < verified_rows_before:
        regressions.append("P1_3_STRUCTURED_REGRESSION")
    if facts_after < facts_before:
        regressions.append("P1_5_FINANCIAL_FACT_REGRESSION")
    if route_regressions is None:
        reasons.append("P1_7_ROUTE_NOT_VERIFIED")
    elif route_regressions:
        regressions.append("P1_7_ROUTE_REGRESSION")
    if report.state != DocumentState.READY:
        reasons.append("DOCUMENT_QUALITY_CONTRACT_NOT_MET")
    if any(r.parsed_with_policy_version != report.parsed_with_policy_version for r in new_reports.values()):
        reasons.append("MIXED_POLICY_VERSIONS")
    promote = not reasons and not regressions
    return PromotionDecision(
        promote, DocumentState.READY if promote else DocumentState.QUARANTINED, tuple(reasons), tuple(regressions)
    )
