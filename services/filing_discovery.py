"""Safe discovery and download of official company filings.

SEC filings are resolved through SEC's public company index and submissions
API.  Mainland A-share annual reports are resolved through CNINFO's public
company/announcement APIs and downloaded only from its static PDF host.  Both
sources return normal ingestion artifacts; no filing content is injected into
chat responses directly.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

SEC_INDEX_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
SEC_ALLOWED_HOSTS = frozenset({"www.sec.gov", "data.sec.gov"})
CNINFO_COMPANY_SEARCH_URL = "https://www.cninfo.com.cn/new/information/topSearch/query"
CNINFO_ANNOUNCEMENT_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_PDF_BASE_URL = "https://static.cninfo.com.cn/"
CNINFO_ALLOWED_HOSTS = frozenset({"www.cninfo.com.cn", "static.cninfo.com.cn"})
MAX_FILING_BYTES = 25 * 1024 * 1024
MAX_CNINFO_RESPONSE_BYTES = 5 * 1024 * 1024
_SAFE_DOCUMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,240}$")
_SAFE_ACCESSION = re.compile(r"^[0-9]{18}$")
_SAFE_CNINFO_CODE = re.compile(r"^(?:\d{6})(?:\.(?:SH|SZ|BJ))?$", re.IGNORECASE)
_SAFE_CNINFO_ORG = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
_SAFE_CNINFO_ARTIFACT = re.compile(r"^finalpage/\d{4}-\d{2}-\d{2}/\d{6,20}\.PDF$", re.IGNORECASE)
_CJK = re.compile(r"[\u3400-\u9fff]")


class FilingDiscoveryError(RuntimeError):
    """A safe, user-facing discovery failure."""


class FilingNotFound(FilingDiscoveryError):
    """No uniquely matched company or requested filing was found."""


@dataclass(frozen=True)
class DiscoveredFiling:
    company: str
    cik: str
    form: str
    filing_date: str
    report_date: str
    filename: str
    source_url: str
    content: bytes
    source_type: str = "sec_edgar"
    stock_code: str | None = None
    exchange: str | None = None
    report_type: str | None = None
    report_year: int | None = None
    audited: bool = False


def _normalise(value: str) -> str:
    return "".join(char for char in unescape(value).casefold() if char.isalnum())


def _user_agent() -> str:
    return os.environ.get(
        "SEC_USER_AGENT",
        "financial-rag-assistant/8.2 (contact: financial-rag-assistant@example.com)",
    ).strip()


def _assert_sec_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in SEC_ALLOWED_HOSTS:
        raise FilingDiscoveryError("SEC discovery returned an untrusted URL")


def _fetch(url: str, *, max_bytes: int | None = None) -> bytes:
    _assert_sec_url(url)
    request = Request(
        url,
        headers={
            "Accept": "application/json, text/html;q=0.9",
            "User-Agent": _user_agent(),
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=15) as response:  # noqa: S310 - URL is allowlisted above.
            _assert_sec_url(response.geturl())
            content_length = response.headers.get("Content-Length")
            if max_bytes is not None and content_length and int(content_length) > max_bytes:
                raise FilingDiscoveryError("SEC filing exceeds the configured download limit")
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if max_bytes is not None and size > max_bytes:
                    raise FilingDiscoveryError("SEC filing exceeds the configured download limit")
                chunks.append(chunk)
            return b"".join(chunks)
    except FilingDiscoveryError:
        raise
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise FilingDiscoveryError("SEC filing service is temporarily unavailable") from exc


def _assert_cninfo_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in CNINFO_ALLOWED_HOSTS:
        raise FilingDiscoveryError("CNINFO discovery returned an untrusted URL")


def _cninfo_fetch(url: str, *, form: dict[str, str] | None = None,
                  max_bytes: int = MAX_CNINFO_RESPONSE_BYTES) -> bytes:
    """Fetch a bounded CNINFO response from an explicitly allowlisted host."""

    _assert_cninfo_url(url)
    data = urlencode(form).encode("utf-8") if form is not None else None
    request = Request(
        url,
        data=data,
        headers={
            "Accept": "application/json, application/pdf;q=0.9, */*;q=0.5",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
            if form is not None else "application/octet-stream",
            "Referer": "https://www.cninfo.com.cn/",
            "User-Agent": "financial-rag-assistant/8.2 (public filing discovery)",
        },
        method="POST" if form is not None else "GET",
    )
    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310 - allowlisted above.
            _assert_cninfo_url(response.geturl())
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                raise FilingDiscoveryError("CNINFO response exceeds the configured size limit")
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise FilingDiscoveryError("CNINFO response exceeds the configured size limit")
                chunks.append(chunk)
            return b"".join(chunks)
    except FilingDiscoveryError:
        raise
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise FilingDiscoveryError("CNINFO filing service is temporarily unavailable") from exc


def _cninfo_json(url: str, form: dict[str, str]) -> object:
    try:
        return json.loads(_cninfo_fetch(url, form=form).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FilingDiscoveryError("CNINFO returned invalid JSON") from exc


def _cninfo_market(code: str) -> str:
    digits = code[:6]
    if digits.startswith(("60", "68", "90")):
        return "sse"
    if digits.startswith(("00", "30", "20")):
        return "szse"
    if digits.startswith(("43", "83", "87", "88", "92")):
        return "bj"
    raise FilingNotFound("The matched issuer is not a supported mainland A-share company")


def _resolve_cninfo_company(company: str) -> tuple[str, str, str, str]:
    query = company.strip()
    if not query:
        raise FilingNotFound("A company name or A-share code is required")
    code_query = query.upper().split(".", maxsplit=1)[0]
    is_code = bool(_SAFE_CNINFO_CODE.fullmatch(query))
    payload = _cninfo_json(
        CNINFO_COMPANY_SEARCH_URL,
        {"keyWord": code_query if is_code else query, "maxNum": "20"},
    )
    if not isinstance(payload, list):
        raise FilingDiscoveryError("CNINFO company search returned an unexpected response")
    matches: list[tuple[str, str, str, str]] = []
    normal_query = _normalise(query)
    for row in payload:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code", "")).strip()
        org_id = str(row.get("orgId", "")).strip()
        title = str(row.get("zwjc") or row.get("fullName") or row.get("zwjc2") or "").strip()
        category = str(row.get("category", ""))
        if not re.fullmatch(r"\d{6}", code) or not _SAFE_CNINFO_ORG.fullmatch(org_id):
            continue
        if "A股" not in category:
            continue
        try:
            market = _cninfo_market(code)
        except FilingNotFound:
            continue
        exact = code == code_query if is_code else _normalise(title) == normal_query
        if exact and title:
            matches.append((code, org_id, title, market))
    unique = {(code, org, title, market) for code, org, title, market in matches}
    if len(unique) != 1:
        if unique:
            raise FilingNotFound("The A-share company name matched multiple issuers")
        raise FilingNotFound("No exact mainland A-share company match was found")
    code, org_id, title, market = next(iter(unique))
    requested_exchange = query.rsplit(".", maxsplit=1)[1].lower() if is_code and "." in query else None
    expected_exchange = {"sh": "sse", "sz": "szse", "bj": "bj"}.get(requested_exchange or "")
    if expected_exchange is not None and expected_exchange != market:
        raise FilingNotFound("The A-share ticker suffix does not match the issuer exchange")
    return title, code, org_id, market


def _latest_cninfo_annual(company: str, code: str, org_id: str, market: str) -> dict[str, object]:
    from datetime import datetime, timedelta

    today = date.today()
    start = f"{today.year - 5}-01-01"
    end = today.isoformat()
    payload = _cninfo_json(
        CNINFO_ANNOUNCEMENT_URL,
        {
            "stock": f"{code},{org_id}",
            "tabName": "fulltext",
            "pageSize": "30",
            "pageNum": "1",
            "column": market,
            "category": "category_ndbg_szsh",
            "seDate": f"{start}~{end}",
            "isHLtitle": "true",
        },
    )
    announcements = payload.get("announcements") if isinstance(payload, dict) else None
    if not isinstance(announcements, list):
        raise FilingDiscoveryError("CNINFO annual report search returned an unexpected response")
    candidates: list[tuple[date, int, str, str]] = []
    for row in announcements:
        if not isinstance(row, dict):
            continue
        title = str(row.get("announcementTitle", "")).strip()
        # Only the full Chinese annual report is eligible. Exclude summaries,
        # English editions, ESG reports, and all interim/quarterly filings.
        if "年度报告" not in title or any(term in title for term in ("摘要", "英文", "ESG", "社会责任")):
            continue
        match = re.search(r"(20\d{2})年年度报告(?:全文)?", title)
        if not match:
            continue
        report_year = int(match.group(1))
        adjunct = str(row.get("adjunctUrl", "")).strip()
        if not _SAFE_CNINFO_ARTIFACT.fullmatch(adjunct):
            continue
        raw_timestamp = row.get("announcementTime")
        try:
            timestamp = int(raw_timestamp) / 1000
            filing_day = datetime.fromtimestamp(timestamp).date()
        except (TypeError, ValueError, OSError, OverflowError):
            day_match = re.search(r"(20\d{2}-\d{2}-\d{2})", adjunct)
            if not day_match:
                continue
            filing_day = date.fromisoformat(day_match.group(1))
        if filing_day > today or filing_day < today - timedelta(days=6 * 366):
            continue
        candidates.append((filing_day, report_year, title, adjunct))
    if not candidates:
        raise FilingNotFound(f"No full audited annual report was found for {company}")
    latest = max(candidates, key=lambda item: (item[0], item[1]))
    return {
        "filing_day": latest[0],
        "report_year": latest[1],
        "title": latest[2],
        "adjunct": latest[3],
    }


def _verify_cninfo_audited_pdf(content: bytes) -> bool:
    if not content.startswith(b"%PDF-"):
        raise FilingDiscoveryError("CNINFO download was not a PDF document")
    try:
        import fitz

        with fitz.open(stream=content, filetype="pdf") as pdf:
            if pdf.page_count < 2:
                raise FilingDiscoveryError("CNINFO annual report PDF is incomplete")
            has_audit_section = any("审计报告" in page.get_text() for page in pdf)
    except FilingDiscoveryError:
        raise
    except Exception as exc:
        raise FilingDiscoveryError("CNINFO annual report PDF could not be verified") from exc
    if not has_audit_section:
        raise FilingDiscoveryError("CNINFO annual report does not contain a readable audit report section")
    return True


def discover_latest_cninfo_annual_report(company: str) -> DiscoveredFiling:
    """Download the newest full mainland A-share annual report containing an audit section."""

    issuer, code, org_id, market = _resolve_cninfo_company(company)
    row = _latest_cninfo_annual(issuer, code, org_id, market)
    source_url = CNINFO_PDF_BASE_URL + str(row["adjunct"])
    _assert_cninfo_url(source_url)
    content = _cninfo_fetch(source_url, max_bytes=MAX_FILING_BYTES)
    audited = _verify_cninfo_audited_pdf(content)
    filing_day = row["filing_day"]
    filename = f"{issuer}_{row['report_year']}年度报告_审计_{filing_day.isoformat()}.pdf"
    return DiscoveredFiling(
        company=issuer,
        cik=code,
        form="ANNUAL",
        filing_date=filing_day.isoformat(),
        report_date=f"{row['report_year']}-12-31",
        filename=filename,
        source_url=source_url,
        content=content,
        source_type="cninfo",
        stock_code=code,
        exchange=market,
        report_type="annual",
        report_year=int(row["report_year"]),
        audited=audited,
    )


def discover_latest_company_filing(company: str) -> DiscoveredFiling:
    """Route Chinese issuer names/A-share tickers to audited CNINFO annual reports."""

    if _CJK.search(company) or _SAFE_CNINFO_CODE.fullmatch(company.strip()):
        return discover_latest_cninfo_annual_report(company)
    try:
        return discover_latest_sec_filing(company)
    except FilingNotFound:
        # Latin aliases of mainland issuers are not guessed: they must match
        # exactly through CNINFO rather than a fuzzy translated-name search.
        raise


def _lookup_company(company: str) -> tuple[str, str]:
    query = _normalise(company.strip())
    if not query:
        raise FilingNotFound("A company name is required")
    try:
        raw = json.loads(_fetch(SEC_INDEX_URL).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FilingDiscoveryError("SEC company index returned invalid data") from exc

    candidates: list[tuple[int, str, str]] = []
    for row in raw.values() if isinstance(raw, dict) else []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title", "")).strip()
        ticker = str(row.get("ticker", "")).strip()
        cik_value = row.get("cik_str")
        if not title or cik_value is None:
            continue
        title_key = _normalise(title)
        ticker_key = _normalise(ticker)
        score = 0
        if query == ticker_key:
            score = 100
        elif query == title_key:
            score = 90
        elif title_key.startswith(query):
            score = 80
        elif query in title_key:
            score = 70
        elif query in ticker_key:
            score = 60
        if score:
            candidates.append((score, title, str(int(cik_value)).zfill(10)))
    if not candidates:
        raise FilingNotFound("No SEC company matched the requested name")
    candidates.sort(key=lambda item: (-item[0], item[1]))
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0] and candidates[0][1] != candidates[1][1]:
        raise FilingNotFound("The company name matched multiple SEC issuers")
    _, title, cik = candidates[0]
    return title, cik


def discover_latest_sec_filing(company: str, *, forms: tuple[str, ...] = ("10-K", "10-Q")) -> DiscoveredFiling:
    """Find and download the newest allowed SEC filing for *company*."""

    issuer, cik = _lookup_company(company)
    try:
        submissions = json.loads(
            _fetch(SEC_SUBMISSIONS_URL.format(cik=cik)).decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FilingDiscoveryError("SEC submissions response was invalid") from exc

    recent = (submissions.get("filings") or {}).get("recent") or {}
    rows: list[dict[str, str]] = []
    count = len(recent.get("form", []))
    for index in range(count):
        form = str(recent.get("form", [""])[index])
        if form not in forms:
            continue
        primary = str(recent.get("primaryDocument", [""])[index])
        accession = str(recent.get("accessionNumber", [""])[index]).replace("-", "")
        filing_date = str(recent.get("filingDate", [""])[index])
        report_date = str(recent.get("reportDate", [""])[index] or filing_date)
        if not _SAFE_DOCUMENT.fullmatch(primary) or not _SAFE_ACCESSION.fullmatch(accession):
            continue
        try:
            date.fromisoformat(filing_date)
        except ValueError:
            continue
        rows.append({
            "form": form,
            "primary": primary,
            "accession": accession,
            "filing_date": filing_date,
            "report_date": report_date,
        })
    if not rows:
        raise FilingNotFound("No recent SEC 10-K or 10-Q was found")
    row = max(rows, key=lambda item: item["filing_date"])
    url = SEC_ARCHIVE_URL.format(cik=int(cik), accession=row["accession"], document=row["primary"])
    content = _fetch(url, max_bytes=MAX_FILING_BYTES)
    sample = content[:4096].lower()
    if b"<html" not in sample and b"<!doctype" not in sample:
        raise FilingDiscoveryError("SEC filing was not a readable HTML document")
    safe_issuer = re.sub(r"[^A-Za-z0-9]+", "_", issuer).strip("_") or "company"
    filename = f"{safe_issuer}_{row['form'].replace('-', '')}_{row['report_date']}_{row['accession']}.html"
    return DiscoveredFiling(
        company=issuer,
        cik=cik,
        form=row["form"],
        filing_date=row["filing_date"],
        report_date=row["report_date"],
        filename=filename,
        source_url=url,
        content=content,
    )
