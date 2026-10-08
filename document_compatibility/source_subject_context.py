"""Shared source-structural authority; no index enhancement or Answer dependency."""

import re

SUBJECT_CONTEXT_VERSION = "explicit-same-page-owner-header.v1"


def explicitly_named_subject(context_text):
    """Extract only a name bounded by explicit adjacent table labels."""
    match = re.search(r"名称\s+([^\n]+?)\s+(?:单位负责人|法定代表人|成立日期)", context_text)
    return match.group(1).strip() if match else None


def controlling_shareholder_contexts(chunks):
    """Keep explicit same-page ancestor headers; never infer an issuer subject.

    Cross-page inheritance and unidentified entities deliberately remain unknown.
    Chunk order is the parser's source order, not retrieval ranking.
    """
    result = []
    active = None
    previous_page = None
    for chunk in chunks:
        page, text = chunk.get("page"), chunk.get("text", "")
        section = chunk.get("section", "")
        if page != previous_page:
            active = None
        previous_page = page
        if (re.search(r"控股股东情况|controlling shareholder information", section, re.I)
                and re.search(r"名称|name", text, re.I)
                and len(text) <= 4096):
            active = {"role": "CONTROLLING_SHAREHOLDER", "page": page,
                      "context_text": text, "rule": SUBJECT_CONTEXT_VERSION}
        elif re.match(r"^(?:[一二三四五六七八九十]+[、.]|[IVX]+\.)", section):
            active = None
        result.append(dict(active) if active else None)
    return tuple(result)
