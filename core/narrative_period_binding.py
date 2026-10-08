"""Conservative report-year admission, distinct from observation-period identity."""

import re
from collections.abc import Mapping

_YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_REPORT = re.compile(
    r"(?<!\d)(20\d{2})\s*年?(?:年度报告|年报)|"
    r"\b(?:FY\s*)?(20\d{2})\s+annual\s+report\b", re.I)


def narrative_period_is_bound(question: str, payload: Mapping) -> bool:
    """Never copy cover/report identity into a financial observation period.

    For a mixed-period query, require each explicitly requested kind of binding.
    Missing evidence is not inferred from the text or document filename.
    """
    years = set(_YEAR.findall(question))
    if not years:
        return True
    report_matches = tuple(_REPORT.finditer(question))
    report_years = {next(value for value in match.groups() if value)
                    for match in report_matches}
    # The same year can occur once as report identity and once as a fact period.
    # Subtracting sets of year values would silently drop the latter obligation.
    observation_years = {match.group(1) for match in _YEAR.finditer(question)
                         if not any(report.start() <= match.start() < report.end()
                                    for report in report_matches)}
    provenance = payload.get("provenance", {})
    report_period = provenance.get("report_period") if isinstance(provenance, Mapping) else None
    report_match = (re.fullmatch(r"FY(20\d{2})", report_period)
                    if isinstance(report_period, str) else None)
    if report_years and (not report_match or report_match.group(1) not in report_years):
        return False
    period = payload.get("period", {})
    observation_year = period.get("fiscal_year") if isinstance(period, Mapping) else None
    return not observation_years or observation_year in observation_years
