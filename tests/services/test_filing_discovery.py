import json
from datetime import datetime, timezone
from urllib.parse import parse_qs

import pytest

from services import filing_discovery


class _Response:
    def __init__(self, payload: bytes, url: str = "https://www.sec.gov"):
        self._payload = payload
        self.headers = {}
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size: int = -1):
        if not self._payload:
            return b""
        payload, self._payload = self._payload[:size], self._payload[size:]
        return payload

    def geturl(self):
        return self._url


def test_discovery_rejects_non_sec_urls():
    with pytest.raises(filing_discovery.FilingDiscoveryError):
        filing_discovery._fetch("https://example.com/file.html")


def test_discovery_selects_latest_sec_10q(monkeypatch):
    ticker_index = {
        "0": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corporation"},
    }
    submissions = {
        "filings": {
            "recent": {
                "form": ["10-Q", "8-K", "10-K"],
                "primaryDocument": ["older.htm", "noise.htm", "annual.htm"],
                "accessionNumber": ["0000789019-25-000001", "0000789019-25-000002", "0000789019-25-000003"],
                "filingDate": ["2025-01-01", "2025-02-01", "2024-11-01"],
                "reportDate": ["2024-12-31", "2025-01-31", "2024-09-30"],
            }
        }
    }
    calls: list[str] = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if request.full_url.endswith("company_tickers.json"):
            return _Response(json.dumps(ticker_index).encode(), request.full_url)
        if "/submissions/CIK0000789019.json" in request.full_url:
            return _Response(json.dumps(submissions).encode(), request.full_url)
        return _Response(
            b"<!doctype html><html><body>Microsoft filing revenue table</body></html>",
            request.full_url,
        )

    monkeypatch.setattr(filing_discovery, "urlopen", fake_urlopen)
    result = filing_discovery.discover_latest_sec_filing("Microsoft")

    assert result.company == "Microsoft Corporation"
    assert result.form == "10-Q"
    assert result.report_date == "2024-12-31"
    assert result.filename.endswith(".html")
    assert result.source_url.startswith("https://www.sec.gov/Archives/")
    assert len(calls) == 3


def test_discovery_fails_closed_for_ambiguous_company(monkeypatch):
    ticker_index = {
        "0": {"cik_str": 1, "ticker": "ABC", "title": "ABC Holdings"},
        "1": {"cik_str": 2, "ticker": "ABD", "title": "ABC Technologies"},
    }
    monkeypatch.setattr(
        filing_discovery,
        "urlopen",
        lambda request, timeout: _Response(json.dumps(ticker_index).encode(), request.full_url),
    )
    with pytest.raises(filing_discovery.FilingNotFound):
        filing_discovery.discover_latest_sec_filing("ABC")


def _audit_pdf() -> bytes:
    import fitz

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text(
        (72, 72),
        "\u8d35\u5dde\u8305\u53f0\u80a1\u4efd\u6709\u9650\u516c\u53f8 2025 \u5e74\u5e74\u5ea6\u62a5\u544a",
        fontname="china-s",
    )
    audit_page = pdf.new_page()
    audit_page.insert_text(
        (72, 72),
        "\u5ba1\u8ba1\u62a5\u544a \u5929\u5065\u5ba1\u30142026\u30158-346\u53f7",
        fontname="china-s",
    )
    content = pdf.tobytes()
    pdf.close()
    return content


def test_cninfo_discovery_selects_full_annual_report_and_verifies_audit_pdf(monkeypatch):
    timestamp = int(datetime(2026, 4, 17, tzinfo=timezone.utc).timestamp() * 1000)
    calls: list[tuple[str, str, dict[str, list[str]]]] = []
    pdf_content = _audit_pdf()

    def fake_urlopen(request, timeout):
        body = parse_qs((request.data or b"").decode("utf-8"))
        calls.append((request.full_url, request.get_method(), body))
        if request.full_url.endswith("topSearch/query"):
            return _Response(json.dumps([{
                "code": "600519",
                "orgId": "gssh0600519",
                "zwjc": "\u8d35\u5dde\u8305\u53f0",
                "category": "A\u80a1",
            }], ensure_ascii=False).encode("utf-8"), request.full_url)
        if request.full_url.endswith("hisAnnouncement/query"):
            return _Response(json.dumps({"announcements": [
                {
                    "announcementTitle": "\u8d35\u5dde\u8305\u53f02025\u5e74\u5e74\u5ea6\u62a5\u544a\u6458\u8981",
                    "announcementTime": timestamp,
                    "adjunctUrl": "finalpage/2026-04-17/1225114740.PDF",
                },
                {
                    "announcementTitle": "\u8d35\u5dde\u8305\u53f02025\u5e74\u5e74\u5ea6\u62a5\u544a\uff08\u82f1\u6587\u7248\uff09",
                    "announcementTime": timestamp,
                    "adjunctUrl": "finalpage/2026-04-17/1225114742.PDF",
                },
                {
                    "announcementTitle": "\u8d35\u5dde\u8305\u53f02025\u5e74\u5e74\u5ea6\u62a5\u544a",
                    "announcementTime": timestamp,
                    "adjunctUrl": "finalpage/2026-04-17/1225114741.PDF",
                },
            ]}, ensure_ascii=False).encode("utf-8"), request.full_url)
        return _Response(pdf_content, request.full_url)

    monkeypatch.setattr(filing_discovery, "urlopen", fake_urlopen)
    result = filing_discovery.discover_latest_company_filing("\u8d35\u5dde\u8305\u53f0")

    assert result.company == "\u8d35\u5dde\u8305\u53f0"
    assert result.source_type == "cninfo"
    assert result.stock_code == "600519"
    assert result.exchange == "sse"
    assert result.report_type == "annual"
    assert result.report_year == 2025
    assert result.audited is True
    assert result.report_date == "2025-12-31"
    assert result.source_url == (
        "https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF"
    )
    assert result.content.startswith(b"%PDF-")
    assert calls[0][2]["keyWord"] == ["\u8d35\u5dde\u8305\u53f0"]
    assert calls[1][2]["column"] == ["sse"]
    assert calls[1][2]["category"] == ["category_ndbg_szsh"]
    assert calls[2][0].startswith("https://static.cninfo.com.cn/")


def test_cninfo_rejects_non_exact_or_ambiguous_company(monkeypatch):
    monkeypatch.setattr(
        filing_discovery,
        "urlopen",
        lambda request, timeout: _Response(json.dumps([
            {"code": "600519", "orgId": "gssh0600519", "zwjc": "\u8d35\u5dde\u8305\u53f0", "category": "A\u80a1"},
            {"code": "000858", "orgId": "gssz0000858", "zwjc": "\u4e94\u7cae\u6db2", "category": "A\u80a1"},
        ], ensure_ascii=False).encode("utf-8"), request.full_url),
    )
    with pytest.raises(filing_discovery.FilingNotFound):
        filing_discovery.discover_latest_cninfo_annual_report("\u8305\u53f0")


def test_cninfo_rejects_wrong_exchange_suffix(monkeypatch):
    monkeypatch.setattr(
        filing_discovery,
        "urlopen",
        lambda request, timeout: _Response(json.dumps([
            {"code": "600519", "orgId": "gssh0600519", "zwjc": "\u8d35\u5dde\u8305\u53f0", "category": "A\u80a1"},
        ], ensure_ascii=False).encode("utf-8"), request.full_url),
    )
    with pytest.raises(filing_discovery.FilingNotFound, match="suffix"):
        filing_discovery._resolve_cninfo_company("600519.SZ")


def test_cninfo_rejects_untrusted_hosts_and_unsafe_artifact_paths():
    with pytest.raises(filing_discovery.FilingDiscoveryError):
        filing_discovery._cninfo_fetch("https://example.com/file.pdf")
    with pytest.raises(filing_discovery.FilingDiscoveryError):
        filing_discovery.discover_latest_cninfo_annual_report("../outside")


def test_cninfo_rejects_non_pdf_and_pdf_without_audit_section():
    with pytest.raises(filing_discovery.FilingDiscoveryError, match="not a PDF"):
        filing_discovery._verify_cninfo_audited_pdf(b"<html>not a pdf</html>")
    import fitz

    pdf = fitz.open()
    pdf.new_page().insert_text((72, 72), "公司年度报告")
    pdf.new_page().insert_text((72, 72), "财务报表")
    content = pdf.tobytes()
    pdf.close()
    with pytest.raises(filing_discovery.FilingDiscoveryError, match="audit report section"):
        filing_discovery._verify_cninfo_audited_pdf(content)
