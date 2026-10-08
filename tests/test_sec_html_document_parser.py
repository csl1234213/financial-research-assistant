from pathlib import Path

from document_formats import load_structured_document_chunks, validate_document_payload


def test_sec_html_validation_and_table_row_preservation(tmp_path: Path):
    payload = b"""
    <!doctype html><html><body>
      <h1>Microsoft Corporation</h1>
      <p>Quarterly report for the period ended December 31, 2024.</p>
      <table><tr><th>Revenue</th><th>Q2 2025</th></tr>
      <tr><td>Azure revenue</td><td>$28.5 billion</td></tr></table>
    </body></html>
    """
    assert validate_document_payload("microsoft_10q.html", payload) == ".html"
    path = tmp_path / "microsoft_10q.html"
    path.write_bytes(payload)
    chunks = load_structured_document_chunks(path, chunk_size=1000, overlap=0)
    text = "\n".join(chunk.text for chunk in chunks)
    assert "Azure revenue" in text
    assert "$28.5 billion" in text


def test_sec_html_rejects_empty_document():
    payload = b"<html><body><script>secret()</script></body></html>"
    try:
        validate_document_payload("empty.html", payload)
    except ValueError as exc:
        assert "meaningful report text" in str(exc)
    else:
        raise AssertionError("empty HTML should be rejected")
