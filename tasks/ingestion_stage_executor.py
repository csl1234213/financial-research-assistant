"""Execute actual operators outside transactions, then commit with lease fencing."""

from core.ingestion_contracts import StageLeaseLost
from tasks.ingestion_fact_stage import FinancialFactStage
from tasks.ingestion_parse_stage import PDFParseStage
from tasks.ingestion_quality_stage import PDFQualityStage
from tasks.ingestion_tree_stage import FinancialTreeStage


class IngestionStageExecutor:
    def __init__(self, ledger, *, source_resolver, clock, index_operator=None, ocr=None):
        self.ledger = ledger
        self.source_resolver = source_resolver
        self.clock = clock
        self.parser = PDFParseStage(ledger.artifact_store, ocr=ocr)
        self.quality = PDFQualityStage(ledger.artifact_store, ocr=ocr)
        self.facts = FinancialFactStage(ledger.artifact_store)
        self.tree = FinancialTreeStage(ledger.artifact_store)
        self.index = index_operator

    def run_one(self, task_id):
        lease = self.ledger.claim(task_id, self.clock())
        if lease is None:
            return "not_claimed"
        try:
            if lease.stage == "PARSING":
                receipt = self.parser.execute(lease, self.source_resolver(lease))
            elif lease.stage == "QUALITY_CHECK":
                digest = self.ledger.prior_artifact(lease, "PARSING", now=self.clock())
                receipt = self.quality.execute(lease, parse_artifact_sha256=digest)
            elif lease.stage == "BUILDING_FACTS":
                parsed = self.ledger.prior_artifact(lease, "PARSING", now=self.clock())
                quality = self.ledger.prior_artifact(lease, "QUALITY_CHECK", now=self.clock())
                receipt = self.facts.execute(lease, parse_artifact_sha256=parsed,
                                             quality_artifact_sha256=quality)
            elif lease.stage == "BUILDING_TREE":
                parsed = self.ledger.prior_artifact(lease, "PARSING", now=self.clock())
                quality = self.ledger.prior_artifact(lease, "QUALITY_CHECK", now=self.clock())
                receipt = self.tree.execute(lease, parse_artifact_sha256=parsed,
                                            quality_artifact_sha256=quality)
            elif lease.stage == "INDEXING" and self.index is not None:
                parsed = self.ledger.prior_artifact(lease, "PARSING", now=self.clock())
                quality = self.ledger.prior_artifact(lease, "QUALITY_CHECK", now=self.clock())
                receipt = self.index.execute(lease, parse_artifact_sha256=parsed,
                                             quality_artifact_sha256=quality)
            else:
                raise ValueError("STAGE_OPERATOR_NOT_IMPLEMENTED")
        except StageLeaseLost:
            return "lease_lost"
        except (TimeoutError, ConnectionError):
            return self._fail(lease, "STAGE_TRANSIENT_FAILURE", retryable=True)
        except (ValueError, PermissionError, FileNotFoundError):
            # Do not leak local paths, source text or arbitrary exception messages.
            return self._fail(lease, "STAGE_OPERATOR_FAILURE", retryable=False)
        except Exception:
            # Unknown operator defects get a finite recovery budget, not an
            # infinite loop or a fabricated successful stage checkpoint.
            return self._fail(lease, "STAGE_UNKNOWN_FAILURE", retryable=True)
        if not self.ledger.finish(lease, now=self.clock(), **receipt):
            return "lease_lost"
        return "quarantined" if receipt.get("quality_status") == "FAIL" else "completed"

    def _fail(self, lease, code, *, retryable):
        committed = self.ledger.finish(lease, now=self.clock(), error_code=code, retryable=retryable)
        return "failed" if committed else "lease_lost"
