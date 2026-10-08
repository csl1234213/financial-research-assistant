"""Feature-driven policies and explicit, inspectable registries."""

from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass

from .models import DocumentProfile, FailureClass, FormatFamily, PageFeatures


@dataclass(frozen=True)
class ParserCapability:
    parser_id: str
    parser_version: str
    capabilities: tuple[tuple[str, str], ...]
    available: bool = True
    region_supported: bool = False


class ParserCapabilityRegistry:
    def __init__(self, *, ocr_available: bool = False):
        version = importlib.metadata.version("PyMuPDF")
        self.parsers = {
            "pymupdf-native": ParserCapability(
                "pymupdf-native",
                version,
                (("native_text", "HIGH"), ("geometry", "HIGH"), ("scan", "NONE")),
                region_supported=True,
            ),
            "pymupdf-table": ParserCapability(
                "pymupdf-table",
                version,
                (("table_structure", "MEDIUM"), ("narrative", "NONE")),
                region_supported=True,
            ),
            "existing-layout": ParserCapability(
                "existing-layout",
                "column-reading-order-v1",
                (("multi_column", "MEDIUM"), ("numeric_authority", "NONE")),
            ),
            "tesseract": ParserCapability(
                "tesseract",
                f"via-pymupdf-{version}",
                (("scan", "HIGH"), ("native_financial_number_trust", "LOW")),
                available=ocr_available,
                region_supported=True,
            ),
        }

    def get(self, parser_id: str) -> ParserCapability:
        return self.parsers[parser_id]


@dataclass(frozen=True)
class PageParsingPlan:
    page: int
    primary: str
    helpers: tuple[str, ...]
    shadow: str | None
    recovery: str | None
    reason: str


@dataclass(frozen=True)
class ParserPolicy:
    version: str
    recover_native_orphans: bool
    recover_headers: bool
    permit_ocr: bool
    minimum_reading_confidence: float = 0.8
    audit_geometry_context: bool = False
    prove_native_merged_regions: bool = False


# Both are executable policies introduced here. v1 is an observation baseline,
# not a claim that historical production documents ran this compatibility gate.
POLICIES = {
    "financial-pdf-v1-observe": ParserPolicy("financial-pdf-v1-observe", False, False, False),
    "financial-pdf-v2": ParserPolicy("financial-pdf-v2", True, True, True),
    "financial-pdf-v3": ParserPolicy("financial-pdf-v3", True, True, True, audit_geometry_context=True),
    "financial-pdf-v4": ParserPolicy("financial-pdf-v4", True, True, True,
                                    audit_geometry_context=True, prove_native_merged_regions=True),
}
DEFAULT_POLICY = POLICIES["financial-pdf-v4"]


class ParserPolicyEngine:
    def plan(self, profile: DocumentProfile, page: PageFeatures, registry: ParserCapabilityRegistry) -> PageParsingPlan:
        if FormatFamily.UNKNOWN in profile.format_families:
            return PageParsingPlan(page.page, "none", (), None, "QUARANTINE", "unknown profile")
        if page.blank:
            return PageParsingPlan(page.page, "pymupdf-native", (), None, None, "verified blank page")
        if page.ocr_required:
            available = registry.get("tesseract").available
            return PageParsingPlan(
                page.page,
                "pymupdf-native" if page.has_native else "tesseract",
                (),
                None,
                "OCR_REGION" if page.has_native and available else "OCR_PAGE" if available else "QUARANTINE",
                "image region requires OCR; retain native authority",
            )
        helpers = tuple(
            name
            for name, active in (
                ("pymupdf-table", page.table_density > 0),
                ("existing-layout", page.column_count > 1),
            )
            if active
        )
        return PageParsingPlan(page.page, "pymupdf-native", helpers, None, None, "native source available")


@dataclass(frozen=True)
class RecoveryPolicy:
    policy_id: str
    failure_class: FailureClass
    action: str
    version: str = "1"


class RecoveryPolicyRegistry:
    def __init__(self):
        self.policies = {
            failure: RecoveryPolicy(failure.value.lower(), failure, action)
            for failure, action in {
                FailureClass.NO_NATIVE_TEXT: "OCR_PAGE",
                FailureClass.OCR_REQUIRED: "OCR_REGION",
                FailureClass.ORPHAN_TEXT: "REGION_RECOVERY",
                FailureClass.CRITICAL_FINANCIAL_CONTENT_LOSS: "REGION_RECOVERY",
                FailureClass.CROSS_PAGE_TABLE_HEADER_LOSS: "TABLE_CONTEXT_INHERITANCE",
                FailureClass.MULTICOLUMN_READING_ORDER_ERROR: "MANUAL_REVIEW_REQUIRED",
                # No independently validated table repair is installed yet.
                FailureClass.TABLE_STRUCTURE_LOSS: "MANUAL_REVIEW_REQUIRED",
                FailureClass.NATIVE_OCR_NUMERIC_CONFLICT: "RETAIN_NATIVE",
            }.items()
        }

    def route(self, failure: FailureClass) -> RecoveryPolicy:
        return self.policies.get(failure, RecoveryPolicy("quarantine", failure, "QUARANTINE"))


class FailureSignatureRegistry:
    """Only validated feature signatures select automatic recovery."""

    signatures = {
        FailureClass.ORPHAN_TEXT: ("trusted_native_source",),
        FailureClass.CRITICAL_FINANCIAL_CONTENT_LOSS: ("trusted_native_source",),
        FailureClass.CROSS_PAGE_TABLE_HEADER_LOSS: ("adjacent_page", "matching_columns", "same_section"),
    }

    def supports(self, failure: FailureClass, features: dict[str, str]) -> bool:
        required = self.signatures.get(failure)
        return bool(required) and all(features.get(key) == "true" for key in required)

    def records(self) -> tuple[dict, ...]:
        """Code-reviewed offline signature store; never learns rules from documents."""
        registry = RecoveryPolicyRegistry()
        return tuple(
            {
                "failure_class": failure.value,
                "required_features": {key: "true" for key in required},
                "parser": "pymupdf-native" if "trusted_native_source" in required else "pymupdf-table",
                "recovery_strategy": registry.route(failure).action,
                "recovery_version": registry.route(failure).version,
                "regression_fixtures": (
                    ["critical-row-loss-alpha", "critical-row-loss-beta"]
                    if failure == FailureClass.CRITICAL_FINANCIAL_CONTENT_LOSS
                    else ["orphan-text-alpha", "orphan-text-beta"]
                    if failure == FailureClass.ORPHAN_TEXT
                    else ["cross-page-table-alpha", "cross-page-table-beta"]
                ),
            }
            for failure, required in self.signatures.items()
        )


@dataclass(frozen=True)
class DocumentQualityContract:
    family: FormatFamily
    required_statements: tuple[str, ...] = ()
    recommended_statements: tuple[str, ...] = ()


class DocumentQualityContractRegistry:
    def __init__(self):
        self.contracts = {family: DocumentQualityContract(family) for family in FormatFamily}
        self.contracts[FormatFamily.CAS_ANNUAL_REPORT] = DocumentQualityContract(
            FormatFamily.CAS_ANNUAL_REPORT,
            ("balance_sheet", "income_statement", "cash_flow_statement"),
            ("equity_statement",),
        )

    def for_profile(self, profile: DocumentProfile) -> tuple[DocumentQualityContract, ...]:
        return tuple(self.contracts[family] for family in profile.format_families)
