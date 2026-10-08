"""Local selected-node evidence allocation, independent of selector and build.

Lexical relevance is navigation, not a correctness proof. Coverage is deliberately
limited to understood affirmative narrative disclosures; other needs stay UNKNOWN.
"""

import re
from time import perf_counter

from retrieval.adaptive_contract import CoverageReport

_TERMS = re.compile(r"[^\W_]+", re.UNICODE)
_HAN = re.compile(r"[\u3400-\u9fff]+")
_NEGATED = re.compile(r"(?:无法|不能|未能|没有|未披露|不涉及|并非|不是|尚未|未说明|未提供|不存在|未知|待确认)|"
                      r"\b(?:not|no|unknown|unavailable|undisclosed|cannot)\b", re.I)
_ASPECTS = {
    "MAIN_BUSINESS_DESCRIPTION": (
        re.compile(r"(?:主要业务|主营业务|principal business|main business|primary business)", re.I),
        re.compile(r"(?:主要业务|主营业务)(?:包括|为|是|涉及|涵盖|集中于|以)|"
                   r"(?:principal|main|primary) business (?:is|includes|consists of|involves)\s+\w", re.I),
    ),
    "RISK_DESCRIPTION": (
        re.compile(r"(?:风险|risk factors?|principal risks?)", re.I),
        re.compile(r"(?:面临|存在|可能导致|受到).{0,40}风险|风险(?:包括|主要为|来自|在于)|"
                   r"(?:risks? (?:include|arise|involve)|faces? .{0,40}risk)\b", re.I),
    ),
}


def _terms(text):
    """Small local token matcher; no dependency on mixed Hybrid tokenizer work."""
    terms = set(_TERMS.findall(text.casefold()))
    for run in _HAN.findall(text):
        terms.update(run[i:i + 2] for i in range(len(run) - 1))
    return terms


def information_needs(request):
    if request.required_aspects:
        return request.required_aspects
    # Do not claim to decompose quantitative, period/scope-constrained requests.
    if request.metric or request.period or request.fiscal_year or request.scope:
        return ()
    query = request.scoped.query
    if re.search(r"多少|金额|占比|同比|增长|收入|利润|资产|审计|"
                 r"how much|percentage|growth|revenue|profit", query, re.I):
        return ()
    return tuple(aspect for aspect, (mention, _) in _ASPECTS.items() if mention.search(query))


def _supports(block, aspect):
    if aspect not in _ASPECTS or str(block.block_type) != "TEXT":
        return False
    # Evaluate declarative sentences only; context/headings cannot supply facts.
    for sentence in re.split(r"[。.!！\n]", block.text):
        if ("?" not in sentence and "？" not in sentence and not _NEGATED.search(sentence)
                and _ASPECTS[aspect][1].search(sentence)):
            return True
    return False


def coverage_for(required, blocks):
    covered = tuple(aspect for aspect in required if any(_supports(b, aspect) for b in blocks))
    missing = tuple(aspect for aspect in required if aspect not in covered)
    if not required or any(aspect not in _ASPECTS for aspect in required):
        return CoverageReport(required, covered, missing), "UNKNOWN"
    ratio = len(covered) / len(required)
    return (CoverageReport(required, covered, missing, ratio, not missing),
            "SATISFIED" if not missing else ("PARTIAL" if covered else "INSUFFICIENT"))


def select_source_blocks(request, blocks, candidate_ids):
    started = perf_counter()
    required = information_needs(request)
    query_terms = _terms(request.scoped.query)
    rows = []
    for block_id in candidate_ids:
        block = blocks[block_id]
        body_terms = _terms(block.text)
        context_terms = _terms(block.section or "")
        matched = tuple(aspect for aspect in required if _supports(block, aspect))
        lexical = len(query_terms & body_terms) / max(1, len(query_terms))
        context = len(query_terms & context_terms) / max(1, len(query_terms))
        # Body overlap outranks a heading context alone; coverage proof dominates.
        score = lexical + 0.15 * context
        if str(block.block_type) == "TITLE":
            score *= 0.25
        rows.append({"block_id": block_id, "score": score, "aspects": matched,
                     "reason": "INFORMATION_NEED_MATCH" if matched else
                     ("LEXICAL_MATCH" if lexical else "HEADING_CONTEXT" if context else "NO_MATCH")})
    chosen, covered = [], set()
    pending = list(rows)
    if required and all(aspect in _ASPECTS for aspect in required) and any(row["aspects"] for row in rows):
        # top_k is a ceiling, not a quota. Do not dilute a supported disclosure
        # with cover/header matches merely to fill unused slots. If nothing is
        # proven, retain ranked diagnostic evidence but never mark it satisfied.
        pending = [row for row in rows if row["aspects"]]
    while pending and len(chosen) < request.scoped.top_k:
        best = min(pending, key=lambda row: (
            -len(set(row["aspects"]) - covered), -len(row["aspects"]), -row["score"],
            blocks[row["block_id"]].page, blocks[row["block_id"]].reading_order, row["block_id"],
        ))
        pending.remove(best)
        chosen.append(best["block_id"])
        covered.update(best["aspects"])
    coverage, status = coverage_for(required, [blocks[i] for i in chosen])
    trace = {
        "candidate_block_count": len(rows), "candidate_source_block_ids": list(candidate_ids),
        "selected_evidence_block_ids": chosen,
        "rejected_block_ids": [r["block_id"] for r in rows if r["block_id"] not in chosen],
        "candidate_scores": rows, "coverage_status": status,
        "required_aspects": list(required), "covered_aspects": list(coverage.covered_aspects),
        "missing_aspects": list(coverage.missing_aspects), "top_k": request.scoped.top_k,
        "selection_elapsed_ms": (perf_counter() - started) * 1000,
        "evidence_blocks_returned": len(chosen), "evidence_selection_provider_calls": 0,
    }
    return chosen, coverage, trace
