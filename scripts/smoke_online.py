#!/usr/bin/env python3
"""Credential-free post-deployment health smoke check."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


def get_json(url: str) -> tuple[int, object]:
    request = urllib.request.Request(url, headers={"User-Agent": "financial-rag-smoke/1"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.load(response)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"request failed: {url}: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    results: dict[str, int] = {}
    for path in ("/api/v1/health", "/api/v1/ready"):
        status, body = get_json(base + path)
        if status != 200 or not isinstance(body, dict) or body.get("status") != "ok":
            print(json.dumps({"status": "FAIL", "endpoint": path, "http": status}))
            return 1
        results[path] = status
    print(json.dumps({"status": "PASS", "base_url": base, "endpoints": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
