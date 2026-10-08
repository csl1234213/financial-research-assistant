"""Deterministic, auditable canonicalization for financial statement row labels.

This registry is intentionally independent from PDF parsing, retrieval, prompts,
and provider-backed semantic classification. Structural row verification and
financial metric meaning are separate judgments: normalization never changes a
source row or upgrades its ``VerificationStatus``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Iterable, Mapping

from core.financial_table_rows import FinancialTableRow, VerificationStatus


class MetricMappingStatus(StrEnum):
    """How strongly a registry rule supports the row-label mapping."""

    EXACT = "EXACT"
    SUPPORTED = "SUPPORTED"
    AMBIGUOUS = "AMBIGUOUS"
    UNMAPPED = "UNMAPPED"


@dataclass(frozen=True, slots=True)
class FinancialMetricDefinition:
    """A canonical metric plus its accounting/reporting dimensions."""

    canonical_name: str
    category: str
    statement_types: tuple[str, ...]
    aliases_zh: tuple[str, ...]
    aliases_en: tuple[str, ...]
    scope_rules: str
    period_semantics: str
    value_type: str
    aggregation_semantics: str
    notes: str = ""
    query_aliases_zh: tuple[str, ...] = ()
    query_aliases_en: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MetricAliasRule:
    """A contextual alias; aliases are not global string substitutions."""

    alias: str
    canonical_metric: str
    statement_types: tuple[str, ...]
    status: MetricMappingStatus
    mapping_rule: str
    required_context: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MetricNormalization:
    """Auditable semantic projection that leaves its source row unchanged."""

    row: FinancialTableRow
    original_label: str
    normalized_label: str
    canonical_metric: str | None
    mapping_status: MetricMappingStatus
    mapping_rule: str
    mapping_evidence: str

    @property
    def statement_type(self) -> str | None:
        return self.row.statement_type

    @property
    def scope(self) -> str | None:
        return self.row.scope


@dataclass(frozen=True, slots=True)
class QueryMetricResolution:
    """A query phrase resolved only through declared registry aliases."""

    canonical_metric: str | None
    status: MetricMappingStatus
    matched_alias: str | None = None
    period_semantics: str | None = None
    reason: str = ""


def normalize_row_label(label: str) -> str:
    """Normalize formatting noise while retaining accounting-significant words.

    NFKC handles full-width punctuation and compatibility spaces. The prefix
    ``其中:`` and attribution/scope language are deliberately preserved.
    """

    normalized = unicodedata.normalize("NFKC", label)
    normalized = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.replace("：", ":").replace("﹕", ":")
    normalized = normalized.replace("（", "(").replace("）", ")")
    normalized = normalized.replace("［", "[").replace("］", "]")
    return normalized.strip()


def _alias_key(label: str) -> str:
    """Return the direct, punctuation-normalized registry lookup key."""

    normalized = normalize_row_label(label).casefold()
    # Reference marks are presentation artifacts only in these narrow forms.
    normalized = re.sub(r"(?:\[(?:注)?\d+\]|\(注\d+\)|[¹²³⁴⁵⁶⁷⁸⁹])$", "", normalized)
    return normalized


def _without_row_ordinal(label: str) -> str | None:
    """Remove only a conventional leading statement row number for fallback."""

    match = re.match(r"^(?:[一二三四五六七八九十]+、|\d+[、.．])(.+)$", label)
    return match.group(1) if match else None


def _without_sign_convention_note(label: str) -> str | None:
    """Strip only standard profit/loss presentation notes, not row semantics."""

    match = re.match(r"^(.+?)\((?:亏损总额|净亏损|亏损)[^()]*填列\)$", label)
    return match.group(1) if match else None


class FinancialMetricRegistry:
    """Immutable lookup service for deterministic row-label normalization."""

    def __init__(
        self,
        definitions: Iterable[FinancialMetricDefinition],
        rules: Iterable[MetricAliasRule],
    ) -> None:
        definition_items = tuple(definitions)
        definitions_by_name = {item.canonical_name: item for item in definition_items}
        if len(definitions_by_name) != len(definition_items):
            raise ValueError("canonical metric names must be unique")
        rules_by_alias: dict[str, list[MetricAliasRule]] = {}
        for rule in rules:
            if rule.canonical_metric not in definitions_by_name:
                raise ValueError(f"alias targets unknown metric: {rule.canonical_metric}")
            rules_by_alias.setdefault(_alias_key(rule.alias), []).append(rule)
        self._definitions: Mapping[str, FinancialMetricDefinition] = MappingProxyType(definitions_by_name)
        self._rules: Mapping[str, tuple[MetricAliasRule, ...]] = MappingProxyType(
            {key: tuple(value) for key, value in rules_by_alias.items()}
        )

    @property
    def definitions(self) -> tuple[FinancialMetricDefinition, ...]:
        return tuple(self._definitions.values())

    def get(self, canonical_name: str) -> FinancialMetricDefinition | None:
        return self._definitions.get(canonical_name)

    def resolve_query_metric(self, query: str) -> QueryMetricResolution:
        """Resolve an explicit query phrase without fuzzy or semantic guessing.

        Longer declared aliases win over aliases contained inside them (for
        example, ``归母净利润`` over ``净利润``). If equally specific aliases
        point at different metrics, the result is ambiguous and callers must
        not select one arbitrarily.
        """

        normalized_query = unicodedata.normalize("NFKC", query).casefold()
        matches: list[tuple[int, int, MetricAliasRule]] = []
        query_rules = [rule for rules in self._rules.values() for rule in rules]
        for definition in self._definitions.values():
            query_rules.extend(
                MetricAliasRule(
                    alias=alias,
                    canonical_metric=definition.canonical_name,
                    statement_types=definition.statement_types,
                    status=MetricMappingStatus.SUPPORTED,
                    mapping_rule="registry_query_phrase_alias",
                )
                for alias in definition.query_aliases_zh + definition.query_aliases_en
            )
        for rule in query_rules:
            alias = unicodedata.normalize("NFKC", rule.alias).casefold().strip()
            if not alias:
                continue
            if re.search(r"[a-z0-9]", alias):
                expression = rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
                for match in re.finditer(expression, normalized_query):
                    matches.append((match.start(), match.end(), rule))
            else:
                for match in re.finditer(re.escape(alias), normalized_query):
                    matches.append((match.start(), match.end(), rule))

        if not matches:
            return QueryMetricResolution(None, MetricMappingStatus.UNMAPPED, reason="no_registry_query_alias")

        selected: list[tuple[int, int, MetricAliasRule]] = []
        for candidate in sorted(matches, key=lambda item: item[1] - item[0], reverse=True):
            start, end, _ = candidate
            if any(start >= chosen_start and end <= chosen_end for chosen_start, chosen_end, _ in selected):
                continue
            selected.append(candidate)
        targets = {rule.canonical_metric for _, _, rule in selected}
        if len(targets) != 1:
            return QueryMetricResolution(
                None,
                MetricMappingStatus.AMBIGUOUS,
                reason="equally_specific_aliases_resolve_to_multiple_metrics",
            )

        metric = next(iter(targets))
        definition = self._definitions[metric]
        matching_rules = [rule for _, _, rule in selected]
        aliases = {rule.alias for rule in matching_rules}
        return QueryMetricResolution(
            metric,
            MetricMappingStatus.EXACT if any(rule.status == MetricMappingStatus.EXACT for rule in matching_rules)
            else MetricMappingStatus.SUPPORTED,
            matched_alias=sorted(aliases, key=lambda value: (len(value), value.casefold()))[0],
            period_semantics=definition.period_semantics,
            reason="longest_registry_query_alias",
        )

    def normalize(
        self,
        row: FinancialTableRow,
        *,
        row_hierarchy: str | None = None,
    ) -> MetricNormalization:
        """Resolve a row only when its statement/context supports one metric.

        ``row_hierarchy`` is retained as evidence and may satisfy a future
        registry rule, but this initial registry has no hierarchy-dependent
        alias requiring inferred parent/child semantics.
        """

        original = row.row_label or ""
        normalized = normalize_row_label(original)
        evidence_parts = [f"statement_type={row.statement_type or 'unknown'}"]
        if row.table_title:
            evidence_parts.append(f"table_title={row.table_title}")
        if row_hierarchy:
            evidence_parts.append(f"row_hierarchy={row_hierarchy}")
        evidence = "; ".join(evidence_parts)

        if not original.strip():
            return _result(row, original, normalized, None, MetricMappingStatus.UNMAPPED, "empty_row_label", evidence)

        alias = _alias_key(original)
        rules = self._rules.get(alias, ())
        match_kind = "exact_alias"
        if not rules:
            unnumbered = _without_row_ordinal(normalized)
            if unnumbered:
                alias = _alias_key(unnumbered)
                rules = self._rules.get(alias, ())
                match_kind = "safe_row_ordinal_variant"
        if not rules:
            unnumbered = _without_row_ordinal(normalized) or normalized
            without_sign_note = _without_sign_convention_note(unnumbered)
            if without_sign_note:
                alias = _alias_key(without_sign_note)
                rules = self._rules.get(alias, ())
                match_kind = "safe_accounting_sign_note_variant"

        if not rules:
            # Generic words such as “现金” are explicitly recognized as
            # ambiguous rather than being silently assigned a cash concept.
            if alias in {"现金", "cash"}:
                return _result(
                    row, original, normalized, None, MetricMappingStatus.AMBIGUOUS, "ambiguous_cash_concept", evidence
                )
            return _result(row, original, normalized, None, MetricMappingStatus.UNMAPPED, "no_registry_alias", evidence)

        contextual: list[MetricAliasRule] = []
        wrong_statement: list[MetricAliasRule] = []
        for rule in rules:
            if rule.required_context and not _context_matches(rule.required_context, row, row_hierarchy):
                continue
            if row.statement_type not in rule.statement_types:
                wrong_statement.append(rule)
                continue
            contextual.append(rule)

        if not contextual:
            targets = sorted({rule.canonical_metric for rule in wrong_statement})
            return _result(
                row,
                original,
                normalized,
                None,
                MetricMappingStatus.UNMAPPED,
                "statement_type_mismatch" if wrong_statement else "context_not_proven",
                f"{evidence}; candidate_metrics={','.join(targets) or 'none'}",
            )

        targets = {rule.canonical_metric for rule in contextual}
        if len(targets) != 1:
            return _result(
                row,
                original,
                normalized,
                None,
                MetricMappingStatus.AMBIGUOUS,
                "multiple_contextual_metric_candidates",
                evidence,
            )
        rule = contextual[0]
        definition = self._definitions[rule.canonical_metric]
        if row.statement_type not in definition.statement_types:
            return _result(
                row,
                original,
                normalized,
                None,
                MetricMappingStatus.UNMAPPED,
                "definition_statement_constraint_failed",
                evidence,
            )
        if row.verification_status != VerificationStatus.VERIFIED:
            return _result(
                row,
                original,
                normalized,
                None,
                MetricMappingStatus.UNMAPPED,
                "source_row_not_structurally_verified",
                f"{evidence}; source_verification={row.verification_status.value}",
            )

        status = rule.status
        if match_kind != "exact_alias" and status == MetricMappingStatus.EXACT:
            status = MetricMappingStatus.SUPPORTED
        return _result(
            row,
            original,
            normalized,
            rule.canonical_metric,
            status,
            rule.mapping_rule if match_kind == "exact_alias" else match_kind,
            f"{evidence}; matched_alias={rule.alias}",
        )


def _context_matches(required: tuple[str, ...], row: FinancialTableRow, row_hierarchy: str | None) -> bool:
    context = " ".join((row.table_title or "", row.source_text or "", row_hierarchy or ""))
    folded = context.casefold()
    return all(term.casefold() in folded for term in required)


def _result(
    row: FinancialTableRow,
    original: str,
    normalized: str,
    metric: str | None,
    status: MetricMappingStatus,
    rule: str,
    evidence: str,
) -> MetricNormalization:
    return MetricNormalization(
        row=row,
        original_label=original,
        normalized_label=normalized,
        canonical_metric=metric,
        mapping_status=status,
        mapping_rule=rule,
        mapping_evidence=evidence,
    )


_BS = ("balance_sheet",)
_IS = ("income_statement",)
_CF = ("cash_flow_statement",)
_EQ = ("equity_statement",)


_DEFINITIONS = (
    FinancialMetricDefinition(
        "cash_and_bank_balances",
        "balance_sheet",
        _BS,
        ("货币资金",),
        ("cash and bank balances",),
        "scope is an observation dimension",
        "point_in_time",
        "monetary",
        "non_additive",
        "Chinese 货币资金 is not cash and cash equivalents.",
    ),
    FinancialMetricDefinition(
        "cash_and_cash_equivalents",
        "balance_sheet",
        _BS,
        ("现金及现金等价物",),
        ("cash and cash equivalents",),
        "scope is an observation dimension",
        "point_in_time",
        "monetary",
        "non_additive",
        "Distinct from Chinese balance-sheet 货币资金.",
    ),
    FinancialMetricDefinition(
        "total_assets",
        "balance_sheet",
        _BS,
        ("资产总计", "资产合计"),
        ("total assets",),
        "scope is an observation dimension",
        "point_in_time",
        "monetary",
        "non_additive",
        query_aliases_zh=("总资产",),
    ),
    FinancialMetricDefinition(
        "total_liabilities",
        "balance_sheet",
        _BS,
        ("负债合计", "负债总计"),
        ("total liabilities",),
        "scope is an observation dimension",
        "point_in_time",
        "monetary",
        "non_additive",
        "Not total debt.",
        query_aliases_zh=("总负债",),
    ),
    FinancialMetricDefinition(
        "total_equity",
        "balance_sheet",
        _BS + _EQ,
        ("所有者权益合计", "所有者权益（或股东权益）合计", "股东权益合计"),
        ("total equity", "total shareholders' equity"),
        "scope is an observation dimension",
        "point_in_time",
        "monetary",
        "non_additive",
        "Total equity, not parent-attributable equity.",
    ),
    FinancialMetricDefinition(
        "accounts_receivable",
        "balance_sheet",
        _BS,
        ("应收账款",),
        ("accounts receivable",),
        "scope is an observation dimension",
        "point_in_time",
        "monetary",
        "non_additive",
    ),
    FinancialMetricDefinition(
        "inventory",
        "balance_sheet",
        _BS,
        ("存货",),
        ("inventory",),
        "scope is an observation dimension",
        "point_in_time",
        "monetary",
        "non_additive",
    ),
    FinancialMetricDefinition(
        "fixed_assets",
        "balance_sheet",
        _BS,
        ("固定资产",),
        ("property, plant and equipment", "fixed assets"),
        "scope is an observation dimension",
        "point_in_time",
        "monetary",
        "non_additive",
        "Not capital expenditure.",
    ),
    FinancialMetricDefinition(
        "construction_in_progress",
        "balance_sheet",
        _BS,
        ("在建工程",),
        ("construction in progress",),
        "scope is an observation dimension",
        "point_in_time",
        "monetary",
        "non_additive",
        "Not capital expenditure.",
    ),
    FinancialMetricDefinition(
        "short_term_borrowings",
        "balance_sheet",
        _BS,
        ("短期借款",),
        ("short-term borrowings",),
        "scope is an observation dimension",
        "point_in_time",
        "monetary",
        "non_additive",
    ),
    FinancialMetricDefinition(
        "long_term_borrowings",
        "balance_sheet",
        _BS,
        ("长期借款",),
        ("long-term borrowings",),
        "scope is an observation dimension",
        "point_in_time",
        "monetary",
        "non_additive",
    ),
    FinancialMetricDefinition(
        "revenue",
        "income_statement",
        _IS,
        ("营业收入", "其中:营业收入"),
        ("revenue", "revenues", "total revenue", "total revenues"),
        "scope is an observation dimension",
        "duration",
        "monetary",
        "flow",
        "营业总收入 is kept separate.",
    ),
    FinancialMetricDefinition(
        "total_operating_revenue",
        "income_statement",
        _IS,
        ("营业总收入",),
        ("total operating revenue",),
        "scope is an observation dimension",
        "duration",
        "monetary",
        "flow",
        "Not assumed synonymous with 营业收入.",
    ),
    FinancialMetricDefinition(
        "cost_of_revenue",
        "income_statement",
        _IS,
        ("营业成本", "其中:营业成本"),
        ("cost of revenue", "cost of revenues", "cost of sales"),
        "scope is an observation dimension",
        "duration",
        "monetary",
        "flow",
    ),
    FinancialMetricDefinition(
        "operating_income",
        "income_statement",
        _IS,
        ("营业利润",),
        ("operating income", "operating profit", "income from operations"),
        "scope is an observation dimension",
        "duration",
        "monetary",
        "flow",
        "Uses existing project naming convention.",
    ),
    FinancialMetricDefinition(
        "total_profit",
        "income_statement",
        _IS,
        ("利润总额",),
        ("total profit", "profit before tax"),
        "scope is an observation dimension",
        "duration",
        "monetary",
        "flow",
    ),
    FinancialMetricDefinition(
        "net_income",
        "income_statement",
        _IS,
        ("净利润",),
        ("net income", "net profit"),
        "scope is an observation dimension",
        "duration",
        "monetary",
        "flow",
        "Consolidated/parent scope remains separate from metric identity.",
    ),
    FinancialMetricDefinition(
        "attributable_net_income",
        "income_statement",
        _IS,
        ("归属于母公司所有者的净利润", "归属于母公司股东的净利润", "归母净利润"),
        ("net income attributable to parent", "profit attributable to owners of the parent"),
        "scope is an observation dimension",
        "duration",
        "monetary",
        "flow",
        "Kept distinct from net_income; follows current project convention.",
    ),
    FinancialMetricDefinition(
        "r_and_d_expense",
        "income_statement",
        _IS,
        ("研发费用",),
        ("research and development expense", "r&d expense"),
        "scope is an observation dimension",
        "duration",
        "monetary",
        "flow",
    ),
    FinancialMetricDefinition(
        "selling_expense",
        "income_statement",
        _IS,
        ("销售费用",),
        ("selling expense", "selling expenses"),
        "scope is an observation dimension",
        "duration",
        "monetary",
        "flow",
    ),
    FinancialMetricDefinition(
        "administrative_expense",
        "income_statement",
        _IS,
        ("管理费用",),
        ("administrative expense",),
        "scope is an observation dimension",
        "duration",
        "monetary",
        "flow",
    ),
    FinancialMetricDefinition(
        "finance_expense",
        "income_statement",
        _IS,
        ("财务费用",),
        ("finance expense", "financial expenses"),
        "scope is an observation dimension",
        "duration",
        "monetary",
        "flow",
    ),
    FinancialMetricDefinition(
        "operating_cash_flow",
        "cash_flow_statement",
        _CF,
        ("经营活动产生的现金流量净额",),
        ("net cash from operating activities", "operating cash flow"),
        "scope is an observation dimension",
        "duration",
        "monetary",
        "flow",
        "Not free cash flow.",
        query_aliases_zh=("经营活动现金流量净额", "经营活动现金流净额"),
    ),
    FinancialMetricDefinition(
        "investing_cash_flow",
        "cash_flow_statement",
        _CF,
        ("投资活动产生的现金流量净额",),
        ("net cash from investing activities", "investing cash flow"),
        "scope is an observation dimension",
        "duration",
        "monetary",
        "flow",
    ),
    FinancialMetricDefinition(
        "financing_cash_flow",
        "cash_flow_statement",
        _CF,
        ("筹资活动产生的现金流量净额",),
        ("net cash from financing activities", "financing cash flow"),
        "scope is an observation dimension",
        "duration",
        "monetary",
        "flow",
    ),
    FinancialMetricDefinition(
        "cash_and_cash_equivalents_net_increase",
        "cash_flow_statement",
        _CF,
        ("现金及现金等价物净增加额",),
        ("net increase in cash and cash equivalents",),
        "scope is an observation dimension",
        "duration",
        "monetary",
        "flow",
    ),
    FinancialMetricDefinition(
        "cash_and_cash_equivalents_beginning",
        "cash_flow_statement",
        _CF,
        ("期初现金及现金等价物余额", "加:期初现金及现金等价物余额"),
        ("beginning cash and cash equivalents",),
        "scope is an observation dimension",
        "point_in_time",
        "monetary",
        "non_additive",
    ),
    FinancialMetricDefinition(
        "cash_and_cash_equivalents_ending",
        "cash_flow_statement",
        _CF,
        ("期末现金及现金等价物余额",),
        ("ending cash and cash equivalents", "cash and cash equivalents at end of period"),
        "scope is an observation dimension",
        "point_in_time",
        "monetary",
        "non_additive",
    ),
    FinancialMetricDefinition(
        "equity_attributable_to_parent",
        "equity_statement",
        _BS + _EQ,
        ("归属于母公司所有者权益合计", "归属于母公司所有者权益", "归属于母公司股东权益合计"),
        ("equity attributable to owners of parent", "parent shareholders' equity"),
        "scope is an observation dimension",
        "point_in_time",
        "monetary",
        "non_additive",
    ),
    FinancialMetricDefinition(
        "minority_interest",
        "balance_sheet",
        _BS + _EQ,
        ("少数股东权益",),
        ("non-controlling interests", "minority interest"),
        "scope is an observation dimension",
        "point_in_time",
        "monetary",
        "non_additive",
    ),
)


def _rules_from_definitions() -> tuple[MetricAliasRule, ...]:
    rules: list[MetricAliasRule] = []
    for definition in _DEFINITIONS:
        for index, alias in enumerate(definition.aliases_zh + definition.aliases_en):
            # The first alias is the registry's primary form. Other explicitly
            # listed forms are supported synonyms, not fuzzy matches.
            status = MetricMappingStatus.EXACT if index == 0 else MetricMappingStatus.SUPPORTED
            rules.append(
                MetricAliasRule(
                    alias=alias,
                    canonical_metric=definition.canonical_name,
                    statement_types=definition.statement_types,
                    status=status,
                    mapping_rule=(
                        "registry_primary_alias" if status == MetricMappingStatus.EXACT else "registry_supported_alias"
                    ),
                )
            )
    return tuple(rules)


FINANCIAL_METRIC_REGISTRY = FinancialMetricRegistry(_DEFINITIONS, _rules_from_definitions())


def normalize_financial_table_row(row: FinancialTableRow, *, row_hierarchy: str | None = None) -> MetricNormalization:
    """Public registry API for one structurally reconstructed row."""

    return FINANCIAL_METRIC_REGISTRY.normalize(row, row_hierarchy=row_hierarchy)


def normalize_financial_table_rows(
    rows: Iterable[FinancialTableRow],
) -> tuple[MetricNormalization, ...]:
    """Normalize multiple rows without merging their scope or period."""

    return tuple(normalize_financial_table_row(row) for row in rows)


def extract_explicit_fiscal_year(query: str) -> str | None:
    """Return one explicit 20xx year; refuse queries naming multiple years."""

    years = tuple(dict.fromkeys(re.findall(r"(?<!\d)(20\d{2})(?!\d)", unicodedata.normalize("NFKC", query))))
    return years[0] if len(years) == 1 else None
