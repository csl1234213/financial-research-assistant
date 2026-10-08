"""Controlled projection inputs for index unit tests, with no SQL bootstrap."""

import json
from types import SimpleNamespace

SOURCE_SHA = "a" * 64


def prepare(store):
    chunks = [
        {"text": "控股股东 名称 示例集团有限公司", "page": 1, "section": "控股股东情况"},
        {"text": "主要业务：制造", "page": 1, "section": "业务"},
    ]
    parsed = {"document_id": 42, "tenant_id": 1, "source_sha256": SOURCE_SHA, "chunks": chunks}
    parse = store.put(1, SOURCE_SHA, json.dumps(parsed, ensure_ascii=False).encode())
    quality = store.put(1, SOURCE_SHA, json.dumps({
        "quality_status": "PASS", "source_sha256": SOURCE_SHA, "parse_artifact_sha256": parse,
    }).encode())
    lease = SimpleNamespace(stage="INDEXING", tenant_id=1, document_id=42, source_sha256=SOURCE_SHA)
    return lease, parse, quality
