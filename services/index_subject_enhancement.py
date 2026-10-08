"""Optional source-bound subject metadata; legacy semantics remain unchanged."""
import json

from document_compatibility.narrative_subject_context import (
    SUBJECT_CONTEXT_VERSION,
    controlling_shareholder_contexts,
)


class SubjectContextIndexEnhancement:
    version = SUBJECT_CONTEXT_VERSION

    def project(self, chunks):
        result = []
        for context in controlling_shareholder_contexts(chunks):
            metadata = {"subject_context_version": self.version}
            if context is not None:
                metadata["subject_context"] = json.dumps(context, ensure_ascii=False, sort_keys=True)
            result.append(metadata)
        return tuple(result)
