"""One deterministic subject contract for serialization and claim admission."""

import hashlib
import json
from dataclasses import dataclass

from document_compatibility.narrative_subject_context import SUBJECT_CONTEXT_VERSION, explicitly_named_subject


@dataclass(frozen=True)
class NarrativeSubjectBinding:
    role: str
    page: int
    subject_name: str | None
    allowed_claim_prefixes: tuple[str, ...]
    context_sha256: str

    def allows(self, text):
        for prefix in self.allowed_claim_prefixes:
            if text.casefold().startswith(prefix.casefold()):
                remainder = text[len(prefix):]
                if prefix[-1].isascii() and prefix[-1].isalnum() and remainder and remainder[0].isalnum():
                    continue
                return True
        return False

    def to_dict(self):
        return {"role": self.role, "page": self.page, "subject_name": self.subject_name,
                "allowed_claim_prefixes": list(self.allowed_claim_prefixes),
                "context_sha256": self.context_sha256, "rule": SUBJECT_CONTEXT_VERSION}


def subject_binding(payload):
    encoded = payload.get("provenance", {}).get("subject_context")
    if encoded is None:
        return None
    if not isinstance(encoded, str):
        raise ValueError("INVALID_NARRATIVE_SUBJECT_CONTEXT")
    try:
        context = json.loads(encoded)
    except (ValueError, TypeError) as exc:
        raise ValueError("INVALID_NARRATIVE_SUBJECT_CONTEXT") from exc
    if (not isinstance(context, dict) or set(context) != {"role", "page", "context_text", "rule"}
            or context.get("role") != "CONTROLLING_SHAREHOLDER" or context.get("rule") != SUBJECT_CONTEXT_VERSION
            or type(context.get("page")) is not int or context["page"] < 1
            or type(payload.get("page")) is not int or context["page"] != payload["page"]
            or not isinstance(context.get("context_text"), str)
            or not context["context_text"].strip() or len(context["context_text"]) > 4096):
        raise ValueError("INVALID_NARRATIVE_SUBJECT_CONTEXT")
    name = explicitly_named_subject(context["context_text"])
    prefixes = ("控股股东", "控股股東", "The controlling shareholder", "Controlling shareholder")
    return NarrativeSubjectBinding(context["role"], context["page"], name,
        prefixes + ((name,) if name else ()), hashlib.sha256(context["context_text"].encode("utf-8")).hexdigest())
