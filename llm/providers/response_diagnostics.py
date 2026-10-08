"""Content-free observational receipts; never used to admit a completion."""
import hashlib
import json


def safe_response_diagnostics(content, *, finish_reason=None, prompt_tokens=None,
                              completion_tokens=None, total_tokens=None, reasoning_tokens=None):
    text = content if isinstance(content, str) else ""
    raw = text.encode("utf-8", errors="replace")
    status, kind, claims = "NOT_APPLICABLE", None, None

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_):
        raise ValueError("non-finite JSON constant")

    if text.strip():
        status = "FAIL"
        try:
            parsed = json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)
            status = "PASS"
            kind = {dict: "object", list: "array", str: "string", int: "number",
                    float: "number", bool: "boolean", type(None): "null"}.get(type(parsed))
            if isinstance(parsed, dict) and isinstance(parsed.get("claims"), list):
                claims = len(parsed["claims"])
        except (ValueError, TypeError, RecursionError):
            pass
    def known(value):
        return value if type(value) is int and value >= 0 else None
    return {"visible_content_present": bool(text.strip()), "visible_char_count": len(text),
        "visible_utf8_bytes": len(raw), "visible_sha256": hashlib.sha256(raw).hexdigest(),
        "strict_json_parse": status, "top_level_type": kind, "claim_count": claims,
        "finish_reason": finish_reason if isinstance(finish_reason, str) else None,
        "prompt_tokens": known(prompt_tokens), "completion_tokens": known(completion_tokens),
        "total_tokens": known(total_tokens), "reasoning_tokens": known(reasoning_tokens)}
